"""
Puente SSH y SFTP para comunicación remota transparente con las Raspberry Pi.
Utiliza OpenSSH nativo con soporte SSH_ASKPASS sin dependencias externas pesadas.
"""

import os
import sys
import subprocess
import tempfile
import shutil
from typing import Dict, Any, List, Tuple, Optional
from core.credentials import CredentialsManager


class SSHBridge:
    def __init__(self, creds_manager: Optional[CredentialsManager] = None):
        self.creds_manager = creds_manager or CredentialsManager()

    def _build_env_with_password(self, password: str) -> Tuple[Dict[str, str], Optional[str]]:
        env = dict(os.environ)
        if not password:
            return env, None

        askpass_script = tempfile.NamedTemporaryFile("w", delete=False, suffix=".sh")
        # Script que devuelve la contraseña por stdout
        safe_pass = password.replace('\\', '\\\\').replace('"', '\\"')
        askpass_script.write(f'#!/bin/sh\nprintf "%s" "{safe_pass}"\n')
        askpass_script.close()
        os.chmod(askpass_script.name, 0o755)

        env["SSH_ASKPASS"] = askpass_script.name
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["DISPLAY"] = ":0"
        return env, askpass_script.name

    def run_command(self, ip: str, command: str, timeout: int = 20) -> Tuple[int, str, str]:
        """Ejecuta un comando remoto por SSH."""
        creds = self.creds_manager.get_ssh_credentials(ip)
        user = creds.get("user", "pi")
        password = creds.get("password", "")
        port = str(creds.get("port", 22))

        env, askpass_path = self._build_env_with_password(password)

        cmd = [
            "ssh",
            "-p", port,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=5",
            "-o", "BatchMode=no" if password else "BatchMode=yes",
            f"{user}@{ip}",
            command
        ]

        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"Tiempo de espera agotado ({timeout}s)"
        except Exception as e:
            return -1, "", str(e)
        finally:
            if askpass_path and os.path.exists(askpass_path):
                try:
                    os.unlink(askpass_path)
                except Exception:
                    pass

    def list_remote_videos(self, ip: str) -> List[Dict[str, Any]]:
        """Busca archivos de video en carpetas típicas de la Raspberry Pi."""
        # Escanear /home/pi/Videos, /home/pi/vlc-autoplay-studio, /media, /mnt
        remote_script = """python3 -c "
import os, json

EXTS = ('.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v')
DIRS = [
    os.path.expanduser('~/Videos'),
    os.path.expanduser('~/vlc-autoplay-studio'),
    os.path.expanduser('~'),
    '/media',
    '/mnt'
]

results = []
seen = set()

for d in DIRS:
    if os.path.exists(d):
        for root, _, files in os.walk(d):
            # No buscar en carpetas ocultas o del sistema profundo
            if '/.' in root or '/__pycache__' in root or '/node_modules' in root:
                continue
            for f in files:
                if f.lower().endswith(EXTS):
                    path = os.path.join(root, f)
                    if path not in seen:
                        seen.add(path)
                        try:
                            st = os.stat(path)
                            size_mb = round(st.st_size / (1024 * 1024), 2)
                            results.append({
                                'name': f,
                                'path': path,
                                'size_mb': size_mb,
                                'mtime': int(st.st_mtime)
                            })
                        except Exception:
                            pass

# Ordenar por fecha reciente
results.sort(key=lambda x: x['mtime'], reverse=True)
print(json.dumps(results[:100]))
" """
        code, stdout, stderr = self.run_command(ip, remote_script, timeout=12)
        if code == 0 and stdout.strip():
            try:
                import json
                return json.loads(stdout.strip())
            except Exception:
                pass
        return []

    def get_system_stats(self, ip: str) -> Dict[str, Any]:
        """Obtiene métricas de hardware: temperatura, espacio libre, RAM, Wi-Fi."""
        remote_script = """python3 -c "
import subprocess, os, json, shutil

stats = {
    'cpu_temp': None,
    'disk_free_gb': None,
    'disk_total_gb': None,
    'disk_percent': None,
    'ram_used_mb': None,
    'ram_total_mb': None,
    'wifi_ssid': None,
    'uptime_hours': None
}

# 1. Temperatura CPU
try:
    if os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            stats['cpu_temp'] = round(int(f.read().strip()) / 1000.0, 1)
    else:
        out = subprocess.check_output(['vcgencmd', 'measure_temp'], timeout=1).decode('utf-8')
        stats['cpu_temp'] = float(out.replace('temp=', '').replace(\"'C\", '').strip())
except Exception:
    pass

# 2. Espacio en disco (SD Card raíz)
try:
    usage = shutil.disk_usage('/')
    stats['disk_total_gb'] = round(usage.total / (1024**3), 1)
    stats['disk_free_gb'] = round(usage.free / (1024**3), 1)
    stats['disk_percent'] = round((usage.used / usage.total) * 100, 1)
except Exception:
    pass

# 3. RAM
try:
    with open('/proc/meminfo', 'r') as f:
        mem = {}
        for line in f:
            parts = line.split(':')
            if len(parts) == 2:
                mem[parts[0].strip()] = int(parts[1].replace('kB', '').strip())
        total = mem.get('MemTotal', 0)
        avail = mem.get('MemAvailable', mem.get('MemFree', 0))
        stats['ram_total_mb'] = round(total / 1024, 0)
        stats['ram_used_mb'] = round((total - avail) / 1024, 0)
except Exception:
    pass

# 4. Wi-Fi SSID
try:
    out = subprocess.check_output(['iwgetid', '-r'], timeout=1).decode('utf-8').strip()
    stats['wifi_ssid'] = out if out else 'Cable / Ethernet'
except Exception:
    stats['wifi_ssid'] = 'Conectado'

# 5. Uptime
try:
    with open('/proc/uptime', 'r') as f:
        stats['uptime_hours'] = round(float(f.read().split()[0]) / 3600.0, 1)
except Exception:
    pass

print(json.dumps(stats))
" """
        code, stdout, stderr = self.run_command(ip, remote_script, timeout=8)
        if code == 0 and stdout.strip():
            try:
                import json
                return json.loads(stdout.strip())
            except Exception:
                pass
        return {}

    def get_logs(self, ip: str, lines: int = 80) -> str:
        """Obtiene las últimas líneas de logs de reproducción y sistema."""
        cmd = f"journalctl -n {lines} --no-pager 2>/dev/null || tail -n {lines} /var/log/syslog 2>/dev/null"
        code, stdout, stderr = self.run_command(ip, cmd, timeout=8)
        return stdout if code == 0 else (stderr or "No se pudieron obtener logs")

    def upload_video_file(self, ip: str, local_filepath: str, remote_dir: str = "/home/pi/Videos") -> Tuple[bool, str]:
        """Sube un archivo de video mediante SCP nativo."""
        creds = self.creds_manager.get_ssh_credentials(ip)
        user = creds.get("user", "pi")
        password = creds.get("password", "")
        port = str(creds.get("port", 22))

        # Asegurar que el directorio remoto exista
        mkdir_cmd = f"mkdir -p '{remote_dir}'"
        self.run_command(ip, mkdir_cmd, timeout=8)

        filename = os.path.basename(local_filepath)
        remote_dest = f"{remote_dir}/{filename}"

        env, askpass_path = self._build_env_with_password(password)

        scp_cmd = [
            "scp",
            "-P", port,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            "-o", "BatchMode=no" if password else "BatchMode=yes",
            local_filepath,
            f"{user}@{ip}:{remote_dest}"
        ]

        try:
            proc = subprocess.run(scp_cmd, env=env, capture_output=True, text=True, timeout=600)
            if proc.returncode == 0:
                return True, remote_dest
            return False, f"Error SCP ({proc.returncode}): {proc.stderr}"
        except subprocess.TimeoutExpired:
            return False, "La transferencia excedió el tiempo límite (10 min)"
        except Exception as e:
            return False, str(e)
        finally:
            if askpass_path and os.path.exists(askpass_path):
                try:
                    os.unlink(askpass_path)
                except Exception:
                    pass

    def switch_active_video(self, ip: str, remote_video_path: str) -> Tuple[bool, str]:
        """Actualiza el perfil activo en profiles.json de la Pi y reinicia el reproductor."""
        remote_script = f"""python3 -c "
import os, json, sys

path = os.path.expanduser('~/vlc-autoplay-studio/profiles.json')
if not os.path.exists(path):
    print('NO_PROFILES_FILE')
    sys.exit(1)

with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

active_id = data.get('active_profile_id')
updated = False
for p in data.get('profiles', []):
    if p.get('id') == active_id or not active_id:
        p['file_path'] = '{remote_video_path}'
        updated = True
        break

if updated:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print('UPDATED')
else:
    print('NOT_UPDATED')
" """
        code, stdout, stderr = self.run_command(ip, remote_script, timeout=8)
        if "UPDATED" in stdout:
            # Reiniciar el reproductor en la Pi
            self.restart_player_service(ip)
            return True, f"Video cambiado a: {os.path.basename(remote_video_path)}"
        return False, f"Error cambiando video: {stderr or stdout}"

    def update_profile_settings(self, ip: str, settings: Dict[str, Any]) -> Tuple[bool, str]:
        """Actualiza configuraciones (volumen, loop, delay, scarlett, hdmi) en la Pi."""
        import json
        settings_json = json.dumps(settings)
        remote_script = f"""python3 -c "
import os, json

settings = json.loads('''{settings_json}''')
path = os.path.expanduser('~/vlc-autoplay-studio/profiles.json')
if os.path.exists(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    active_id = data.get('active_profile_id')
    for p in data.get('profiles', []):
        if p.get('id') == active_id or not active_id:
            for k, v in settings.items():
                p[k] = v
            break
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print('SUCCESS')
else:
    print('NOT_FOUND')
" """
        code, stdout, stderr = self.run_command(ip, remote_script, timeout=8)
        if "SUCCESS" in stdout:
            return True, "Ajustes guardados correctamente en la Pi"
        return False, f"Error guardando ajustes: {stderr or stdout}"

    def restart_player_service(self, ip: str) -> Tuple[bool, str]:
        """Reinicia el servicio o proceso de video en la Pi."""
        cmd = "pkill -f 'sync_runner' || pkill -f 'mpv' || pkill -f 'vlc' || true; systemctl --user restart vlc-autoplay.service 2>/dev/null || true"
        code, stdout, stderr = self.run_command(ip, cmd, timeout=8)
        return True, "Comando de reinicio de reproductor enviado"

    def git_pull_remote(self, ip: str) -> Tuple[bool, str]:
        """Ejecuta git pull en ~/vlc-autoplay-studio."""
        cmd = "cd ~/vlc-autoplay-studio && git pull && sudo systemctl daemon-reload 2>/dev/null || true"
        code, stdout, stderr = self.run_command(ip, cmd, timeout=25)
        if code == 0:
            return True, stdout or "Software actualizado correctamente"
        return False, stderr or stdout

    def reboot_remote(self, ip: str) -> Tuple[bool, str]:
        cmd = "sudo reboot"
        self.run_command(ip, cmd, timeout=5)
        return True, "Orden de reinicio enviada"

    def shutdown_remote(self, ip: str) -> Tuple[bool, str]:
        cmd = "sudo poweroff"
        self.run_command(ip, cmd, timeout=5)
        return True, "Orden de apagado enviada"
