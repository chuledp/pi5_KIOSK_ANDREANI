"""
Controlador y Ruteador para Focusrite Scarlett 8i6 (1st Gen / 3rd Gen) en Raspberry Pi 5.
Gestiona:
1. Detección automática de la placa USB Scarlett en ALSA (/proc/asound/cards).
2. Configuración del Mixer Interno por Hardware de la Scarlett 8i6 vía `amixer`:
   - Asigna `Mixer Input 01/02` = `PCM 1/2` (Estéreo L/R) y `Mixer Input 03/04` = `PCM 1/2` (Bus paralelo de Boost en el DSP de la placa).
   - Rutea las 6 salidas físicas a los 6 Mixes internos de hardware (`Mix A` a `Mix F`):
     * `Analogue Output 01` (Line 1 L) <- `Mix A`
     * `Analogue Output 02` (Line 2 R) <- `Mix B`
     * `Analogue Output 03` (Line 3 L) <- `Mix C`
     * `Analogue Output 04` (Line 4 R) <- `Mix D`
     * `S/PDIF Output 01` (Subwoofer Samson 10" L) <- `Mix E` (Suma Mono L+R)
     * `S/PDIF Output 02` (Subwoofer Samson 10" R) <- `Mix F` (Suma Mono L+R)
   - Permite controlar independientemente en tiempo real el nivel de [Analógicas 1-2], [Analógicas 3-4] y [Subwoofer S/PDIF 5-6],
     duplicando canales en los Mixes cuando el slider supera el 100% para ganar hasta +12 dB extra directo en el DSP de la Scarlett.
3. Generación del filtro DSP (`dynaudnorm` + `alimiter`) para MPV.
4. Lanzador de `alsa-scarlett-gui`.
"""

import os
import re
import sys
import shutil
import subprocess
from typing import Dict, Any, Optional, List, Tuple


def detect_scarlett_card() -> Dict[str, Any]:
    """
    Busca una interfaz Focusrite Scarlett (o interfaz de audio USB) en /proc/asound/cards.
    Retorna información de la tarjeta para ALSA y MPV.
    """
    result = {
        "found": False,
        "card_index": -1,
        "card_id": "USB",
        "description": "No detectada",
        "mpv_device": "alsa/plughw:CARD=USB,DEV=0",
        "alsa_device": "plughw:CARD=USB,DEV=0",
    }

    cards_path = "/proc/asound/cards"
    if not os.path.exists(cards_path):
        return result

    try:
        with open(cards_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        candidates: List[Tuple[int, str, str, int]] = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            m = re.match(r"^(\d+)\s+\[([^\]]+)\]\s*:\s*(.+)$", line)
            if m:
                idx = int(m.group(1))
                card_id = m.group(2).strip()
                desc = m.group(3).strip()
                if i + 1 < len(lines) and not re.match(r"^\d+\s+\[", lines[i + 1].strip()):
                    desc += " - " + lines[i + 1].strip()
                    i += 1

                low = (card_id + " " + desc).lower()
                if "scarlett" in low or "focusrite" in low:
                    candidates.append((idx, card_id, desc, 2))
                elif "usb" in low:
                    candidates.append((idx, card_id, desc, 1))
            i += 1

        if candidates:
            candidates.sort(key=lambda x: x[3], reverse=True)
            idx, card_id, desc, _ = candidates[0]
            result.update({
                "found": True,
                "card_index": idx,
                "card_id": card_id,
                "description": desc,
                "mpv_device": f"alsa/plughw:CARD={card_id},DEV=0",
                "alsa_device": f"plughw:CARD={card_id},DEV=0",
            })
    except Exception as e:
        print(f"Error detectando Scarlett en /proc/asound/cards: {e}")

    return result


def _run_amixer(card_idx: int, args: List[str]) -> Optional[str]:
    if not shutil.which("amixer"):
        return None
    cmd = ["amixer", "-c", str(card_idx)] + args
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2.0
        )
        if res.returncode == 0:
            return res.stdout
    except Exception:
        pass
    return None


