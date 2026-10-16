#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VLC AutoPlay Studio
Herramienta visual para configurar reproducción automática en bucle para instalaciones artísticas.
Diseñado para Raspberry Pi 5 y Raspberry Pi OS (Debian Bookworm).
"""

import os
import sys
import shutil
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional

from core.profile_manager import ProfileManager
from core.autostart import AutostartManager, build_vlc_command

# Paleta de colores Dark Theme Profesional
THEME = {
    "bg": "#13151a",
    "surface": "#1e2129",
    "card": "#262a34",
    "card_border": "#363b49",
    "primary": "#3b82f6",
    "primary_hover": "#2563eb",
    "success": "#10b981",
    "success_hover": "#059669",
    "danger": "#ef4444",
    "danger_hover": "#dc2626",
    "text": "#f9fafb",
    "text_muted": "#9ca3af",
    "text_dim": "#6b7280",
    "accent": "#8b5cf6"
}

def find_vlc_binary() -> str:
    """Detecta el binario de VLC disponible según la plataforma."""
    # En Linux / Raspberry Pi OS:
    for cmd in ["cvlc", "vlc"]:
        if shutil.which(cmd):
            return cmd
    # En macOS:
    mac_vlc = "/Applications/VLC.app/Contents/MacOS/VLC"
    if os.path.exists(mac_vlc):
        return mac_vlc
    return "cvlc"

class VLCAutoPlayApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("VLC AutoPlay Studio - Raspberry Pi")
        self.geometry("960x700")
        self.minsize(860, 620)
        self.configure(bg=THEME["bg"])

        # Inicializar managers
        self.profile_mgr = ProfileManager()
        self.autostart_mgr = AutostartManager()
        
        self.current_profile_id: Optional[str] = None
        self.test_process: Optional[subprocess.Popen] = None

        self._init_styles()
        self._build_header()
        self._build_main_layout()
        self._build_footer()

        # Cargar perfiles iniciales
        self.reload_profiles_list()
        
        # Seleccionar perfil activo por defecto
        active_prof = self.profile_mgr.get_active_profile()
        if active_prof:
            self.select_profile(active_prof["id"])

        self.update_autostart_badge()

        # Manejo de cierre de ventana
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _init_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        # Configuración general
        style.configure(".", background=THEME["bg"], foreground=THEME["text"], font=("Helvetica", 10))
        
        # Frames
        style.configure("Surface.TFrame", background=THEME["surface"])
        style.configure("Card.TFrame", background=THEME["card"], relief="flat")
        
        # Labels
        style.configure("Title.TLabel", font=("Helvetica", 18, "bold"), foreground=THEME["text"], background=THEME["surface"])
        style.configure("Subtitle.TLabel", font=("Helvetica", 10), foreground=THEME["text_muted"], background=THEME["surface"])
        style.configure("CardTitle.TLabel", font=("Helvetica", 11, "bold"), foreground=THEME["text"], background=THEME["card"])
        style.configure("CardText.TLabel", font=("Helvetica", 9), foreground=THEME["text_muted"], background=THEME["card"])
        style.configure("CardTextDim.TLabel", font=("Helvetica", 8, "italic"), foreground=THEME["text_dim"], background=THEME["card"])
        
        # Checkbuttons
        style.configure(
            "Card.TCheckbutton",
            background=THEME["card"],
            foreground=THEME["text"],
            font=("Helvetica", 10),
            focuscolor=THEME["card"]
        )
        style.map("Card.TCheckbutton",
            background=[('active', THEME["card"])],
            foreground=[('active', THEME["primary"])]
        )

        # Scale
        style.configure("Horizontal.TScale", background=THEME["card"], troughcolor=THEME["surface"])

    def _build_header(self):
        header_frame = tk.Frame(self, bg=THEME["surface"], padx=20, pady=14, relief="ridge", bd=1)
        header_frame.pack(fill=tk.X, side=tk.TOP)

        title_box = tk.Frame(header_frame, bg=THEME["surface"])
        title_box.pack(side=tk.LEFT)

        lbl_title = ttk.Label(title_box, text="🎬 VLC AutoPlay Studio", style="Title.TLabel")
        lbl_title.pack(anchor="w")

        lbl_sub = ttk.Label(
            title_box,
            text="Configuración visual de bucles de video/audio en arranque automático (Modo Kiosk)",
            style="Subtitle.TLabel"
        )
        lbl_sub.pack(anchor="w", pady=(2, 0))

        # Badge de estado de arranque
        self.badge_frame = tk.Frame(header_frame, bg=THEME["card"], padx=14, pady=8, bd=1, relief="solid")
        self.badge_frame.pack(side=tk.RIGHT)

        self.lbl_badge_dot = tk.Label(self.badge_frame, text="●", font=("Helvetica", 14), bg=THEME["card"], fg=THEME["danger"])
        self.lbl_badge_dot.pack(side=tk.LEFT, padx=(0, 6))

        self.lbl_badge_text = tk.Label(
            self.badge_frame,
            text="Arranque Inactivo",
            font=("Helvetica", 10, "bold"),
            bg=THEME["card"],
            fg=THEME["text"]
        )
        self.lbl_badge_text.pack(side=tk.LEFT)

    def _build_main_layout(self):
        container = tk.Frame(self, bg=THEME["bg"], padx=16, pady=16)
        container.pack(fill=tk.BOTH, expand=True)

        # ========================================================
        # COLUMNA IZQUIERDA: Lista y gestión de Perfiles
        # ========================================================
        left_col = tk.Frame(container, bg=THEME["surface"], width=260, padx=14, pady=14, bd=1, relief="ridge")
        left_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))
        left_col.pack_propagate(False)

        lbl_prof = tk.Label(
            left_col,
            text="PERFILES DE OBRAS",
            font=("Helvetica", 10, "bold"),
            bg=THEME["surface"],
            fg=THEME["text_muted"]
        )
        lbl_prof.pack(anchor="w", pady=(0, 8))

        # Listbox de perfiles
        list_frame = tk.Frame(left_col, bg=THEME["card"])
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.profile_listbox = tk.Listbox(
            list_frame,
            bg=THEME["card"],
            fg=THEME["text"],
            selectbackground=THEME["primary"],
            selectforeground="#ffffff",
            bd=0,
            highlightthickness=0,
            font=("Helvetica", 10),
            activestyle="none"
        )
        self.profile_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.profile_listbox.bind("<<ListboxSelect>>", self.on_profile_selected)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.profile_listbox.yview, bg=THEME["surface"])
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.profile_listbox.config(yscrollcommand=scrollbar.set)

        # Botones de perfiles
        btn_box = tk.Frame(left_col, bg=THEME["surface"])
        btn_box.pack(fill=tk.X, pady=(10, 0))

        btn_new = tk.Button(
            btn_box,
            text="+ Nuevo",
            command=self.action_new_profile,
            bg=THEME["primary"],
            fg="#ffffff",
            activebackground=THEME["primary_hover"],
            activeforeground="#ffffff",
            relief="flat",
            font=("Helvetica", 9, "bold"),
            cursor="hand2"
        )
        btn_new.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        btn_dup = tk.Button(
            btn_box,
            text="Duplicar",
            command=self.action_duplicate_profile,
            bg=THEME["card"],
            fg=THEME["text"],
            activebackground=THEME["card_border"],
            activeforeground=THEME["text"],
            relief="flat",
            font=("Helvetica", 9),
            cursor="hand2"
        )
        btn_dup.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        btn_del = tk.Button(
            btn_box,
            text="Eliminar",
            command=self.action_delete_profile,
            bg=THEME["card"],
            fg=THEME["danger"],
            activebackground=THEME["card_border"],
            activeforeground=THEME["danger"],
            relief="flat",
            font=("Helvetica", 9),
            cursor="hand2"
        )
        btn_del.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(4, 0))

        # ========================================================
        # COLUMNA DERECHA: Configuración del Perfil Seleccionado
        # ========================================================
        right_col = tk.Frame(container, bg=THEME["bg"])
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Tarjeta 1: Datos Básicos & Nombre
        card_header = tk.Frame(right_col, bg=THEME["surface"], padx=14, pady=10, bd=1, relief="ridge")
        card_header.pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            card_header,
            text="Nombre del Perfil:",
            bg=THEME["surface"],
            fg=THEME["text_muted"],
            font=("Helvetica", 10, "bold")
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.entry_prof_name = tk.Entry(
            card_header,
            bg=THEME["card"],
            fg=THEME["text"],
            insertbackground="#ffffff",
            bd=1,
            relief="solid",
            font=("Helvetica", 11)
        )
        self.entry_prof_name.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.entry_prof_name.bind("<FocusOut>", self.on_name_change)
        self.entry_prof_name.bind("<Return>", self.on_name_change)

        self.btn_save_name = tk.Button(
            card_header,
            text="Renombrar",
            command=self.on_name_change,
            bg=THEME["card"],
            fg=THEME["text"],
            relief="flat",
            font=("Helvetica", 9),
            cursor="hand2"
        )
        self.btn_save_name.pack(side=tk.RIGHT)

        # Tarjeta 2: Selector de Archivo o Carpeta
        card_file = tk.Frame(right_col, bg=THEME["card"], padx=16, pady=14, bd=1, relief="ridge")
        card_file.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(card_file, text="1. Archivo o Carpeta a Reproducir", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            card_file,
            text="Seleccioná un archivo de video/audio, o una carpeta con múltiples archivos para reproducir en secuencia.",
            style="CardText.TLabel"
        ).pack(anchor="w", pady=(2, 8))

        file_pick_row = tk.Frame(card_file, bg=THEME["card"])
        file_pick_row.pack(fill=tk.X)

        self.entry_file_path = tk.Entry(
            file_pick_row,
            bg=THEME["surface"],
            fg=THEME["text"],
            insertbackground="#ffffff",
            bd=1,
            relief="solid",
            font=("Helvetica", 10)
        )
        self.entry_file_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.entry_file_path.bind("<FocusOut>", self.save_current_settings)

        btn_browse_file = tk.Button(
            file_pick_row,
            text="Elegir Archivo...",
            command=self.browse_file,
            bg=THEME["primary"],
            fg="#ffffff",
            activebackground=THEME["primary_hover"],
            relief="flat",
            font=("Helvetica", 9, "bold"),
            cursor="hand2",
            padx=10
        )
        btn_browse_file.pack(side=tk.LEFT, padx=(0, 4))

        btn_browse_dir = tk.Button(
            file_pick_row,
            text="Elegir Carpeta...",
            command=self.browse_directory,
            bg=THEME["card_border"],
            fg=THEME["text"],
            relief="flat",
            font=("Helvetica", 9),
            cursor="hand2",
            padx=8
        )
        btn_browse_dir.pack(side=tk.LEFT)

        # Tarjeta 3: Opciones de Reproducción (Modo Kiosk)
        card_opts = tk.Frame(right_col, bg=THEME["card"], padx=16, pady=14, bd=1, relief="ridge")
        card_opts.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(card_opts, text="2. Ajustes de Exhibición en Sala", style="CardTitle.TLabel").pack(anchor="w")

        # Variables de checkboxes
        self.var_loop = tk.BooleanVar(value=True)
        self.var_fullscreen = tk.BooleanVar(value=True)
        self.var_hide_osd = tk.BooleanVar(value=True)
        self.var_hide_mouse = tk.BooleanVar(value=True)
        self.var_no_audio = tk.BooleanVar(value=False)
        self.var_delay = tk.IntVar(value=5)
        self.var_volume = tk.IntVar(value=100)

        chk_grid = tk.Frame(card_opts, bg=THEME["card"])
        chk_grid.pack(fill=tk.X, pady=(8, 10))

        cb1 = ttk.Checkbutton(
            chk_grid,
            text="Bucle continuo (Loop infinito sin parar)",
            variable=self.var_loop,
            command=self.save_current_settings,
            style="Card.TCheckbutton"
        )
        cb1.grid(row=0, column=0, sticky="w", padx=(0, 20), pady=4)

        cb2 = ttk.Checkbutton(
            chk_grid,
            text="Pantalla completa automática",
            variable=self.var_fullscreen,
            command=self.save_current_settings,
            style="Card.TCheckbutton"
        )
        cb2.grid(row=0, column=1, sticky="w", pady=4)

        cb3 = ttk.Checkbutton(
            chk_grid,
            text="Ocultar título / textos OSD de VLC (Proyección limpia)",
            variable=self.var_hide_osd,
            command=self.save_current_settings,
            style="Card.TCheckbutton"
        )
        cb3.grid(row=1, column=0, sticky="w", padx=(0, 20), pady=4)

        cb4 = ttk.Checkbutton(
            chk_grid,
            text="Ocultar cursor del mouse automáticamente",
            variable=self.var_hide_mouse,
            command=self.save_current_settings,
            style="Card.TCheckbutton"
        )
        cb4.grid(row=1, column=1, sticky="w", pady=4)

        cb5 = ttk.Checkbutton(
            chk_grid,
            text="Silenciar audio por completo (--no-audio)",
            variable=self.var_no_audio,
            command=self.save_current_settings,
            style="Card.TCheckbutton"
        )
        cb5.grid(row=2, column=0, sticky="w", padx=(0, 20), pady=4)

        # Sliders: Delay y Volumen
        slider_frame = tk.Frame(card_opts, bg=THEME["card"])
        slider_frame.pack(fill=tk.X, pady=(6, 0))

        # Delay
        f_delay = tk.Frame(slider_frame, bg=THEME["card"])
        f_delay.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 16))

        self.lbl_delay_val = tk.Label(
            f_delay,
            text="Retardo de arranque: 5 seg",
            bg=THEME["card"],
            fg=THEME["text"],
            font=("Helvetica", 9, "bold")
        )
        self.lbl_delay_val.pack(anchor="w")

        scale_delay = ttk.Scale(
            f_delay,
            from_=0,
            to=30,
            orient="horizontal",
            variable=self.var_delay,
            command=self._on_delay_slide
        )
        scale_delay.pack(fill=tk.X, pady=2)

        ttk.Label(
            f_delay,
            text="Espera a que el monitor HDMI termine de encender.",
            style="CardTextDim.TLabel"
        ).pack(anchor="w")

        # Volumen
        f_vol = tk.Frame(slider_frame, bg=THEME["card"])
        f_vol.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        self.lbl_vol_val = tk.Label(
            f_vol,
            text="Volumen de salida: 100%",
            bg=THEME["card"],
            fg=THEME["text"],
            font=("Helvetica", 9, "bold")
        )
        self.lbl_vol_val.pack(anchor="w")

        scale_vol = ttk.Scale(
            f_vol,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.var_volume,
            command=self._on_vol_slide
        )
        scale_vol.pack(fill=tk.X, pady=2)

        ttk.Label(
            f_vol,
            text="Nivel inicial de ganancia de audio en VLC.",
            style="CardTextDim.TLabel"
        ).pack(anchor="w")

        # Tarjeta 4: Acciones Principales (Boot y Prueba)
        card_actions = tk.Frame(right_col, bg=THEME["surface"], padx=16, pady=14, bd=1, relief="ridge")
        card_actions.pack(fill=tk.BOTH, expand=True)

        ttk.Label(card_actions, text="3. Control de Arranque y Prueba", style="CardTitle.TLabel").pack(anchor="w")

        action_btns = tk.Frame(card_actions, bg=THEME["surface"])
        action_btns.pack(fill=tk.X, pady=(12, 0))

        # Botón de activación en arranque
        self.btn_autostart_toggle = tk.Button(
            action_btns,
            text="⚡ Activar este perfil en el Arranque",
            command=self.toggle_autostart,
            bg=THEME["success"],
            fg="#ffffff",
            activebackground=THEME["success_hover"],
            relief="flat",
            font=("Helvetica", 11, "bold"),
            cursor="hand2",
            padx=16,
            pady=8
        )
        self.btn_autostart_toggle.pack(side=tk.LEFT, padx=(0, 10))

        # Botón de prueba inmediata
        self.btn_test = tk.Button(
            action_btns,
            text="▶ Probar Reproducción Ahora",
            command=self.toggle_test_playback,
            bg=THEME["primary"],
            fg="#ffffff",
            activebackground=THEME["primary_hover"],
            relief="flat",
            font=("Helvetica", 11, "bold"),
            cursor="hand2",
            padx=16,
            pady=8
        )
        self.btn_test.pack(side=tk.LEFT)

    def _build_footer(self):
        footer = tk.Frame(self, bg=THEME["surface"], padx=16, pady=6, bd=1, relief="ridge")
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        self.lbl_status = tk.Label(
            footer,
            text="Listo. Seleccioná un archivo para comenzar.",
            bg=THEME["surface"],
            fg=THEME["text_muted"],
            font=("Helvetica", 9)
        )
        self.lbl_status.pack(side=tk.LEFT)

        vlc_bin = find_vlc_binary()
        lbl_vlc = tk.Label(
            footer,
            text=f"Motor de video detectado: {vlc_bin}",
            bg=THEME["surface"],
            fg=THEME["text_dim"],
            font=("Helvetica", 8)
        )
        lbl_vlc.pack(side=tk.RIGHT)

    def _on_delay_slide(self, val):
        secs = int(float(val))
        self.lbl_delay_val.config(text=f"Retardo de arranque: {secs} seg")
        self.save_current_settings()

    def _on_vol_slide(self, val):
        vol = int(float(val))
        self.lbl_vol_val.config(text=f"Volumen de salida: {vol}%")
        self.save_current_settings()

    # ============================================================
    # LÓGICA DE PERFILES
    # ============================================================
    def reload_profiles_list(self):
        self.profile_listbox.delete(0, tk.END)
        active_id = self.profile_mgr.get_active_profile()
        active_id = active_id["id"] if active_id else None

        profiles = self.profile_mgr.get_profiles()
        for idx, p in enumerate(profiles):
            is_active = (p["id"] == active_id and self.profile_mgr.is_autostart_enabled())
            mark = "★ [BOOT] " if is_active else "  "
            self.profile_listbox.insert(tk.END, f"{mark}{p['name']}")
            if p["id"] == self.current_profile_id:
                self.profile_listbox.select_set(idx)

    def select_profile(self, profile_id: str):
        prof = self.profile_mgr.get_profile(profile_id)
        if not prof:
            return

        self.current_profile_id = profile_id

        # Rellenar campos de la UI
        self.entry_prof_name.delete(0, tk.END)
        self.entry_prof_name.insert(0, prof.get("name", ""))

        self.entry_file_path.delete(0, tk.END)
        self.entry_file_path.insert(0, prof.get("file_path", ""))

        self.var_loop.set(prof.get("loop", True))
        self.var_fullscreen.set(prof.get("fullscreen", True))
        self.var_hide_osd.set(prof.get("hide_osd", True))
        self.var_hide_mouse.set(prof.get("hide_mouse", True))
        self.var_no_audio.set(prof.get("no_audio", False))

        delay = prof.get("delay_seconds", 5)
        self.var_delay.set(delay)
        self.lbl_delay_val.config(text=f"Retardo de arranque: {delay} seg")

        vol = prof.get("volume", 100)
        self.var_volume.set(vol)
        self.lbl_vol_val.config(text=f"Volumen de salida: {vol}%")

        # Seleccionar en el listbox
        profiles = self.profile_mgr.get_profiles()
        for idx, p in enumerate(profiles):
            if p["id"] == profile_id:
                self.profile_listbox.select_clear(0, tk.END)
                self.profile_listbox.select_set(idx)
                break

        self.update_autostart_badge()

    def on_profile_selected(self, event):
        sel = self.profile_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        profiles = self.profile_mgr.get_profiles()
        if 0 <= idx < len(profiles):
            self.select_profile(profiles[idx]["id"])

    def on_name_change(self, event=None):
        if not self.current_profile_id:
            return
        new_name = self.entry_prof_name.get().strip()
        if new_name:
            self.profile_mgr.update_profile(self.current_profile_id, {"name": new_name})
            self.reload_profiles_list()
            self.set_status(f"Perfil renombrado a: '{new_name}'")

    def save_current_settings(self, event=None):
        if not self.current_profile_id:
            return

        updates = {
            "file_path": self.entry_file_path.get().strip(),
            "loop": self.var_loop.get(),
            "fullscreen": self.var_fullscreen.get(),
            "hide_osd": self.var_hide_osd.get(),
            "hide_mouse": self.var_hide_mouse.get(),
            "no_audio": self.var_no_audio.get(),
            "delay_seconds": int(self.var_delay.get()),
            "volume": int(self.var_volume.get())
        }

        self.profile_mgr.update_profile(self.current_profile_id, updates)
        
        # Si el perfil que se modificó es el activo en boot, refrescar el runner
        active = self.profile_mgr.get_active_profile()
        if active and active["id"] == self.current_profile_id and self.profile_mgr.is_autostart_enabled():
            self.autostart_mgr.enable(active)

        self.set_status("Configuración guardada.")

    def action_new_profile(self):
        new_prof = self.profile_mgr.add_profile("Nueva Instalación")
        self.reload_profiles_list()
        self.select_profile(new_prof["id"])
        self.set_status("Nuevo perfil creado.")

    def action_duplicate_profile(self):
        if not self.current_profile_id:
            return
        dup = self.profile_mgr.duplicate_profile(self.current_profile_id)
        if dup:
            self.reload_profiles_list()
            self.select_profile(dup["id"])
            self.set_status("Perfil duplicado.")

    def action_delete_profile(self):
        if not self.current_profile_id:
            return
        profiles = self.profile_mgr.get_profiles()
        if len(profiles) <= 1:
            messagebox.showwarning("Atención", "Debe existir al menos un perfil de instalación.")
            return

        prof = self.profile_mgr.get_profile(self.current_profile_id)
        if messagebox.askyesno("Confirmar", f"¿Estás seguro de eliminar el perfil '{prof['name']}'?"):
            self.profile_mgr.delete_profile(self.current_profile_id)
            active = self.profile_mgr.get_active_profile()
            self.reload_profiles_list()
            if active:
                self.select_profile(active["id"])
            self.set_status("Perfil eliminado.")

    def browse_file(self):
        filetypes = [
            ("Archivos de Video y Audio", "*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.flac *.m4a *.webm *.ogv"),
            ("Todos los archivos", "*.*")
        ]
        chosen = filedialog.askopenfilename(title="Seleccionar archivo de video o audio", filetypes=filetypes)
        if chosen:
            self.entry_file_path.delete(0, tk.END)
            self.entry_file_path.insert(0, chosen)
            self.save_current_settings()
            self.set_status(f"Archivo seleccionado: {os.path.basename(chosen)}")

    def browse_directory(self):
        chosen = filedialog.askdirectory(title="Seleccionar carpeta de medios")
        if chosen:
            self.entry_file_path.delete(0, tk.END)
            self.entry_file_path.insert(0, chosen)
            self.save_current_settings()
            self.set_status(f"Carpeta seleccionada: {chosen}")

    # ============================================================
    # ARRANQUE AUTOMÁTICO (AUTOSTART)
    # ============================================================
    def update_autostart_badge(self):
        is_active = self.autostart_mgr.is_active() and self.profile_mgr.is_autostart_enabled()
        active_prof = self.profile_mgr.get_active_profile()

        if is_active and active_prof:
            self.lbl_badge_dot.config(fg=THEME["success"])
            self.lbl_badge_text.config(
                text=f"Arranque ACTIVO con: {active_prof['name']}",
                fg=THEME["success"]
            )
            if self.current_profile_id == active_prof["id"]:
                self.btn_autostart_toggle.config(
                    text="⏸ Desactivar Arranque Automático",
                    bg=THEME["danger"],
                    activebackground=THEME["danger_hover"]
                )
            else:
                self.btn_autostart_toggle.config(
                    text="⚡ Cambiar Arranque a ESTE perfil",
                    bg=THEME["accent"],
                    activebackground=THEME["primary_hover"]
                )
        else:
            self.lbl_badge_dot.config(fg=THEME["danger"])
            self.lbl_badge_text.config(text="Arranque Inactivo", fg=THEME["text_muted"])
            self.btn_autostart_toggle.config(
                text="⚡ Activar este perfil en el Arranque",
                bg=THEME["success"],
                activebackground=THEME["success_hover"]
            )

    def toggle_autostart(self):
        if not self.current_profile_id:
            return

        self.save_current_settings()
        prof = self.profile_mgr.get_profile(self.current_profile_id)
        if not prof:
            return

        if not prof.get("file_path"):
            messagebox.showwarning("Atención", "Debés elegir un archivo o carpeta de video/audio antes de activar el arranque.")
            return

        is_active = self.autostart_mgr.is_active() and self.profile_mgr.is_autostart_enabled()
        active_id = self.profile_mgr.get_active_profile()
        active_id = active_id["id"] if active_id else None

        if is_active and active_id == self.current_profile_id:
            # Desactivar
            self.autostart_mgr.disable()
            self.profile_mgr.set_autostart_enabled(False)
            self.set_status("Arranque automático desactivado.")
        else:
            # Activar este perfil
            self.profile_mgr.set_active_profile(self.current_profile_id)
            self.autostart_mgr.enable(prof)
            self.profile_mgr.set_autostart_enabled(True)
            self.set_status(f"¡Arranque automático configurado para '{prof['name']}'!")

        self.reload_profiles_list()
        self.update_autostart_badge()

    # ============================================================
    # PRUEBA DE REPRODUCCIÓN INMEDIATA
    # ============================================================
    def toggle_test_playback(self):
        if self.test_process is not None:
            # Detener prueba
            try:
                self.test_process.terminate()
                self.test_process.wait(timeout=2)
            except Exception:
                self.test_process.kill()
            self.test_process = None
            self.btn_test.config(text="▶ Probar Reproducción Ahora", bg=THEME["primary"])
            self.set_status("Prueba de reproducción finalizada.")
            return

        # Iniciar prueba
        self.save_current_settings()
        prof = self.profile_mgr.get_profile(self.current_profile_id)
        if not prof or not prof.get("file_path"):
            messagebox.showwarning("Atención", "Por favor seleccioná un archivo de video o audio para probar.")
            return

        binary = find_vlc_binary()
        cmd = build_vlc_command(prof, binary=binary)

        self.set_status(f"Iniciando reproducción de prueba: {cmd}")
        try:
            # Ejecutar VLC como subproceso
            self.test_process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.btn_test.config(text="⏹ Detener Prueba", bg=THEME["danger"])
            # Chequear periódicamente si sigue corriendo
            self.check_test_process()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo ejecutar VLC: {e}\nAsegurate de que VLC esté instalado.")
            self.test_process = None

    def check_test_process(self):
        if self.test_process is not None:
            ret = self.test_process.poll()
            if ret is not None:
                # El proceso terminó solo (ej. el usuario presionó 'q' o cerró VLC)
                self.test_process = None
                self.btn_test.config(text="▶ Probar Reproducción Ahora", bg=THEME["primary"])
                self.set_status("Reproducción terminada.")
            else:
                self.after(500, self.check_test_process)

    def set_status(self, text: str):
        self.lbl_status.config(text=text)

    def on_close(self):
        if self.test_process is not None:
            try:
                self.test_process.terminate()
            except Exception:
                pass
        self.destroy()

def main():
    app = VLCAutoPlayApp()
    app.mainloop()

if __name__ == "__main__":
    main()
