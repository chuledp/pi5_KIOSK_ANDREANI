"""
Receptor OSC (Open Sound Control) ligero en Python puro.
No requiere dependencias externas (compatible con Debian 12 / Raspberry Pi OS PEP 668).
Recibe mensajes UDP de Resolume, TouchDesigner, Reaper, QLC+ o de una Raspberry Pi Master.
"""

import socket
import struct
import threading
from typing import Callable, Dict, List, Any, Optional

def _pad4(length: int) -> int:
    """Calcula el relleno necesario para alinear a 4 bytes."""
    rem = length % 4
    return 0 if rem == 0 else 4 - rem

def parse_osc_message(data: bytes) -> Optional[tuple[str, List[Any]]]:
    """
    Decodifica un paquete binario OSC en (dirección, lista_de_argumentos).
    """
    try:
        # 1. Leer dirección (terminada en null y alineada a 4 bytes)
        null_idx = data.find(b'\x00')
        if null_idx == -1:
            return None
        address = data[:null_idx].decode('utf-8', errors='ignore')
        offset = null_idx + 1 + _pad4(null_idx + 1)

        if offset >= len(data):
            return address, []

        # 2. Leer type tags (inicia con ',')
        args: List[Any] = []
        if data[offset:offset+1] == b',':
            type_tag_end = data.find(b'\x00', offset)
            if type_tag_end == -1:
                return address, []
            type_tags = data[offset+1:type_tag_end].decode('utf-8', errors='ignore')
            offset = type_tag_end + 1 + _pad4(type_tag_end + 1)

            # 3. Leer cada argumento según su tag
            for tag in type_tags:
                if offset >= len(data):
                    break
                if tag == 'f':  # Float32 big-endian
                    val = struct.unpack('>f', data[offset:offset+4])[0]
                    args.append(val)
                    offset += 4
                elif tag == 'i':  # Int32 big-endian
                    val = struct.unpack('>i', data[offset:offset+4])[0]
                    args.append(val)
                    offset += 4
                elif tag == 's':  # String terminada en null
                    str_end = data.find(b'\x00', offset)
                    if str_end != -1:
                        val = data[offset:str_end].decode('utf-8', errors='ignore')
                        offset = str_end + 1 + _pad4(str_end + 1)
                        args.append(val)
                elif tag == 'b':  # Blob
                    blob_len = struct.unpack('>i', data[offset:offset+4])[0]
                    offset += 4
                    val = data[offset:offset+blob_len]
                    offset += blob_len + _pad4(blob_len)
                    args.append(val)
                elif tag == 'T':  # True
                    args.append(True)
                elif tag == 'F':  # False
                    args.append(False)
        return address, args
    except Exception as e:
        print(f"Error decodificando OSC: {e}")
        return None

def build_osc_message(address: str, args: Optional[List[Any]] = None) -> bytes:
    """
    Codifica una dirección y argumentos en un mensaje binario OSC.
    """
    args = args or []
    # Codificar dirección alineada a 4 bytes
    addr_bytes = address.encode('utf-8') + b'\x00'
    addr_bytes += b'\x00' * _pad4(len(addr_bytes))

    # Construir type tags
    tags = ','
    payload = bytearray()
    for arg in args:
        if isinstance(arg, float):
            tags += 'f'
            payload.extend(struct.pack('>f', arg))
        elif isinstance(arg, int) and not isinstance(arg, bool):
            tags += 'i'
            payload.extend(struct.pack('>i', arg))
        elif isinstance(arg, str):
            tags += 's'
            s_bytes = arg.encode('utf-8') + b'\x00'
            s_bytes += b'\x00' * _pad4(len(s_bytes))
            payload.extend(s_bytes)
        elif isinstance(arg, bool):
            tags += 'T' if arg else 'F'
        elif isinstance(arg, bytes):
            tags += 'b'
            b_len = len(arg)
            payload.extend(struct.pack('>i', b_len))
            b_padded = arg + (b'\x00' * _pad4(b_len))
            payload.extend(b_padded)

    tags_bytes = tags.encode('utf-8') + b'\x00'
    tags_bytes += b'\x00' * _pad4(len(tags_bytes))

    return addr_bytes + tags_bytes + bytes(payload)

class OSCReceiver:
    def __init__(self, port: int = 9000, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self.sock: Optional[socket.socket] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self.callbacks: Dict[str, List[Callable[[str, List[Any]], None]]] = {}
        self.any_callbacks: List[Callable[[str, List[Any]], None]] = []

    def on(self, address: str, callback: Callable[[str, List[Any]], None]):
        """Registra un callback para una dirección OSC específica."""
        if address not in self.callbacks:
            self.callbacks[address] = []
        self.callbacks[address].append(callback)

    def on_any(self, callback: Callable[[str, List[Any]], None]):
        """Registra un callback para cualquier mensaje OSC recibido."""
        self.any_callbacks.append(callback)

    def start(self):
        if self.is_running:
            return

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Permitir reuso de puerto
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.settimeout(0.5)

        self.is_running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def _listen_loop(self):
        while self.is_running and self.sock:
            try:
                data, addr = self.sock.recvfrom(4096)
                parsed = parse_osc_message(data)
                if not parsed:
                    continue
                osc_addr, osc_args = parsed

                # Disparar callbacks genéricos (para monitor en vivo)
                for cb in self.any_callbacks:
                    try:
                        cb(osc_addr, osc_args)
                    except Exception as err:
                        print(f"Error en on_any callback: {err}")

                # Disparar callbacks específicos
                if osc_addr in self.callbacks:
                    for cb in self.callbacks[osc_addr]:
                        try:
                            cb(osc_addr, osc_args)
                        except Exception as err:
                            print(f"Error en callback {osc_addr}: {err}")

            except socket.timeout:
                continue
            except Exception as e:
                if self.is_running:
                    print(f"Error en listener OSC: {e}")
                break

    def stop(self):
        self.is_running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
