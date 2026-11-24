# 🚀 Kiosk Fleet Manager (Torre de Control)

Panel centralizado para administrar, monitorear y actualizar todas las **Raspberry Pi** de la exhibición desde tu notebook sin necesidad de cables, código ni terminales SSH.

---

## 🌟 Características Principales

* **Auto-descubrimiento en Red:** Encuentra automáticamente todas las Raspberry Pi activas en la subred local (o podés agregar IPs manualmente).
* **Control de Reproducción Centralizado:**
  * Botones Maestros: *Reproducir Todas*, *Pausar Todas*, *Reiniciar Videos*, *Volumen Maestro del Edificio*.
  * Control individual por Sala en tarjetas interactivas.
* **Gestor de Videos Remoto:**
  * Explorador de archivos: Mirá qué videos ya están en la Pi (`/home/pi/Videos`, pendrives USB, etc.) y cambialos con 1 clic.
  * **Subida Drag & Drop:** Arrastrá un video nuevo desde tu compu y se transfiere por SFTP a la Pi con barra de progreso en vivo, con opción de reproducirlo inmediatamente al terminar.
* **Ajustes de Exhibición:** Modificá volumen, bucle infinito (loop), pantalla completa, delay de inicio y salidas de audio Focusrite Scarlett 8i6 directamente desde la interfaz web.
* **Diagnóstico y Salud de Hardware:**
  * Temperatura de CPU en tiempo real (°C).
  * Espacio libre en tarjeta SD y memoria RAM.
  * Consola de **Logs en Vivo** para inspeccionar qué está pasando con el reproductor sin abrir la consola.
  * Acciones de 1 clic: **Actualizar Software (`git pull`)**, **Reiniciar Reproductor**, **Reiniciar Raspberry Pi** y **Apagar**.

---

## 🖥️ Cómo Ejecutarlo en tu Notebook

### En macOS:
Hacé doble clic directamente en:
```bash
iniciar_control.command
```
*(O ejecutá `./run.sh` en la terminal)*.

Esto iniciará el servidor local y abrirá automáticamente tu navegador web en:
👉 `http://localhost:5050`

### En Linux / Windows:
```bash
python3 manager_server.py 5050
```

---

## 🔑 Configuración de Credenciales SSH

En la barra superior del panel, hacé clic en **"Credenciales"**:
* Ingresá el usuario (por defecto: `pi`) y la contraseña de tus Raspberry Pi.
* Se guardarán de forma segura en `config.json` de tu notebook y **nunca más te las volverá a pedir**.

---

## 📁 Estructura del Proyecto

```text
kiosk-fleet-manager/
├── iniciar_control.command   # Lanzador de doble clic para Mac
├── run.sh                    # Script de inicio en terminal
├── manager_server.py         # Servidor web local y API REST
├── core/
│   ├── credentials.py        # Gestor de credenciales y configuración
│   ├── discovery.py          # Motor de escaneo y auto-descubrimiento en LAN
│   ├── http_bridge.py        # Cliente REST para consultar estados en vivo (puerto 8080)
│   └── ssh_bridge.py         # Puente SSH/SFTP para subida de videos, logs y comandos
└── static/
    └── index.html            # Interfaz gráfica interactiva (Torre de Control)
```