def _get_scontrols(card_idx: int) -> List[str]:
    """Obtiene la lista de controles simples (`scontrols`) disponibles en la tarjeta ALSA."""
    out = _run_amixer(card_idx, ["scontrols"])
    if not out:
        return []
    controls = []
    for line in out.splitlines():
        m = re.search(r"'([^']+)'", line)
        if m:
            controls.append(m.group(1))
    return controls


def _get_cset_controls(card_idx: int) -> List[str]:
    """Obtiene la lista completa de controles (`amixer controls`) para soportar `cset` en scarlett2."""
    out = _run_amixer(card_idx, ["controls"])
    if not out:
        return []
    controls = []
    for line in out.splitlines():
        m = re.search(r"name='([^']+)'", line)
        if m:
            controls.append(m.group(1))
    return controls


def _split_gain_to_dual_bus(gain_pct: int) -> Tuple[int, int]:
    """
    Convierte un porcentaje de slider (0% a 200%) en dos buses paralelos del mixer interno
    de la Scarlett (Input Primario 0..100% + Input Boost Paralelo 0..100%).
    - 0%..100%: Bus 1 = gain_pct%, Bus 2 = 0%
    - 101%..200%: Bus 1 = 100% (+6dB en DSP Scarlett), Bus 2 = (gain_pct - 100)% (hasta +12dB sumados)
    """
    g = max(0, min(200, int(gain_pct)))
    if g <= 100:
        return g, 0
    return 100, g - 100


def apply_scarlett_mix_levels(profile: Dict[str, Any]) -> bool:
    """
    Actualiza en tiempo real los faders de Mix A..F dentro del DSP de la Scarlett 8i6
    según los 3 sliders del perfil:
      - Analógicas 1-2 (`scarlett_gain_12`: 0% a 200%) -> Mix A (L) y Mix B (R)
      - Analógicas 3-4 (`scarlett_gain_34`: 0% a 200%) -> Mix C (L) y Mix D (R)
      - Subwoofer S/PDIF 5-6 (`scarlett_gain_sub`: 0% a 200%) -> Mix E (L+R) y Mix F (L+R)
    """
    if not sys.platform.startswith("linux"):
        return False

    info = detect_scarlett_card()
    if not info["found"]:
        return False

    card_idx = info["card_index"]
    scontrols = _get_scontrols(card_idx)
    ccontrols = _get_cset_controls(card_idx)
    all_names = set(scontrols) | set(ccontrols)

    def set_ctrl(name: str, value: str) -> bool:
        if name in scontrols:
            return _run_amixer(card_idx, ["sset", name, value]) is not None
        if name in ccontrols:
            return _run_amixer(card_idx, ["cset", f"name='{name}'", value]) is not None
        return False

    def set_mix_input(mix_letter: str, input_num: int, pct: int):
        val = f"{max(0, min(100, int(pct)))}%"
        for cname in (
            f"Mix {mix_letter} Input 0{input_num}",
            f"Mix {mix_letter} Input 0{input_num} Playback Volume",
            f"Matrix 0{input_num} Mix {mix_letter}",
        ):
            if cname in all_names:
                set_ctrl(cname, val)

    g12_main, g12_boost = _split_gain_to_dual_bus(profile.get("scarlett_gain_12", 120))
    g34_main, g34_boost = _split_gain_to_dual_bus(profile.get("scarlett_gain_34", 120))
    gsub_main, gsub_boost = _split_gain_to_dual_bus(profile.get("scarlett_gain_sub", 130))

    # Mix A (Analógica 1 - L): Input 01 (PCM 1 L) + Input 03 (PCM 1 Boost L)
    set_mix_input("A", 1, g12_main)
    set_mix_input("A", 2, 0)
    set_mix_input("A", 3, g12_boost)
    set_mix_input("A", 4, 0)

    # Mix B (Analógica 2 - R): Input 02 (PCM 2 R) + Input 04 (PCM 2 Boost R)
    set_mix_input("B", 1, 0)
    set_mix_input("B", 2, g12_main)
    set_mix_input("B", 3, 0)
    set_mix_input("B", 4, g12_boost)

    # Mix C (Analógica 3 - L): Input 01 (PCM 1 L) + Input 03 (PCM 1 Boost L)
    set_mix_input("C", 1, g34_main)
    set_mix_input("C", 2, 0)
    set_mix_input("C", 3, g34_boost)
    set_mix_input("C", 4, 0)

    # Mix D (Analógica 4 - R): Input 02 (PCM 2 R) + Input 04 (PCM 2 Boost R)
    set_mix_input("D", 1, 0)
    set_mix_input("D", 2, g34_main)
    set_mix_input("D", 3, 0)
    set_mix_input("D", 4, g34_boost)

    # Mix E y Mix F (S/PDIF 5-6 -> Subwoofer Samson 10"): Suma Mono (PCM 1 L + PCM 2 R)
    for sub_mix in ("E", "F"):
        set_mix_input(sub_mix, 1, gsub_main)
        set_mix_input(sub_mix, 2, gsub_main)
        set_mix_input(sub_mix, 3, gsub_boost)
        set_mix_input(sub_mix, 4, gsub_boost)

    return True


