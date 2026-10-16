# 🎬 VLC AutoPlay Studio (Raspberry Pi 5)

> ### ⚡ Instalación Rápida (Pegar en la terminal de la Raspberry Pi):
> ```bash
> curl -sSL https://raw.githubusercontent.com/chuledp/pi5_KIOSK_ANDREANI/main/quick-install.sh | bash
> ```
> *(Descarga el software, instala dependencias si faltan y crea el acceso directo en el Escritorio)*

---

**VLC AutoPlay Studio** es una aplicación gráfica para **Raspberry Pi OS (Debian 12 Bookworm)** diseñada especialmente para artistas visuales, técnicos y montajistas de exposiciones. Permite programar la reproducción automática en bucle continuo de videos o audios al encender la Raspberry Pi de forma 100% visual y sin necesidad de escribir comandos en la terminal.

---

## ✨ Características Principales

- **Zero Terminal**: No hace falta editar archivos de sistema ni usar la consola.
- **Modo Kiosk Profesional**:
  - Bucle infinito continuo (`--loop`).
  - Pantalla completa automática (`--fullscreen`).
  - **Sin título ni textos OSD**: Evita que aparezca el nombre del archivo en la pantalla cada vez que el video se reinicia.
  - Ocultamiento automático del cursor del mouse.
  - Control de volumen y opción para silenciar audio por completo.
- **Retardo de sincronización (Delay de Arranque)**: Configurable de 0 a 30 segundos para esperar a que el monitor/proyector HDMI y el servidor gráfico (Wayland/X11) terminen de negociar la señal antes de lanzar el video.
- **Soporte de Archivos o Carpetas**: Reproduce un archivo individual (`.mp4`, `.mkv`, `.avi`, `.mov`, `.mp3`, `.wav`) o una carpeta entera con múltiples videos en orden.
- **Gestión de Perfiles**: Guardá configuraciones para diferentes obras o salas (ej: *"Sala Principal"*, *"Pasillo Audio"*, *"Muestra Noche"*) y elegí cuál querés que arranque con un clic.
- **Botón de Prueba Inmediata**: Probá el video a pantalla completa en el momento para verificar encuadre y sonido sin reiniciar la Raspberry Pi.

---

## 🚀 Instalación en la Raspberry Pi 5

### Opción 1: Comando rápido de 1 sola línea (Recomendado)
Abrí la terminal de la Raspberry Pi y pegá este comando. Descargará todo, instalará dependencias si faltan y creará el acceso directo en el Escritorio automáticamente:
```bash
curl -sSL https://raw.githubusercontent.com/chuledp/pi5_KIOSK_ANDREANI/main/quick-install.sh | bash
```

---

### Opción 2: Si descargaste el archivo ZIP desde GitHub
Por seguridad, cuando descargás un archivo ZIP de internet en Linux/Raspberry Pi OS, el sistema le quita el permiso de "ejecución" a los archivos para evitar virus. Para instalarlo:
1. Descomprimí el ZIP en tu carpeta personal (`/home/pi/`).
2. Abrí la carpeta descomprimida.
3. Hacé **clic derecho** sobre `Instalar_Acceso_Directo.desktop` -> **Propiedades** -> pestaña **Permisos**.
4. En **Ejecutar**, seleccioná **"Cualquiera"** (o tildar *"Permitir ejecutar el archivo como un programa"*).
5. ¡Listo! Ahora hacé **doble clic en `Instalar_Acceso_Directo.desktop`** y se creará el icono definitivo en tu Escritorio.

---

## 🖥️ Cómo Usar la Aplicación

1. **Abrir el programa**: Hacé doble clic en el icono **VLC AutoPlay Studio** en tu Escritorio o Menú.
2. **Elegir tu video o audio**:
   - Hacé clic en **"Elegir Archivo..."** y seleccioná tu video.
   - O hacé clic en **"Elegir Carpeta..."** si tenés una serie de videos.
3. **Ajustar opciones de sala**:
   - Verificá que estén tildadas las opciones de *Bucle continuo*, *Pantalla completa*, *Ocultar títulos OSD* y *Ocultar cursor*.
   - Si tu monitor tarda unos segundos en dar imagen tras encender, dejá el *Retardo de arranque* en 5 a 8 segundos.
4. **Probar antes de reiniciar**:
   - Hacé clic en el botón azul **"▶ Probar Reproducción Ahora"**.
   - El video se reproducirá a pantalla completa con los ajustes elegidos. Para salir de la prueba podés presionar la tecla `q` en el teclado o el botón *"Detener Prueba"*.
5. **Activar en el Arranque**:
   - Hacé clic en el botón verde **"⚡ Activar este perfil en el Arranque"**.
   - El indicador superior cambiará a verde: `● Arranque ACTIVO con: [Tu Perfil]`.

¡Listo! A partir de ese momento, cada vez que enciendas la Raspberry Pi o se corte la luz y vuelva la energía, la Raspberry Pi iniciará tu video automáticamente a pantalla completa.

---

## ⌨️ Atajos Útiles durante la Reproducción

Si la Raspberry Pi arranca y está reproduciendo el video a pantalla completa en bucle y necesitás salir al escritorio:
- Presioná la tecla **`q`** en el teclado conectado a la Pi: VLC se cerrará inmediatamente y volverás a tu escritorio.
- O presioná **`Alt + F4`** / **`Esc`**.

---

## 🛠️ Requisitos del Sistema

- **Hardware**: Raspberry Pi 5 (o Raspberry Pi 4 / 3 / Zero 2W).
- **Sistema Operativo**: Raspberry Pi OS (Debian Bookworm recomendado, con entorno Wayland o X11).
- **VLC**: Debe estar instalado VLC Media Player. Si por alguna razón tu sistema no lo tiene, se instala con:
  ```bash
  sudo apt update && sudo apt install -y vlc
  ```

---

## 📂 Estructura del Proyecto

```
vlc-autoplay-studio/
├── app.py                         # Interfaz gráfica principal (Tkinter)
├── run.sh                         # Lanzador ejecutable
├── install.sh                     # Instalador de accesos directos
├── Instalar_Acceso_Directo.desktop # Instalador visual para hacer doble clic
├── README.md                      # Esta guía de uso
├── assets/
│   ├── icon.svg                   # Icono vectorial
│   └── icon.png                   # Icono en alta resolución
├── core/
│   ├── __init__.py
│   ├── profile_manager.py         # Guardado de perfiles JSON
│   └── autostart.py               # Generador de scripts de arranque
└── tests/
    └── test_core.py               # Pruebas unitarias
```
