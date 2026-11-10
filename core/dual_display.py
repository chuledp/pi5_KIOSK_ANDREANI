"""
Gestor de Doble Salida HDMI (Dual Optoma / Mirroring) para Raspberry Pi 5.
Habilita ambas salidas micro-HDMI (HDMI-A-1 y HDMI-A-2) y asegura que muestren
exactamente la misma imagen tanto en Wayland (labwc / wayfire vía wlr-randr)
como en X11 (xrandr), además de soportar modo de doble reproductor sincronizado.
"""

import os
import re
import sys
import glob
import shutil
import subprocess
from typing import Dict, Any, Tuple, List, Optional


def _read_sysfs(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return ""


def detect_hdmi_outputs() -> Dict[str, Any]:
    """
    Detecta el estado de las dos salidas HDMI de la Raspberry Pi 5 (HDMI-A-1 y HDMI-A-2),
    incluyendo si están conectadas y qué resolución activa tienen configurada en el DRM/KMS.
    """
    status = {
        "hdmi1_connected": False,
        "hdmi2_connected": False,
        "hdmi1_name": "HDMI-A-1",
        "hdmi2_name": "HDMI-A-2",
        "hdmi1_mode": "",
        "hdmi2_mode": "",
        "hdmi1_modes": [],
        "hdmi2_modes": [],
        "common_resolution": "1920x1080",
        "summary": "HDMI 1+2 (Modo Dual)"
    }

    if not sys.platform.startswith("linux"):
        return status

    try:
        for status_path in sorted(glob.glob("/sys/class/drm/card*-HDMI-A-*/status")):
            base_dir = os.path.dirname(status_path)
            st = _read_sysfs(status_path).lower()
            current_mode = _read_sysfs(os.path.join(base_dir, "mode"))
            modes_raw = _read_sysfs(os.path.join(base_dir, "modes"))
            modes_list = [m.strip() for m in modes_raw.splitlines() if m.strip()]

            if "hdmi-a-1" in status_path.lower():
                status["hdmi1_connected"] = (st == "connected")
                status["hdmi1_mode"] = current_mode
                status["hdmi1_modes"] = modes_list
            elif "hdmi-a-2" in status_path.lower():
                status["hdmi2_connected"] = (st == "connected")
                status["hdmi2_mode"] = current_mode
                status["hdmi2_modes"] = modes_list

        # Buscar mejor resolución común entre ambos proyectores (ej: 1920x1080, 1280x800, 1280x720)
        if status["hdmi1_modes"] and status["hdmi2_modes"]:
            common = [m for m in status["hdmi1_modes"] if m in status["hdmi2_modes"]]
            if common:
                status["common_resolution"] = common[0]

        h1_txt = status["hdmi1_mode"] or ("ON" if status["hdmi1_connected"] else "Wait")
        h2_txt = status["hdmi2_mode"] or ("ON" if status["hdmi2_connected"] else "Wait")

        if status["hdmi1_connected"] and status["hdmi2_connected"]:
            if status["hdmi1_mode"] and status["hdmi2_mode"] and status["hdmi1_mode"] != status["hdmi2_mode"]:
                status["summary"] = f"HDMI-1 [{h1_txt}] | HDMI-2 [{h2_txt}] ⚠️ Diferentes!"
            else:
                status["summary"] = f"HDMI-1 [{h1_txt}] | HDMI-2 [{h2_txt}] ✓ Espejo OK"
        else:
            status["summary"] = f"HDMI-1 [{h1_txt}] | HDMI-2 [{h2_txt}]"
    except Exception:
        pass

    return status


def _update_wayfire_ini_mirror(resolution: str = "auto", mirror: bool = True) -> None:
    """
    Si existe ~/.config/wayfire.ini (Raspberry Pi OS Wayfire), configura HDMI-A-1 y HDMI-A-2
    en posición 0,0 (espejo) o extendido según corresponda.
    """
    wf_path = os.path.expanduser("~/.config/wayfire.ini")
    if not os.path.exists(wf_path):
        return

    try:
        with open(wf_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Eliminar bloques previos de [output:HDMI-A-1] y [output:HDMI-A-2] para escribirlos limpios
        content = re.sub(r"\n?\[output:HDMI-A-1\][^\[]*", "", content, flags=re.DOTALL)
        content = re.sub(r"\n?\[output:HDMI-A-2\][^\[]*", "", content, flags=re.DOTALL)
        content = content.rstrip() + "\n\n"

        mode_line = f"mode = {resolution}@60000\n" if resolution != "auto" else ""
        if mirror:
            block = (
                f"[output:HDMI-A-1]\n"
                f"{mode_line}"
                f"position = 0,0\n\n"
                f"[output:HDMI-A-2]\n"
                f"{mode_line}"
                f"position = 0,0\n"
            )
        else:
            width = int(resolution.split("x")[0]) if "x" in resolution else 1920
            block = (
                f"[output:HDMI-A-1]\n"
                f"{mode_line}"
                f"position = 0,0\n\n"
                f"[output:HDMI-A-2]\n"
                f"{mode_line}"
                f"position = {width},0\n"
            )

        with open(wf_path, "w", encoding="utf-8") as f:
            f.write(content + block)
    except Exception as e:
        print(f"Nota actualizando wayfire.ini: {e}")


def enable_dual_hdmi_mirror(profile: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """
    Activa ambas salidas HDMI (HDMI-A-1 y HDMI-A-2) y las configura para mostrar
    la misma información en ambos proyectores Optoma:
    - En modo `mirror` (por defecto): Superpone ambas salidas en la coordenada `0,0`
      usando `wlr-randr` (Wayland labwc/wayfire) y `xrandr --same-as` (X11).
    - En modo `dual_mpv`: Posiciona HDMI-A-1 en `0,0` y HDMI-A-2 al lado (`1920,0`)
      para que MPV abra dos ventanas sincronizadas en pantalla completa (una en cada proyector).
    """
    prof = profile or {}
    if not prof.get("dual_hdmi_enabled", True):
        return True, "Modo Dual HDMI desactivado en este perfil."

    dual_mode = prof.get("dual_hdmi_mode", "mirror")
    resolution = prof.get("dual_hdmi_resolution", "auto")
    is_mirror = (dual_mode == "mirror")

    st = detect_hdmi_outputs()
    target_res = resolution
    if target_res == "auto":
        # Usar la mejor resolución común detectada entre ambos Optoma para que coincidan 100%
        target_res = st.get("common_resolution", "1920x1080")

    if not sys.platform.startswith("linux"):
        return True, f"Modo Dual Optoma ({dual_mode.upper()}, res: {target_res}) listo (se aplicará en la Raspberry Pi)."

    applied_methods: List[str] = []
    width = int(target_res.split("x")[0]) if "x" in target_res else 1920
    pos_hdmi2_wlr = "0,0" if is_mirror else f"{width},0"
    pos_hdmi2_x11 = "0x0" if is_mirror else f"{width}x0"

    # 1. Wayland (labwc / wayfire) vía wlr-randr
    if shutil.which("wlr-randr"):
        for out1, out2 in (("HDMI-A-1", "HDMI-A-2"), ("HDMI-1", "HDMI-2")):
            for out_name, pos_val in ((out1, "0,0"), (out2, pos_hdmi2_wlr)):
                cmd_single = ["wlr-randr", "--output", out_name, "--on", "--pos", pos_val]
                if target_res:
                    cmd_single.extend(["--mode", target_res])
                try:
                    r = subprocess.run(
                        cmd_single,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=2.5
                    )
                    if r.returncode == 0:
                        applied_methods.append(f"wlr-randr ({out_name}@{target_res})")
                    else:
                        # Fallback sin --mode sólo si el proyector rechazó la resolución solicitada
                        subprocess.run(
                            ["wlr-randr", "--output", out_name, "--on", "--pos", pos_val],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=2.0
                        )
                except Exception:
                    pass

    # 2. Actualizar wayfire.ini si existe
    _update_wayfire_ini_mirror(resolution=target_res, mirror=is_mirror)

    # 3. X11 vía xrandr
    if shutil.which("xrandr"):
        for out1, out2 in (("HDMI-1", "HDMI-2"), ("HDMI-A-1", "HDMI-A-2")):
            cmd_x = ["xrandr", "--output", out1, "--mode", target_res, "--pos", "0x0", "--output", out2, "--mode", target_res, "--pos", pos_hdmi2_x11]
            if is_mirror:
                cmd_x.extend(["--same-as", out1])
            try:
                r = subprocess.run(
                    cmd_x,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=2.5
                )
                if r.returncode == 0:
                    applied_methods.append(f"xrandr ({out1}+{out2}@{target_res})")
                    break
                else:
                    # Fallback auto
                    subprocess.run(
                        ["xrandr", "--output", out1, "--auto", "--pos", "0x0", "--output", out2, "--auto", "--pos", pos_hdmi2_x11],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2.0
                    )
            except Exception:
                pass

    st = detect_hdmi_outputs()
    if applied_methods:
        return True, f"Dual HDMI activo ({target_res}) [{', '.join(applied_methods)}] • {st['summary']}"
    return True, f"Configuración Dual HDMI preparada ({target_res}) ({st['summary']})."


def build_dual_hdmi_shell_snippet(profile: Dict[str, Any]) -> str:
    """
    Genera los comandos bash para `vlc-runner.sh` de modo que al arrancar la Raspberry Pi 5
    se enciendan las dos salidas HDMI en espejo (0,0) antes de lanzar el reproductor.
    """
    if not profile.get("dual_hdmi_enabled", True):
        return "# Modo Dual HDMI desactivado en este perfil"

    dual_mode = profile.get("dual_hdmi_mode", "mirror")
    resolution = profile.get("dual_hdmi_resolution", "auto")
    is_mirror = (dual_mode == "mirror")
    res_target = resolution if resolution != "auto" else "1920x1080"
    width = int(res_target.split("x")[0]) if "x" in res_target else 1920
    pos_wlr = "0,0" if is_mirror else f"{width},0"
    pos_x11 = "0x0" if is_mirror else f"{width}x0"
    same_as_flag = "--same-as HDMI-1" if is_mirror else ""
    same_as_flag_a = "--same-as HDMI-A-1" if is_mirror else ""
    mode_wlr = f"--mode {res_target}"

    return f"""# Habilitar las 2 salidas HDMI forzando idéntica resolución (Dual Optoma: HDMI-A-1 y HDMI-A-2)
if command -v wlr-randr >/dev/null 2>&1; then
    wlr-randr --output HDMI-A-1 --on --pos 0,0 {mode_wlr} 2>/dev/null || wlr-randr --output HDMI-A-1 --on --pos 0,0 2>/dev/null || true
    wlr-randr --output HDMI-A-2 --on --pos {pos_wlr} {mode_wlr} 2>/dev/null || wlr-randr --output HDMI-A-2 --on --pos {pos_wlr} 2>/dev/null || true
fi
if command -v xrandr >/dev/null 2>&1; then
    xrandr --output HDMI-1 --mode {res_target} --pos 0x0 --output HDMI-2 --mode {res_target} --pos {pos_x11} {same_as_flag} 2>/dev/null || xrandr --output HDMI-1 --auto --pos 0x0 --output HDMI-2 --auto --pos {pos_x11} {same_as_flag} 2>/dev/null || true
    xrandr --output HDMI-A-1 --mode {res_target} --pos 0x0 --output HDMI-A-2 --mode {res_target} --pos {pos_x11} {same_as_flag_a} 2>/dev/null || xrandr --output HDMI-A-1 --auto --pos 0x0 --output HDMI-A-2 --auto --pos {pos_x11} {same_as_flag_a} 2>/dev/null || true
fi"""