def configure_scarlett_8i6_hardware(
    profile: Optional[Dict[str, Any]] = None,
    use_mix_boost: bool = True
) -> Tuple[bool, str]:
    """
    Configura automáticamente el mixer interno por hardware de la Focusrite Scarlett 8i6
    (compatible con 3rd Gen `scarlett2` y 1st Gen `scarlett`):
    1. Reloj interno activado para que la salida S/PDIF funcione siempre.
    2. Faders maestros y de línea 1-4 / S/PDIF desmuteados y al 100% (0 dB).
    3. Entradas del Mixer Interno:
       - Input 01 = PCM 1 (L), Input 02 = PCM 2 (R)
       - Input 03 = PCM 1 (L Boost paralelo), Input 04 = PCM 2 (R Boost paralelo)
    4. Salidas ruteadas a los Mixes:
       - Analogue Output 01/02 -> Mix A / Mix B (Par Analógico 1-2)
       - Analogue Output 03/04 -> Mix C / Mix D (Par Analógico 3-4)
       - S/PDIF Output 01/02 -> Mix E / Mix F (Suma Mono L+R para Subwoofer Samson 10")
    """
    write_asoundrc_if_scarlett()

    info = detect_scarlett_card()
    if not info["found"]:
        return False, "No se detectó la placa Focusrite Scarlett USB conectada."

    card_idx = info["card_index"]
    scontrols = _get_scontrols(card_idx)
    ccontrols = _get_cset_controls(card_idx)
    all_names = set(scontrols) | set(ccontrols)
    if not all_names:
        return False, f"Se detectó {info['description']} (Card {card_idx}), pero no expone controles amixer."

    def set_ctrl(name: str, value: str) -> bool:
        if name in scontrols:
            if _run_amixer(card_idx, ["sset", name, value]) is not None:
                return True
        if name in ccontrols:
            if _run_amixer(card_idx, ["cset", f"name='{name}'", value]) is not None:
                return True
        return False

    # 1. Asegurar reloj interno para que S/PDIF siempre emita señal digital hacia el conversor/Subwoofer
    for clk_ctrl in ("Sample Clock Source", "Clock Source", "Sample Clock Source Enum"):
        set_ctrl(clk_ctrl, "Internal")

    # 2. Subir al 100% y desmutear todos los faders maestros y de salidas físicas
    for ctrl in scontrols:
        low = ctrl.lower()
        if any(k in low for k in ("master", "line 0", "line 1", "line 2", "line 3", "line 4", "analogue", "s/pdif", "spdif")):
            if "enum" not in low and "source" not in low and "input" not in low:
                _run_amixer(card_idx, ["sset", ctrl, "100%", "unmute"])
                _run_amixer(card_idx, ["sset", ctrl, "100%"])
                _run_amixer(card_idx, ["sset", ctrl, "unmute"])

    # 3. Configurar entradas de la matriz (Input 01/02 = PCM 1/2, Input 03/04 = PCM 1/2 para Boost paralelo)
    input_pcm_map = {
        1: ("PCM 1", "PCM 01"),
        2: ("PCM 2", "PCM 02"),
        3: ("PCM 1", "PCM 01"),
        4: ("PCM 2", "PCM 02"),
        5: ("PCM 5", "PCM 05", "PCM 1"),
        6: ("PCM 6", "PCM 06", "PCM 2"),
    }
    for ch, pcm_candidates in input_pcm_map.items():
        for prefix in (
            f"Mixer Input 0{ch}",
            f"Mixer Input 0{ch} Capture Enum",
            f"Matrix 0{ch} Input",
            f"Matrix 0{ch} Input Playback Enum",
            f"Input Source 0{ch}",
        ):
            if prefix in all_names:
                for pcm_val in pcm_candidates:
                    if set_ctrl(prefix, pcm_val):
                        break

    # 4. Limpiar entradas 05..08 de Mix A..F para que no metan ruido de entradas físicas de micrófono
    has_mix_routing = any("Mix A" in c for c in all_names)
    if has_mix_routing:
        for letter in ("A", "B", "C", "D", "E", "F"):
            for inp in range(5, 10):
                for cname in (f"Mix {letter} Input 0{inp}", f"Mix {letter} Input 0{inp} Playback Volume"):
                    if cname in all_names:
                        set_ctrl(cname, "0%")

        # Aplicar los niveles de los 3 sliders (1-2, 3-4 y Sub S/PDIF 5-6) en Mix A..F
        apply_scarlett_mix_levels(profile or {})

    # 5. Rutear las 4 Salidas Analógicas (1-4) y las 2 Salidas S/PDIF (5-6) a Mix A..F
    output_mappings = [
        (
            ["Analogue Output 01", "Analogue Output 01 Playback Enum", "Output 1 Source", "Master 1L (Monitor) Source"],
            ["Mix A"],
            ["PCM 1", "PCM 01"]
        ),
        (
            ["Analogue Output 02", "Analogue Output 02 Playback Enum", "Output 2 Source", "Master 1R (Monitor) Source"],
            ["Mix B"],
            ["PCM 2", "PCM 02"]
        ),
        (
            ["Analogue Output 03", "Analogue Output 03 Playback Enum", "Output 3 Source", "Master 2L (Line) Source"],
            ["Mix C", "Mix A"],
            ["PCM 3", "PCM 03", "PCM 1"]
        ),
        (
            ["Analogue Output 04", "Analogue Output 04 Playback Enum", "Output 4 Source", "Master 2R (Line) Source"],
            ["Mix D", "Mix B"],
            ["PCM 4", "PCM 04", "PCM 2"]
        ),
        (
            ["S/PDIF Output 01", "S/PDIF Output 01 Playback Enum", "S/PDIF 1 Source", "Master 3L (S/PDIF) Source"],
            ["Mix E", "Mix C", "Mix A"],
            ["PCM 5", "PCM 05", "PCM 1"]
        ),
        (
            ["S/PDIF Output 02", "S/PDIF Output 02 Playback Enum", "S/PDIF 2 Source", "Master 3R (S/PDIF) Source"],
            ["Mix F", "Mix D", "Mix B"],
            ["PCM 6", "PCM 06", "PCM 2"]
        ),
    ]

    for ctrl_candidates, mix_sources, pcm_sources in output_mappings:
        for ctrl_name in ctrl_candidates:
            if ctrl_name in all_names:
                done = False
                if use_mix_boost and has_mix_routing:
                    for m_src in mix_sources:
                        if set_ctrl(ctrl_name, m_src):
                            done = True
                            break
                if not done:
                    for p_src in pcm_sources:
                        if set_ctrl(ctrl_name, p_src):
                            break

    # 6. Guardar estado en alsactl para que persista tras reiniciar la Pi
    if shutil.which("alsactl"):
        try:
            subprocess.run(
                ["alsactl", "store", str(card_idx)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0
            )
        except Exception:
            pass

    # 7. Asignar Scarlett como salida por defecto en PipeWire y PulseAudio
    set_default_scarlett_sink()

    return True, f"Scarlett 8i6 ruteada ({info['card_id']}): Salidas 1-2 (Mix A/B), 3-4 (Mix C/D) y Sub S/PDIF 5-6 (Mix E/F)."


def build_mpv_audio_filter(profile: Dict[str, Any]) -> str:
    """
    Construye la cadena de filtros `--af` de MPV:
    - Cuando `scarlett_enabled` está activo, genera una matriz de 6 canales (`pan=5.1`)
      para que tanto `PCM 1-2` (Analógicas 1-2), `PCM 3-4` (Analógicas 3-4) como
      `PCM 5-6` (Subwoofer S/PDIF 5-6 en suma Mono L+R) salgan con su ganancia independiente,
      combinado con el ruteo por hardware de `Mix A..F` en la Scarlett 8i6.
    """
    scarlett_enabled = bool(profile.get("scarlett_enabled", True))
    audio_boost = bool(profile.get("audio_boost", True))

    if not scarlett_enabled:
        if audio_boost:
            return "lavfi=[dynaudnorm=f=200:g=15:p=0.95,alimiter=limit=0.98:attack=5:release=50:level=disabled]"
        return ""

    g12 = max(0.0, min(4.0, float(profile.get("scarlett_gain_12", 120)) / 100.0))
    g34 = max(0.0, min(4.0, float(profile.get("scarlett_gain_34", 120)) / 100.0))
    gsub = max(0.0, min(4.0, float(profile.get("scarlett_gain_sub", 130)) / 100.0))
    gsub_half = gsub * 0.5

    pan_expr = (
        f"pan=5.1|"
        f"c0={g12:.2f}*c0|c1={g12:.2f}*c1|"
        f"c2={g34:.2f}*c0|c3={g34:.2f}*c1|"
        f"c4={gsub_half:.2f}*c0+{gsub_half:.2f}*c1|"
        f"c5={gsub_half:.2f}*c0+{gsub_half:.2f}*c1"
    )

    if audio_boost:
        return f"lavfi=[dynaudnorm=f=200:g=15:p=0.95,{pan_expr},alimiter=limit=0.98:attack=5:release=50:level=disabled]"
    return f"lavfi=[{pan_expr}]"


def generate_asoundrc_6ch(card_id: str = "USB") -> str:
    """
    Genera una configuración ~/.asoundrc con el dispositivo `scarlett6ch` opcional.
    """
    return f"""# Generado automáticamente por AutoPlay Studio (Rama Pi+Scarlett)
pcm.scarlett_hw {{
    type hw
    card "{card_id}"
    device 0
}}

pcm.scarlett6ch {{
    type route
    slave.pcm "scarlett_hw"
    slave.channels 6
    ttable.0.0 1.0
    ttable.1.1 1.0
    ttable.0.2 1.0
    ttable.1.3 1.0
    ttable.0.4 0.5
    ttable.1.4 0.5
    ttable.0.5 0.5
    ttable.1.5 0.5
}}

ctl.scarlett6ch {{
    type hw
    card "{card_id}"
}}
"""


def set_default_scarlett_sink() -> bool:
    """
    Configura la Focusrite Scarlett USB como salida de audio por defecto
    en PipeWire (wpctl) y PulseAudio (pactl).
    """
    if not sys.platform.startswith("linux"):
        return False

    success = False

    # 1. PulseAudio / PipeWire-Pulse vía pactl
    if shutil.which("pactl"):
        try:
            r = subprocess.run(
                ["pactl", "list", "short", "sinks"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2.0
            )
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    sink_name = parts[1]
                    low = sink_name.lower()
                    if "scarlett" in low or "focusrite" in low or "usb" in low:
                        subprocess.run(["pactl", "set-default-sink", sink_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0)
                        subprocess.run(["pactl", "set-sink-mute", sink_name, "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0)
                        subprocess.run(["pactl", "set-sink-volume", sink_name, "100%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0)
                        success = True
                        break
        except Exception:
            pass

    # 2. WirePlumber / PipeWire nativo vía wpctl
    if shutil.which("wpctl"):
        try:
            r = subprocess.run(
                ["wpctl", "status"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2.0
            )
            in_sinks = False
            for line in r.stdout.splitlines():
                if "Sinks:" in line:
                    in_sinks = True
                    continue
                if in_sinks and any(header in line for header in ("Sink endpoints:", "Sources:", "Streams:", "Filters:")):
                    break
                if in_sinks:
                    low = line.lower()
                    if "scarlett" in low or "focusrite" in low:
                        m = re.search(r"(\d+)\.", line)
                        if m:
                            node_id = m.group(1)
                            subprocess.run(["wpctl", "set-default", node_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0)
                            subprocess.run(["wpctl", "set-mute", node_id, "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0)
                            subprocess.run(["wpctl", "set-volume", node_id, "1.0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0)
                            success = True
                            break
        except Exception:
            pass

    return success


def write_asoundrc_if_scarlett() -> Optional[str]:
    """Escribe ~/.asoundrc con el dispositivo `scarlett6ch` si estamos en Linux y hay una Scarlett."""
    if not sys.platform.startswith("linux"):
        return None
    info = detect_scarlett_card()
    if not info["found"]:
        return None
    card_id = info["card_id"]
    asound_path = os.path.expanduser("~/.asoundrc")
    try:
        with open(asound_path, "w", encoding="utf-8") as f:
            f.write(generate_asoundrc_6ch(card_id))
        return asound_path
    except Exception as e:
        print(f"No se pudo escribir ~/.asoundrc: {e}")
        return None


def launch_scarlett_gui() -> Tuple[bool, str]:
    """
    Intenta abrir `alsa-scarlett-gui`. Si no está instalado, abre `alsamixer` en una terminal
    apuntando a la placa Scarlett o informa cómo instalarlo.
    """
    if shutil.which("alsa-scarlett-gui"):
        try:
            subprocess.Popen(
                ["alsa-scarlett-gui"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True, "Abriendo panel Focusrite (alsa-scarlett-gui)..."
        except Exception as e:
            return False, f"Error al abrir alsa-scarlett-gui: {e}"

    if shutil.which("qasmixer"):
        subprocess.Popen(["qasmixer"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, "Abriendo QasMixer..."

    info = detect_scarlett_card()
    card_arg = str(info["card_index"]) if info["found"] else "1"
    for term in ("lxterminal", "xfce4-terminal", "x-terminal-emulator", "foot", "gnome-terminal"):
        if shutil.which(term):
            try:
                subprocess.Popen([term, "-e", f"alsamixer -c {card_arg}"])
                return True, f"alsa-scarlett-gui no encontrado; abriendo alsamixer (Card {card_arg})."
            except Exception:
                pass

    return (
        False,
        "No se encontró 'alsa-scarlett-gui'.\n\n"
        "Podés instalarlo corriendo el instalador quick-install.sh de la rama Pi+Scarlett."
    )
