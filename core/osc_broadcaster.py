"""
Emisor / Broadcaster OSC en Python puro.
Permite a una Raspberry Pi actuar como Master y transmitir pulsos de sincronización y cues por red.
"""

import socket
import time
import threading
from typing import List, Any, Optional, Callable

from core.osc_receiver import build_osc_message

class OSCBroadcaster:
    def __init__(self, target_host: str = "255.255.255.255", port: int = 9000):
        self.target_host = target_host
        self.port = port
        self.sock: Optional[socket.socket] = None
        self._init_socket()

        # Ticker para reloj de sincronización maestro
        self.is_broadcasting = False
        self._sync_thread: Optional[threading.Thread] = None
        self.get_current_time_fn: Optional[Callable[[], float]] = None
        self.interval = 0.15  # 150ms

    def _init_socket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Habilitar broadcast UDP
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def send(self, address: str, args: Optional[List[Any]] = None):
        """Envía un paquete OSC a la red."""
        if not self.sock:
            self._init_socket()
        try:
            packet = build_osc_message(address, args)
            self.sock.sendto(packet, (self.target_host, self.port))
        except Exception as e:
            print(f"Error enviando OSC a {self.target_host}:{self.port}: {e}")

    def start_clock_sync(self, get_time_fn: Callable[[], float], interval: float = 0.15):
        """Inicia el envío periódico de /sync/clock con el tiempo actual del master."""
        if self.is_broadcasting:
            return
        self.get_current_time_fn = get_time_fn
        self.interval = interval
        self.is_broadcasting = True
        self._sync_thread = threading.Thread(target=self._clock_loop, daemon=True)
        self._sync_thread.start()

    def _clock_loop(self):
        while self.is_broadcasting:
            if self.get_current_time_fn:
                try:
                    curr_time = self.get_current_time_fn()
                    if curr_time >= 0:
                        self.send("/sync/clock", [float(curr_time)])
                except Exception as e:
                    print(f"Error en loop de reloj sync: {e}")
            time.sleep(self.interval)

    def stop_clock_sync(self):
        self.is_broadcasting = False
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=0.5)
            self._sync_thread = None

    def close(self):
        self.stop_clock_sync()
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
