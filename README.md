# 🎬 AutoPlay Studio • Sync & OSC (Raspberry Pi 5)

> ### ⚡ Instalación Rápida (Pegar en la terminal de la Raspberry Pi):
> ```bash
> curl -sSL https://raw.githubusercontent.com/chuledp/pi5_KIOSK_ANDREANI/sync-osc/quick-install.sh | bash
> ```
> *(Instala dependencias: MPV, VLC, Python Tkinter, y crea el acceso directo en el Escritorio)*

---

**AutoPlay Studio (Sync & OSC)** es una aplicación visual para **Raspberry Pi OS (Debian 12 Bookworm)** diseñada para montajes de arte, exposiciones interactivas y espectáculos multimedia. 

Permite reproducir videos y audios automáticamente al encender la Pi, **sincronizar múltiples Raspberry Pis entre sí por red local** y recibir disparos/cues en tiempo real vía **OSC (Open Sound Control)** desde **TouchDesigner**, **Resolume Arena**, **Reaper**, etc.

---

## 🌐 Funcionalidades de Red & Sincronización

### 1. Tres Roles en Red Configurables
- 📻 **Receptor OSC (Follower)**: La Raspberry Pi escucha en un puerto UDP (por defecto `9000`). Responde instantáneamente a órdenes de reproducción, salto de tiempo, cambio de obra y sincronización de reloj.
- 📡 **Emisor (Master Pi)**: Una Raspberry Pi lidera la sala. Reproduce su video y transmite periódicamente pulsos de reloj (`/sync/clock`) y órdenes por UDP Broadcast a todas las demás Pis de la red.
- 🔌 **Autónomo (Kiosk Local)**: Reproducción independiente en bucle sin conexión a red.

### 2. Motor MPV de Alta Precisión
- Control por **socket IPC Unix**: Búsqueda (*seek*) instantánea frame-accurate sin la latencia de VLC.
- **Algoritmo de Drift Correction (Sincronización suave de reloj)**:
  - Si la Pi se desfasa menos de 300 ms del Master o de la consola, ajusta sutilmente la velocidad de reproducción (`1.025x` o `0.975x`) para volver a sincronizar **sin cortes de audio ni saltos visuales**.
  - Si el desfasaje es mayor, ejecuta un salto directo (*hard seek*).

### 3. Monitor OSC en Tiempo Real
En la parte inferior de la ventana, una barra de estado muestra en vivo cada paquete OSC que llega desde la red (ideal para verificar que TouchDesigner o Resolume están enviando datos antes de montar la sala).

---

## 🎛️ Tabla de Comandos OSC

Por defecto, el sistema responde a las siguientes direcciones OSC:

| Dirección OSC | Argumento | Acción |
| :--- | :--- | :--- |
| `/play` | *(ninguno o 1)* | Inicia o reanuda la reproducción |
| `/pause` | *(ninguno o 1)* | Pausa el video/audio |
| `/stop` | *(ninguno)* | Detiene y vuelve al inicio (segundo 0) |
| `/seek` | `float` (segundos) | Salta al segundo indicado (ej: `/seek 15.5`) |
| `/position` | `float` (`0.0` a `1.0`) | Salto normalizado (estilo fader de Resolume / TouchDesigner) |
| `/cue` | `string` o `int` | Carga y reproduce el perfil que coincida en nombre o ID |
| `/volume` | `int` (`0` a `100`) | Ajusta el volumen de salida dinámicamente |
| `/sync/clock` | `float` (tiempo master) | Sincronización continua de reloj entre Pis |

> [!TIP]
> **Mapeo Personalizado**: Desde el botón **"⚙ Mapear Rutas OSC..."** podés cambiar cualquiera de estas direcciones para que coincida exactamente con las rutas nativas de tu software (por ejemplo `/composition/layers/1/clips/1/connect`).

---

## 💻 Ejemplos de Integración

### Con TouchDesigner
1. Agregá un operador **OSC Out CHOP** o **OSC Out DAT**.
2. Configurá `Network Address` con la IP de la Raspberry Pi (o `255.255.255.255` para broadcast a todas las Pis).
3. Configurá `Network Port` en `9000`.
4. Enviá canales como `/play`, `/pause` o `/seek`.

### Con Resolume Arena
1. En **Preferences > OSC**, activá **OSC Output**.
2. Indicá la IP de la Pi y el puerto `9000`.
3. Mapeá un clip o acción para enviar `/cue 1` o `/play`.

### Con Reaper
1. En **Preferences > Control/OSC/web**, agregá un dispositivo **OSC**.
2. Modo: *Send to device* hacia el puerto `9000`.
3. Podés enviar marcas de tiempo de la línea de tiempo o triggers de regiones.

---

## ⌨️ Atajos Útiles en Pantalla Completa

- **`q`** en el teclado: Cierra inmediatamente el reproductor y vuelve al escritorio de la Pi.
- **`Esc`** o **`Alt + F4`**: Salir de pantalla completa.

---

## 📂 Estructura del Proyecto

```
vlc-autoplay-studio/
├── app.py                         # Interfaz gráfica (Kiosk + OSC + Monitor)
├── run.sh                         # Lanzador ejecutable
├── install.sh                     # Instalador de accesos directos
├── quick-install.sh               # One-liner installer vía curl
├── Instalar_Acceso_Directo.desktop # Instalador visual para hacer doble clic
├── README.md                      # Documentación completa
├── assets/
│   ├── icon.svg                   # Icono vectorial
│   └── icon.png                   # Icono en alta resolución
├── core/
│   ├── __init__.py
│   ├── profile_manager.py         # Configuración y perfiles JSON
│   ├── autostart.py               # Generador de autostart
│   ├── osc_receiver.py            # Servidor OSC ligero en Python puro
│   ├── osc_broadcaster.py         # Emisor UDP Broadcast (Master Pi)
│   ├── mpv_controller.py          # Controlador IPC Unix de MPV & Drift sync
│   └── sync_runner.py             # Daemon de ejecución headless para boot
└── tests/
    ├── test_core.py               # Tests de perfiles y autostart
    ├── test_osc.py                # Tests de codificación y loopback OSC
    └── test_sync_runner.py        # Tests del daemon de sincronización
```
