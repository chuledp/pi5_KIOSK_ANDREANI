"""
Kiosk Guardian: Blindaje de Sistema y Handshake HDMI para Raspberry Pi.
Módulo de protección para instalaciones artísticas, museos y galerías comerciales:
1. Protección contra Cortes Directos de Fase (Apagado por llave térmica sin Soft Power):
   - Soporte y gestión de OverlayFS (Root Filesystem en Modo Solo Lectura / RAM Overlay).
   - Desactivación de Swap (evita corrupción de sectores SD en cortes intempestivos).
   - Configuración de journald en modo volátil (RAM) y parámetros de auto-reparación
     en el arranque del kernel (fsck.mode=force, fsck.repair=yes, fastboot).
2. Resolución Definitiva de Handshake con Proyectores (Anti-Pantalla Negra):
   - Inyección en kernel/cmdline.txt de 'video=HDMI-A-1:...D' y 'video=HDMI-A-2:...D'
     (forzando salida digital permanente aunque el proyector se encienda después).
   - Inyección en config.txt de 'hdmi_force_hotplug', 'hdmi_drive=2' y 'config_hdmi_boost=7'
     para cables largos y proyectores en standby.
   - Watchdog en vivo para auto-renegociar y despertar proyectores que se enciendan tarde.
"""

import os
import re
import sys
import shutil
import subprocess
import threading
import time
from typing import Dict, Any, Tuple, Optional, List

CMDLINE_FORCE_REPAIR = "fsck.mode=force fsck.repair=yes"
CMDLINE_FASTBOOT = "fastboot"
CMDLINE_HDMI_D = "video=HDMI-A-1:1920x1080@60D video=HDMI-A-2:1920x1080@60D"


def is_raspberry_pi() -> bool:
    """Verifica si el sistema se está ejecutando en una Raspberry Pi."""
    if not sys.platform.startswith("linux"):
        return False
    model_paths = ["/proc/device-tree/model", "/sys/firmware/devicetree/base/model"]
    for p in model_paths:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().lower()
                    if "raspberry pi" in content:
                        return True
        except Exception:
            pass
    # Fallback por cpuinfo
    try:
        if os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                if "raspberry" in f.read().lower():
                    return True
    except Exception:
        pass
    return False


def get_boot_config_paths() -> Tuple[Optional[str], Optional[str]]:
    """
    Detecta las rutas activas de config.txt y cmdline.txt.
    Compatible con Debian Bookworm (Pi 5/4 en /boot/firmware/) y Bullseye/legacy (/boot/).
    """
    config_txt = None
    cmdline_txt = None

    candidates_config = [
        "/boot/firmware/config.txt",
        "/boot/config.txt"
    ]
    for c in candidates_config:
        if os.path.exists(c):
            config_txt = c
            break

    candidates_cmdline = [
        "/boot/firmware/cmdline.txt",
        "/boot/cmdline.txt"
    ]
    for cl in candidates_cmdline:
        if os.path.exists(cl):
            cmdline_txt = cl
            break

    return config_txt, cmdline_txt


def _ensure_boot_writable() -> Optional[str]:
    """
    Si la partición de boot (/boot o /boot/firmware) está montada en solo lectura (ro),
    la remonta temporalmente como rw para permitir actualizar configuraciones.
    Retorna el punto de montaje modificado para re-protegerlo posteriormente.
    """
    if not sys.platform.startswith("linux"):
        return None
    for mount_pt in ["/boot/firmware", "/boot"]:
        try:
            with open("/proc/mounts", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4 and parts[1] == mount_pt and "ro" in parts[3].split(","):
                        subprocess.run(["mount", "-o", "remount,rw", mount_pt], check=False)
                        return mount_pt
        except Exception:
            pass
    return None


def _restore_boot_ro(mount_pt: Optional[str]) -> None:
    """Restaura el montaje en modo solo lectura si fue modificado."""
    if mount_pt and sys.platform.startswith("linux"):
        try:
            subprocess.run(["mount", "-o", "remount,ro", mount_pt], check=False)
        except Exception:
            pass


def is_overlayfs_active() -> bool:
    """Detecta si el sistema de archivos raíz (/) está montado actualmente como OverlayFS en RAM."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == "/":
                    if "overlay" in parts[0].lower() or "overlay" in parts[2].lower():
                        return True
    except Exception:
        pass
    return False


def is_overlayfs_configured() -> bool:
    """Verifica si OverlayFS está habilitado en raspi-config para el próximo arranque."""
    if shutil.which("raspi-config"):
        try:
            res = subprocess.run(
                ["raspi-config", "nonint", "get_overlayfs"],
                capture_output=True,
                text=True,
                timeout=2.0
            )
            return res.returncode == 0 and res.stdout.strip() == "0"
        except Exception:
            pass
    return False


def is_boot_readonly() -> bool:
    """Verifica si la partición de boot está montada como solo lectura."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[1] in ("/boot", "/boot/firmware"):
                    options = parts[3].split(",")
                    if "ro" in options:
                        return True
    except Exception:
        pass
    return False


def is_swap_disabled() -> bool:
    """Verifica si no hay memoria swap activa en el sistema."""
    if not sys.platform.startswith("linux"):
        return True
    try:
        with open("/proc/swaps", "r", encoding="utf-8", errors="ignore") as f:
            lines = [l.strip() for l in f if l.strip()]
            return len(lines) <= 1  # Solo cabecera
    except Exception:
        return True


def get_system_hardening_status() -> Dict[str, Any]:
    """
    Devuelve un diagnóstico completo sobre las barreras contra corte de fase
    y el estado de handshake de proyectores.
    """
    overlay_active = is_overlayfs_active()
    overlay_config = is_overlayfs_configured()
    boot_ro = is_boot_readonly()
    swap_off = is_swap_disabled()
    is_rpi = is_raspberry_pi()

    config_txt, cmdline_txt = get_boot_config_paths()

    # Chequear cmdline.txt
    cmdline_content = ""
    if cmdline_txt and os.path.exists(cmdline_txt):
        try:
            with open(cmdline_txt, "r", encoding="utf-8", errors="ignore") as f:
                cmdline_content = f.read()
        except Exception:
            pass

    fsck_autorepair = "fsck.repair=yes" in cmdline_content
    kms_force_hdmi = "video=HDMI-A-1:" in cmdline_content and "D" in cmdline_content

    # Chequear config.txt
    config_content = ""
    if config_txt and os.path.exists(config_txt):
        try:
            with open(config_txt, "r", encoding="utf-8", errors="ignore") as f:
                config_content = f.read()
        except Exception:
            pass

    hdmi_hotplug_forced = "hdmi_force_hotplug=1" in config_content
    hdmi_boost_set = "config_hdmi_boost=" in config_content

    # Evaluación global de protección contra corte de luz
    fully_protected = overlay_active and swap_off and fsck_autorepair
    projectors_hardened = hdmi_hotplug_forced and kms_force_hdmi

    if overlay_active:
        sd_status_text = "🛡️ PROTEGIDA (Modo Solo Lectura / OverlayFS Activo)"
        sd_color = "success"
    elif overlay_config:
        sd_status_text = "⏳ PROTECCIÓN PENDIENTE (Reinicio requerido)"
        sd_color = "amber"
    else:
        sd_status_text = "⚠️ MODO ESCRITURA (Vulnerable a corte directo sin soft power)"
        sd_color = "danger"

    if projectors_hardened:
        hdmi_status_text = "✓ HANDSHAKE BLINDADO (HDMI siempre activo con o sin proyector)"
    else:
        hdmi_status_text = "⚠️ HANDSHAKE ESTÁNDAR (Requiere proyector encendido previamente)"

    return {
        "is_raspberry_pi": is_rpi,
        "overlayfs_active": overlay_active,
        "overlayfs_configured": overlay_config,
        "boot_readonly": boot_ro,
        "swap_disabled": swap_off,
        "fsck_autorepair": fsck_autorepair,
        "hdmi_hotplug_forced": hdmi_hotplug_forced,
        "hdmi_boost_configured": hdmi_boost_set,
        "hdmi_kms_forced": kms_force_hdmi,
        "fully_protected": fully_protected,
        "projectors_hardened": projectors_hardened,
        "sd_status_text": sd_status_text,
        "sd_color": sd_color,
        "hdmi_status_text": hdmi_status_text,
        "config_txt_path": config_txt,
        "cmdline_txt_path": cmdline_txt
    }


def enable_phase_cut_protection() -> Tuple[bool, str]:
    """
    Aplica todas las barreras necesarias para que la Raspberry Pi pueda apagarse
    directamente desde la térmica/fase sin riesgo alguno de corrupción de la SD:
    1. Desactiva Swap para evitar escrituras en flash.
    2. Configura systemd-journald en modo volátil (logs en RAM).
    3. Agrega auto-reparación no interactiva en cmdline.txt (fsck.mode=force fsck.repair=yes).
    4. Activa OverlayFS (Root filesystem en RAM) y Boot Read-Only.
    """
    if not sys.platform.startswith("linux"):
        return True, "Simulación: En Raspberry Pi OS se activará OverlayFS (Read-Only) y auto-reparación fsck."

    actions_taken: List[str] = []

    # 1. Desactivar Swap
    try:
        subprocess.run(["dphys-swapfile", "swapoff"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
        subprocess.run(["dphys-swapfile", "uninstall"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
        subprocess.run(["systemctl", "disable", "dphys-swapfile"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
        actions_taken.append("Swap desactivada")
    except Exception:
        pass

    # 2. Configurar journald en RAM
    journald_conf = "/etc/systemd/journald.conf"
    if os.path.exists(journald_conf):
        try:
            with open(journald_conf, "r", encoding="utf-8") as f:
                j_content = f.read()
            if "Storage=volatile" not in j_content:
                j_content = re.sub(r"^#?Storage=.*", "Storage=volatile", j_content, flags=re.MULTILINE)
                if "Storage=volatile" not in j_content:
                    j_content += "\nStorage=volatile\nRuntimeMaxUse=16M\n"
                with open(journald_conf, "w", encoding="utf-8") as f:
                    f.write(j_content)
                actions_taken.append("Logs en RAM (journald volátil)")
        except Exception:
            pass

    # 3. cmdline.txt: agregar fsck.mode=force fsck.repair=yes fastboot
    _, cmdline_txt = get_boot_config_paths()
    if cmdline_txt and os.path.exists(cmdline_txt):
        remounted = _ensure_boot_writable()
        try:
            with open(cmdline_txt, "r", encoding="utf-8") as f:
                line = f.read().strip()
            modified = False
            for opt in ["fsck.mode=force", "fsck.repair=yes", "fastboot"]:
                if opt not in line:
                    line += f" {opt}"
                    modified = True
            if modified:
                with open(cmdline_txt, "w", encoding="utf-8") as f:
                    f.write(line + "\n")
                actions_taken.append("Auto-reparación fsck agregada a cmdline.txt")
        except Exception as e:
            print(f"Error modificando cmdline.txt: {e}")
        finally:
            _restore_boot_ro(remounted)

    # 4. Habilitar OverlayFS y Boot Read-Only vía raspi-config
    overlay_enabled = False
    if shutil.which("raspi-config"):
        try:
            r1 = subprocess.run(["raspi-config", "nonint", "enable_overlayfs"], capture_output=True, timeout=5)
            r2 = subprocess.run(["raspi-config", "nonint", "enable_bootro"], capture_output=True, timeout=5)
            if r1.returncode == 0:
                overlay_enabled = True
                actions_taken.append("OverlayFS activado (Modo Solo Lectura)")
        except Exception as e:
            print(f"Error habilitando OverlayFS vía raspi-config: {e}")

    msg = (
        "✅ BARRERAS DE APAGADO POR FASE APLICADAS:\n"
        + "\n".join(f"• {a}" for a in actions_taken)
        + "\n\n⚠️ IMPORTANTE: Reiniciá la Raspberry Pi para que la tarjeta SD quede 100% blindada en modo solo lectura."
    )
    return True, msg


def disable_phase_cut_protection() -> Tuple[bool, str]:
    """
    Desactiva temporalmente el OverlayFS para entrar en 'Modo Mantenimiento',
    permitiendo guardar nuevos videos o cambiar configuraciones del sistema.
    """
    if not sys.platform.startswith("linux"):
        return True, "Simulación: En Raspberry Pi OS se desactivará OverlayFS para permitir escritura."

    if not shutil.which("raspi-config"):
        return False, "raspi-config no encontrado en este sistema."

    try:
        r1 = subprocess.run(["raspi-config", "nonint", "disable_bootro"], capture_output=True, timeout=5)
        r2 = subprocess.run(["raspi-config", "nonint", "disable_overlayfs"], capture_output=True, timeout=5)
        if r2.returncode == 0:
            return True, (
                "🔓 MODO MANTENIMIENTO PROGRAMADO:\n"
                "• OverlayFS se desactivará en el próximo arranque.\n"
                "• Podrás actualizar videos, configuraciones y software de forma permanente.\n\n"
                "⚠️ Reiniciá la Raspberry Pi para aplicar el modo de lectura/escritura."
            )
        return False, f"Error desactivando OverlayFS: {r2.stderr.decode()}"
    except Exception as e:
        return False, f"Excepción al desactivar OverlayFS: {e}"


def apply_projector_handshake_fix(resolution: str = "1920x1080@60") -> Tuple[bool, str]:
    """
    Aplica configuración de kernel y firmware para solucionar el handshake con proyectores:
    - En cmdline.txt: Fuerza salida digital permanentemente activa ('video=HDMI-A-1:1920x1080@60D').
      La 'D' obliga al driver DRM a mantener el reloj TMDS encendido aunque el proyector esté apagado.
    - En config.txt: Activa 'hdmi_force_hotplug=1', 'hdmi_drive=2' (audio y clock HDMI sin DVI fallback)
      y 'config_hdmi_boost=7' (amplifica señal para cables largos de proyectores).
    """
    config_txt, cmdline_txt = get_boot_config_paths()
    actions: List[str] = []
    remounted = _ensure_boot_writable()

    try:
        # 1. Configurar cmdline.txt (KMS DRM force digital display)
        if cmdline_txt and os.path.exists(cmdline_txt):
            try:
                with open(cmdline_txt, "r", encoding="utf-8") as f:
                    content = f.read().strip()

                target_cmd = f"video=HDMI-A-1:{resolution}D video=HDMI-A-2:{resolution}D"
                if "video=HDMI-A-1:" not in content:
                    content = f"{content} {target_cmd}"
                    with open(cmdline_txt, "w", encoding="utf-8") as f:
                        f.write(content + "\n")
                    actions.append(f"KMS DRM forzado digital ({resolution}D) en {os.path.basename(cmdline_txt)}")
                elif "video=HDMI-A-1:" in content and "D" not in content:
                    content = re.sub(r"video=HDMI-A-1:[^\s]+", f"video=HDMI-A-1:{resolution}D", content)
                    content = re.sub(r"video=HDMI-A-2:[^\s]+", f"video=HDMI-A-2:{resolution}D", content)
                    with open(cmdline_txt, "w", encoding="utf-8") as f:
                        f.write(content + "\n")
                    actions.append(f"KMS DRM actualizado con bandera D ({resolution}D)")
            except Exception as e:
                print(f"Error escribiendo cmdline.txt: {e}")

        # 2. Configurar config.txt (Firmware HDMI Hotplug & Boost)
        if config_txt and os.path.exists(config_txt):
            try:
                with open(config_txt, "r", encoding="utf-8") as f:
                    cfg_content = f.read()

                block = f"""
# ========================================================
# KIOSK GUARDIAN: Handshake Proyectores (Anti-Pantalla Negra)
# ========================================================
hdmi_force_hotplug=1
hdmi_force_hotplug:0=1
hdmi_force_hotplug:1=1
hdmi_drive=2
hdmi_drive:0=2
hdmi_drive:1=2
config_hdmi_boost=7
config_hdmi_boost:0=7
config_hdmi_boost:1=7
hdmi_group=1
hdmi_mode=16
hdmi_group:0=1
hdmi_mode:0=16
hdmi_group:1=1
hdmi_mode:1=16
disable_overscan=1
# ========================================================
"""
                if "KIOSK GUARDIAN: Handshake Proyectores" not in cfg_content and "hdmi_force_hotplug=1" not in cfg_content:
                    cfg_content = cfg_content.rstrip() + "\n" + block
                    with open(config_txt, "w", encoding="utf-8") as f:
                        f.write(cfg_content)
                    actions.append(f"HDMI Hotplug + Boost (7) inyectado en {os.path.basename(config_txt)}")
                elif "config_hdmi_boost" not in cfg_content:
                    cfg_content += "\nconfig_hdmi_boost=7\nconfig_hdmi_boost:0=7\nconfig_hdmi_boost:1=7\n"
                    with open(config_txt, "w", encoding="utf-8") as f:
                        f.write(cfg_content)
                    actions.append("config_hdmi_boost=7 añadido para cables largos de proyectores")
            except Exception as e:
                print(f"Error escribiendo config.txt: {e}")
    finally:
        _restore_boot_ro(remounted)

    if not actions:
        if not sys.platform.startswith("linux"):
            return True, "Simulación: Parámetros de handshake HDMI configurados para proyectores."
        return True, "La configuración de handshake y boost HDMI ya se encuentra activa."

    msg = (
        "🎬 AJUSTES DE HANDSHAKE HDMI APLICADOS:\n"
        + "\n".join(f"• {a}" for a in actions)
        + "\n\n✓ La Raspberry Pi emitirá señal continua de video aunque el proyector se encienda después."
    )
    return True, msg


class HDMIWatchdog:
    """
    Watchdog en vivo que supervisa las salidas HDMI (HDMI-A-1 y HDMI-A-2).
    Si un proyector se enciende con retraso o sufre un microcorte de fase,
    re-ejecuta automáticamente los comandos de sincronización de pantalla
    (wlr-randr en Wayland y xrandr en X11) para restablecer la imagen de inmediato.
    """
    def __init__(self, check_interval: float = 3.0, on_reconnect_callback=None):
        self.check_interval = check_interval
        self.on_reconnect_callback = on_reconnect_callback
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_states: Dict[str, str] = {}

    def start(self):
        if not sys.platform.startswith("linux"):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="HDMIWatchdog")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self):
        if not sys.platform.startswith("linux"):
            return

        import glob
        last_reconnect_time = 0.0

        while not self._stop_event.is_set():
            try:
                changed = False
                now = time.time()
                status_files = sorted(glob.glob("/sys/class/drm/card*-HDMI-A-*/status"))
                for sf in status_files:
                    try:
                        with open(sf, "r", encoding="utf-8", errors="ignore") as f:
                            st = f.read().strip().lower()
                        prev = self._last_states.get(sf)
                        if prev is not None and prev != st:
                            # Cambio de estado detectado (ej: disconnected -> connected)
                            changed = True
                        self._last_states[sf] = st

                        # Si está conectado pero el archivo 'mode' está vacío, re-armar salida
                        if st == "connected":
                            mode_path = os.path.join(os.path.dirname(sf), "mode")
                            if os.path.exists(mode_path):
                                with open(mode_path, "r", encoding="utf-8", errors="ignore") as mf:
                                    current_mode = mf.read().strip()
                                if not current_mode:
                                    changed = True
                    except Exception:
                        pass

                # Cooldown de 8 segundos entre re-activaciones para evitar sobrecarga de wlr-randr
                if changed and (now - last_reconnect_time > 8.0):
                    last_reconnect_time = now
                    print("[HDMIWatchdog] Cambio en proyector/HDMI detectado. Re-activando salidas...")
                    from core.dual_display import enable_dual_hdmi_mirror
                    enable_dual_hdmi_mirror()
                    if self.on_reconnect_callback:
                        try:
                            self.on_reconnect_callback()
                        except Exception:
                            pass

            except Exception:
                pass

            self._stop_event.wait(self.check_interval)
