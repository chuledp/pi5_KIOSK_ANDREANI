#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VLC / MPV AutoPlay Studio (Sync & OSC Edition)
Herramienta visual para configurar reproducción automática y sincronización por red / OSC para instalaciones artísticas.
Diseñado para Raspberry Pi 5 y Raspberry Pi OS (Debian Bookworm).
"""

import os
import sys
import shutil
import subprocess
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional, Dict, Any

from core.profile_manager import ProfileManager, DEFAULT_OSC_MAPPINGS
from core.autostart import AutostartManager, build_vlc_command
from core.sync_runner import SyncDaemon
from core.osc_receiver import OSCReceiver

# Paleta de colores Dark Theme Profesional
THEME = {
    "bg": "#12141a",
    "surface": "#1a1d24",
    "card": "#242832",
    "card_border": "#353a47",
    "primary": "#3b82f6",
    "primary_hover": "#2563eb",
    "success": "#10b981",
    "success_hover": "#059669",
    "danger": "#ef4444",
    "danger_hover": "#dc2626",
    "purple": "#8b5cf6",
    "amber": "#f59e0b",
    "text": "#f9fafb",
    "text_muted": "#9ca3af",
    "text_dim": "#6b7280"
}

def detect_binaries():
    return {
        "mpv": bool(shutil.which("mpv")),
        "vlc": bool(shutil.which("vlc") or shutil.which("cvlc") or os.path.exists("/Applications/VLC.app/Contents/MacOS/VLC"))
    }

class VLCAutoPlayApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("AutoPlay Studio - Kiosk, Red & OSC (Raspberry Pi 5)")
        self.geometry("1020x780")
        self.minsize(920, 680)
        self.configure(bg=THEME["bg"])

        # Inicializar managers
        self.profile_mgr = ProfileManager()
        self.autostart_mgr = AutostartManager()
        
        self.current_profile_id: Optional[str] = None
        self.active_daemon: Optional[SyncDaemon] = None
        self.live_monitor_receiver: Optional[OSCReceiver] = None

        self._init_styles()
        self._build_header()
        self._build_main_layout()
        self._build_osc_monitor()
        self._build_footer()

        # Cargar perfiles iniciales
        self.reload_profiles_list()
        
        active_prof = self.profile_mgr.get_active_profile()
        if active_prof:
            self.select_profile(active_prof["id"])

        self.update_autostart_badge()
        self._start_live_osc_listener()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _init_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=THEME["bg"], foreground=THEME["text"], font=("Helvetica", 10))
        style.configure("Surface.TFrame", background=THEME["surface"])
        style.configure("Card.TFrame", background=THEME["card"], relief="flat")
        
        style.configure("Title.TLabel", font=("Helvetica", 17, "bold"), foreground=THEME["text"], background=THEME["surface"])
        style.configure("Subtitle.TLabel", font=("Helvetica", 9), foreground=THEME["text_muted"], background=THEME["surface"])
        style.configure("CardTitle.TLabel", font=("Helvetica", 11, "bold"), foreground=THEME["text"], background=THEME["card"])
        style.configure("CardText.TLabel", font=("Helvetica", 9), foreground=THEME["text_muted"], background=THEME["card"])
        style.configure("CardTextDim.TLabel", font=("Helvetica", 8, "italic"), foreground=THEME["text_dim"], background=THEME["card"])
        
        style.configure("Card.TCheckbutton", background=THEME["card"], foreground=THEME["text"], font=("Helvetica", 10))
        style.map("Card.TCheckbutton", background=[('active', THEME["card"])], foreground=[('active', THEME["primary"])])

        style.configure("Card.TRadiobutton", background=THEME["card"], foreground=THEME["text"], font=("Helvetica", 10))
        style.map("Card.TRadiobutton", background=[('active', THEME["card"])], foreground=[('active', THEME["primary"])])

        style.configure("Horizontal.TScale", background=THEME["card"], troughcolor=THEME["surface"])

    def _build_header(self):
        header_frame = tk.Frame(self, bg=THEME["surface"], padx=20, pady=12, relief="ridge", bd=1)
        header_frame.pack(fill=tk.X, side=tk.TOP)

        title_box = tk.Frame(header_frame, bg=THEME["surface"])
        title_box.pack(side=tk.LEFT)

        lbl_title = ttk.Label(title_box, text="🎬 AutoPlay Studio • Sync & OSC", style="Title.TLabel")
        lbl_title.pack(anchor="w")

        lbl_sub = ttk.Label(
            title_box,
            text="Kiosk de Video/Audio con Sincronización por Red y Cues OSC (TouchDesigner, Resolume, Reaper)",
            style="Subtitle.TLabel"
        )
        lbl_sub.pack(anchor="w", pady=(2, 0))

        # Badge de estado de arranque
        self.badge_frame = tk.Frame(header_frame, bg=THEME["card"], padx=14, pady=6, bd=1, relief="solid")
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
        container = tk.Frame(self, bg=THEME["bg"], padx=14, pady=10)
        container.pack(fill=tk.BOTH, expand=True)

        # ========================================================
        # COLUMNA IZQUIERDA: Perfiles
        # ========================================================
        left_col = tk.Frame(container, bg=THEME["surface"], width=250, padx=12, pady=12, bd=1, relief="ridge")
        left_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_col.pack_propagate(False)

        lbl_prof = tk.Label(
            left_col,
            text="PERFILES DE OBRA",
            font=("Helvetica", 10, "bold"),
            bg=THEME["surface"],
            fg=THEME["text_muted"]
        )
        lbl_prof.pack(anchor="w", pady=(0, 6))

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

        btn_box = tk.Frame(left_col, bg=THEME["surface"])
        btn_box.pack(fill=tk.X, pady=(8, 0))

        btn_new = tk.Button(
            btn_box,
            text="+ Nuevo",
            command=self.action_new_profile,
            bg=THEME["primary"],
            fg="#ffffff",
            relief="flat",
            font=("Helvetica", 9, "bold"),
            cursor="hand2"
        )
        btn_new.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))

        btn_dup = tk.Button(
            btn_box,
            text="Duplicar",
            command=self.action_duplicate_profile,
            bg=THEME["card"],
            fg=THEME["text"],
            relief="flat",
            font=("Helvetica", 9),
            cursor="hand2"
        )
        btn_dup.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        btn_del = tk.Button(
            btn_box,
            text="Eliminar",
            command=self.action_delete_profile,
            bg=THEME["card"],
            fg=THEME["danger"],
            relief="flat",
            font=("Helvetica", 9),
            cursor="hand2"
        )
        btn_del.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(2, 0))

        # ========================================================
        # COLUMNA DERECHA: Configuración con Pestañas/Tarjetas
        # ========================================================
        right_col = tk.Frame(container, bg=THEME["bg"])
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Tarjeta 1: Header Perfil
        card_header = tk.Frame(right_col, bg=THEME["surface"], padx=14, pady=8, bd=1, relief="ridge")
        card_header.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            card_header,
            text="Nombre:",
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

        # Tarjeta 2: Archivo a reproducir
        card_file = tk.Frame(right_col, bg=THEME["card"], padx=14, pady=10, bd=1, relief="ridge")
        card_file.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(card_file, text="1. Archivo o Carpeta de Medios", style="CardTitle.TLabel").pack(anchor="w")

        file_row = tk.Frame(card_file, bg=THEME["card"])
        file_row.pack(fill=tk.X, pady=(6, 0))

        self.entry_file_path = tk.Entry(
            file_row,
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
            file_row,
            text="Elegir Archivo...",
            command=self.browse_file,
            bg=THEME["primary"],
            fg="#ffffff",
            relief="flat",
            font=("Helvetica", 9, "bold"),
            cursor="hand2",
            padx=8
        )
        btn_browse_file.pack(side=tk.LEFT, padx=(0, 4))

        btn_browse_dir = tk.Button(
            file_row,
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

        # Tarjeta 3: Configuración de Red y OSC
        card_net = tk.Frame(right_col, bg=THEME["card"], padx=14, pady=10, bd=1, relief="ridge")
        card_net.pack(fill=tk.X, pady=(0, 8))

        row_net_top = tk.Frame(card_net, bg=THEME["card"])
        row_net_top.pack(fill=tk.X)

        ttk.Label(row_net_top, text="2. Rol en Red & Sincronización OSC", style="CardTitle.TLabel").pack(side=tk.LEFT)

        btn_mappings = tk.Button(
            row_net_top,
            text="⚙ Mapear Rutas OSC...",
            command=self.open_osc_mappings_dialog,
            bg=THEME["card_border"],
            fg=THEME["text"],
            relief="flat",
            font=("Helvetica", 8, "bold"),
            cursor="hand2",
            padx=8
        )
        btn_mappings.pack(side=tk.RIGHT)

        # Variables de Red
        self.var_network_role = tk.StringVar(value="follower")
        self.var_osc_port = tk.IntVar(value=9000)
        self.var_broadcast_ip = tk.StringVar(value="255.255.255.255")
        self.var_engine = tk.StringVar(value="mpv")

        roles_row = tk.Frame(card_net, bg=THEME["card"])
        roles_row.pack(fill=tk.X, pady=(6, 4))

        rb1 = ttk.Radiobutton(
            roles_row,
            text="📻 Receptor OSC (Follower)",
            variable=self.var_network_role,
            value="follower",
            command=self.on_role_change,
            style="Card.TRadiobutton"
        )
        rb1.pack(side=tk.LEFT, padx=(0, 16))

        rb2 = ttk.Radiobutton(
            roles_row,
            text="📡 Emisor (Master Pi)",
            variable=self.var_network_role,
            value="master",
            command=self.on_role_change,
            style="Card.TRadiobutton"
        )
        rb2.pack(side=tk.LEFT, padx=(0, 16))

        rb3 = ttk.Radiobutton(
            roles_row,
            text="🔌 Autónomo (Sin red)",
            variable=self.var_network_role,
            value="standalone",
            command=self.on_role_change,
            style="Card.TRadiobutton"
        )
        rb3.pack(side=tk.LEFT)

        # Campos de puerto y broadcast
        net_fields_row = tk.Frame(card_net, bg=THEME["card"])
        net_fields_row.pack(fill=tk.X, pady=(4, 0))

        tk.Label(net_fields_row, text="Puerto UDP OSC:", bg=THEME["card"], fg=THEME["text_muted"], font=("Helvetica", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.entry_port = tk.Entry(net_fields_row, width=8, bg=THEME["surface"], fg=THEME["text"], bd=1, relief="solid")
        self.entry_port.pack(side=tk.LEFT, padx=(0, 16))
        self.entry_port.bind("<FocusOut>", self.save_current_settings)

        self.lbl_bcast = tk.Label(net_fields_row, text="IP Broadcast:", bg=THEME["card"], fg=THEME["text_muted"], font=("Helvetica", 9))
        self.lbl_bcast.pack(side=tk.LEFT, padx=(0, 4))
        self.entry_bcast = tk.Entry(net_fields_row, width=16, bg=THEME["surface"], fg=THEME["text"], bd=1, relief="solid")
        self.entry_bcast.pack(side=tk.LEFT, padx=(0, 16))
        self.entry_bcast.bind("<FocusOut>", self.save_current_settings)

        tk.Label(net_fields_row, text="Motor:", bg=THEME["card"], fg=THEME["text_muted"], font=("Helvetica", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.combo_engine = ttk.Combobox(net_fields_row, values=["mpv", "vlc"], width=6, state="readonly", textvariable=self.var_engine)
        self.combo_engine.pack(side=tk.LEFT)
        self.combo_engine.bind("<<ComboboxSelected>>", self.save_current_settings)

        # Tarjeta 4: Ajustes de Exhibición
        card_opts = tk.Frame(right_col, bg=THEME["card"], padx=14, pady=10, bd=1, relief="ridge")
        card_opts.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(card_opts, text="3. Ajustes de Pantalla & Sonido", style="CardTitle.TLabel").pack(anchor="w")

        self.var_loop = tk.BooleanVar(value=True)
        self.var_fullscreen = tk.BooleanVar(value=True)
        self.var_hide_osd = tk.BooleanVar(value=True)
        self.var_hide_mouse = tk.BooleanVar(value=True)
        self.var_no_audio = tk.BooleanVar(value=False)
        self.var_delay = tk.IntVar(value=5)
        self.var_volume = tk.IntVar(value=100)

        chk_grid = tk.Frame(card_opts, bg=THEME["card"])
        chk_grid.pack(fill=tk.X, pady=(4, 6))

        cb1 = ttk.Checkbutton(chk_grid, text="Bucle infinito (Loop)", variable=self.var_loop, command=self.save_current_settings, style="Card.TCheckbutton")
        cb1.grid(row=0, column=0, sticky="w", padx=(0, 20), pady=2)

        cb2 = ttk.Checkbutton(chk_grid, text="Pantalla completa", variable=self.var_fullscreen, command=self.save_current_settings, style="Card.TCheckbutton")
        cb2.grid(row=0, column=1, sticky="w", pady=2)

        cb3 = ttk.Checkbutton(chk_grid, text="Ocultar título / OSD", variable=self.var_hide_osd, command=self.save_current_settings, style="Card.TCheckbutton")
        cb3.grid(row=1, column=0, sticky="w", padx=(0, 20), pady=2)

        cb4 = ttk.Checkbutton(chk_grid, text="Ocultar cursor mouse", variable=self.var_hide_mouse, command=self.save_current_settings, style="Card.TCheckbutton")
        cb4.grid(row=1, column=1, sticky="w", pady=2)

        # Sliders
        slider_frame = tk.Frame(card_opts, bg=THEME["card"])
        slider_frame.pack(fill=tk.X)

        f_delay = tk.Frame(slider_frame, bg=THEME["card"])
        f_delay.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 14))

        self.lbl_delay_val = tk.Label(f_delay, text="Retardo de arranque: 5 seg", bg=THEME["card"], fg=THEME["text"], font=("Helvetica", 9, "bold"))
        self.lbl_delay_val.pack(anchor="w")

        scale_delay = ttk.Scale(f_delay, from_=0, to=30, orient="horizontal", variable=self.var_delay, command=self._on_delay_slide)
        scale_delay.pack(fill=tk.X)

        f_vol = tk.Frame(slider_frame, bg=THEME["card"])
        f_vol.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        self.lbl_vol_val = tk.Label(f_vol, text="Volumen: 100%", bg=THEME["card"], fg=THEME["text"], font=("Helvetica", 9, "bold"))
        self.lbl_vol_val.pack(anchor="w")

        scale_vol = ttk.Scale(f_vol, from_=0, to=100, orient="horizontal", variable=self.var_volume, command=self._on_vol_slide)
        scale_vol.pack(fill=tk.X)

        # Tarjeta 5: Botones de Acción
        card_actions = tk.Frame(right_col, bg=THEME["surface"], padx=14, pady=10, bd=1, relief="ridge")
        card_actions.pack(fill=tk.BOTH, expand=True)

        ttk.Label(card_actions, text="4. Control de Arranque & Prueba en Vivo", style="CardTitle.TLabel").pack(anchor="w")

        action_btns = tk.Frame(card_actions, bg=THEME["surface"])
        action_btns.pack(fill=tk.X, pady=(8, 0))

        self.btn_autostart_toggle = tk.Button(
            action_btns,
            text="⚡ Activar este perfil en el Arranque",
            command=self.toggle_autostart,
            bg=THEME["success"],
            fg="#ffffff",
            relief="flat",
            font=("Helvetica", 10, "bold"),
            cursor="hand2",
            padx=14,
            pady=6
        )
        self.btn_autostart_toggle.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_test = tk.Button(
            action_btns,
            text="▶ Probar Reproducción / Sync Ahora",
            command=self.toggle_test_playback,
            bg=THEME["primary"],
            fg="#ffffff",
            relief="flat",
            font=("Helvetica", 10, "bold"),
            cursor="hand2",
            padx=14,
            pady=6
        )
        self.btn_test.pack(side=tk.LEFT)

    def _build_osc_monitor(self):
        """Monitor en tiempo real de paquetes OSC entrantes."""
        mon_frame = tk.Frame(self, bg=THEME["surface"], padx=16, pady=4, bd=1, relief="ridge")
        mon_frame.pack(fill=tk.X, side=tk.BOTTOM)

        lbl_mon_title = tk.Label(
            mon_frame,
            text="📡 MONITOR OSC EN VIVO:",
            font=("Helvetica", 8, "bold"),
            bg=THEME["surface"],
            fg=THEME["purple"]
        )
        lbl_mon_title.pack(side=tk.LEFT, padx=(0, 8))

        self.lbl_osc_feed = tk.Label(
            mon_frame,
            text="Esperando paquetes en red local...",
            font=("Courier", 9),
            bg=THEME["surface"],
            fg=THEME["text_muted"]
        )
        self.lbl_osc_feed.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _build_footer(self):
        footer = tk.Frame(self, bg=THEME["bg"], padx=16, pady=4)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        self.lbl_status = tk.Label(footer, text="Listo.", bg=THEME["bg"], fg=THEME["text_muted"], font=("Helvetica", 9))
        self.lbl_status.pack(side=tk.LEFT)

        bins = detect_binaries()
        status_txt = f"Motores: MPV [{'OK' if bins['mpv'] else 'Falta'}] | VLC [{'OK' if bins['vlc'] else 'Falta'}]"
        lbl_bins = tk.Label(footer, text=status_txt, bg=THEME["bg"], fg=THEME["text_dim"], font=("Helvetica", 8))
        lbl_bins.pack(side=tk.RIGHT)

    def _on_delay_slide(self, val):
        secs = int(float(val))
        self.lbl_delay_val.config(text=f"Retardo de arranque: {secs} seg")
        self.save_current_settings()

    def _on_vol_slide(self, val):
        vol = int(float(val))
        self.lbl_vol_val.config(text=f"Volumen: {vol}%")
        self.save_current_settings()

    def on_role_change(self):
        role = self.var_network_role.get()
        if role == "master":
            self.lbl_bcast.pack(side=tk.LEFT, padx=(0, 4))
            self.entry_bcast.pack(side=tk.LEFT, padx=(0, 16))
        else:
            self.lbl_bcast.pack_forget()
            self.entry_bcast.pack_forget()
        self.save_current_settings()
        self._restart_live_osc_listener()

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
            role_icon = {"follower": "📻", "master": "📡", "standalone": "🔌"}.get(p.get("network_role", "follower"), "")
            self.profile_listbox.insert(tk.END, f"{mark}{role_icon} {p['name']}")
            if p["id"] == self.current_profile_id:
                self.profile_listbox.select_set(idx)

    def select_profile(self, profile_id: str):
        prof = self.profile_mgr.get_profile(profile_id)
        if not prof:
            return

        self.current_profile_id = profile_id

        self.entry_prof_name.delete(0, tk.END)
        self.entry_prof_name.insert(0, prof.get("name", ""))

        self.entry_file_path.delete(0, tk.END)
        self.entry_file_path.insert(0, prof.get("file_path", ""))

        self.var_network_role.set(prof.get("network_role", "follower"))
        self.entry_port.delete(0, tk.END)
        self.entry_port.insert(0, str(prof.get("osc_port", 9000)))

        self.entry_bcast.delete(0, tk.END)
        self.entry_bcast.insert(0, prof.get("osc_broadcast_ip", "255.255.255.255"))

        self.var_engine.set(prof.get("player_engine", "mpv"))

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
        self.lbl_vol_val.config(text=f"Volumen: {vol}%")

        self.on_role_change()

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

        try:
            port = int(self.entry_port.get().strip() or "9000")
        except ValueError:
            port = 9000

        updates = {
            "file_path": self.entry_file_path.get().strip(),
            "network_role": self.var_network_role.get(),
            "osc_port": port,
            "osc_broadcast_ip": self.entry_bcast.get().strip() or "255.255.255.255",
            "player_engine": self.var_engine.get(),
            "loop": self.var_loop.get(),
            "fullscreen": self.var_fullscreen.get(),
            "hide_osd": self.var_hide_osd.get(),
            "hide_mouse": self.var_hide_mouse.get(),
            "no_audio": self.var_no_audio.get(),
            "delay_seconds": int(self.var_delay.get()),
            "volume": int(self.var_volume.get())
        }

        self.profile_mgr.update_profile(self.current_profile_id, updates)
        
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
            ("Archivos de Video y Audio", "*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.flac *.webm *.ogv"),
            ("Todos los archivos", "*.*")
        ]
        chosen = filedialog.askopenfilename(title="Seleccionar archivo", filetypes=filetypes)
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
    # DIÁLOGO DE MAPEO DE RUTAS OSC
    # ============================================================
    def open_osc_mappings_dialog(self):
        if not self.current_profile_id:
            return
        prof = self.profile_mgr.get_profile(self.current_profile_id)
        if not prof:
            return

        mappings = prof.get("osc_mappings", dict(DEFAULT_OSC_MAPPINGS))

        dlg = tk.Toplevel(self)
        dlg.title("Mapeo Personalizado de Rutas OSC")
        dlg.geometry("520x460")
        dlg.configure(bg=THEME["surface"])
        dlg.transient(self)
        dlg.grab_set()

        lbl_desc = tk.Label(
            dlg,
            text="Configurá las rutas que recibirás desde TouchDesigner, Resolume o Reaper:",
            bg=THEME["surface"],
            fg=THEME["text"],
            font=("Helvetica", 9, "bold")
        )
        lbl_desc.pack(anchor="w", padx=16, pady=(14, 10))

        entries = {}
        form_frame = tk.Frame(dlg, bg=THEME["card"], padx=14, pady=10, bd=1, relief="ridge")
        form_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=4)

        row = 0
        actions = [
            ("/play", "Iniciar reproducción"),
            ("/pause", "Pausar"),
            ("/stop", "Detener al inicio"),
            ("/seek", "Saltar a segundo (/seek <float>)"),
            ("/position", "Posición normalizada (/position <0.0-1.0>)"),
            ("/cue", "Cargar obra/cue (/cue <id>)"),
            ("/volume", "Ajustar volumen (/volume <0-100>)"),
            ("/sync/clock", "Sincronización de reloj continuo")
        ]

        for action, desc in actions:
            curr_val = mappings.get(action, action)
            lbl = tk.Label(form_frame, text=f"{desc}:", bg=THEME["card"], fg=THEME["text_muted"], font=("Helvetica", 9))
            lbl.grid(row=row, column=0, sticky="w", pady=3)

            ent = tk.Entry(form_frame, width=28, bg=THEME["surface"], fg=THEME["text"], bd=1, relief="solid")
            ent.insert(0, curr_val)
            ent.grid(row=row, column=1, sticky="e", pady=3, padx=(10, 0))
            entries[action] = ent
            row += 1

        btn_row = tk.Frame(dlg, bg=THEME["surface"], pady=12)
        btn_row.pack(fill=tk.X, padx=16)

        def save_mappings():
            new_map = {}
            for act, ent in entries.items():
                val = ent.get().strip() or act
                new_map[act] = val
            self.profile_mgr.update_profile(self.current_profile_id, {"osc_mappings": new_map})
            self.set_status("Mapeo OSC actualizado.")
            dlg.destroy()

        def reset_defaults():
            for act, ent in entries.items():
                ent.delete(0, tk.END)
                ent.insert(0, DEFAULT_OSC_MAPPINGS.get(act, act))

        btn_save = tk.Button(btn_row, text="Guardar Mapeos", command=save_mappings, bg=THEME["primary"], fg="#ffffff", relief="flat", font=("Helvetica", 9, "bold"))
        btn_save.pack(side=tk.RIGHT, padx=(6, 0))

        btn_reset = tk.Button(btn_row, text="Restablecer Defaults", command=reset_defaults, bg=THEME["card"], fg=THEME["text"], relief="flat", font=("Helvetica", 9))
        btn_reset.pack(side=tk.RIGHT)

    # ============================================================
    # MONITOR OSC EN VIVO
    # ============================================================
    def _start_live_osc_listener(self):
        try:
            port = int(self.entry_port.get().strip() or "9000")
        except Exception:
            port = 9000

        self.live_monitor_receiver = OSCReceiver(port=port)

        def on_msg(addr, args):
            t_str = time.strftime("%H:%M:%S")
            args_str = ", ".join(f"{a:.2f}" if isinstance(a, float) else str(a) for a in args)
            text = f"[{t_str}] Recibido: {addr}  ({args_str if args_str else 'sin argumentos'})"
            self.after(0, lambda: self.lbl_osc_feed.config(text=text, fg=THEME["success"]))

        self.live_monitor_receiver.on_any(on_msg)
        try:
            self.live_monitor_receiver.start()
        except Exception as e:
            # Puerto en uso por otra app
            self.lbl_osc_feed.config(text=f"Puerto {port} ocupado por otra instancia", fg=THEME["amber"])

    def _restart_live_osc_listener(self):
        if self.live_monitor_receiver:
            self.live_monitor_receiver.stop()
            self.live_monitor_receiver = None
        self._start_live_osc_listener()

    # ============================================================
    # ARRANQUE AUTOMÁTICO (AUTOSTART)
    # ============================================================
    def update_autostart_badge(self):
        is_active = self.autostart_mgr.is_active() and self.profile_mgr.is_autostart_enabled()
        active_prof = self.profile_mgr.get_active_profile()

        if is_active and active_prof:
            self.lbl_badge_dot.config(fg=THEME["success"])
            self.lbl_badge_text.config(
                text=f"Boot ACTIVO: {active_prof['name']} [{active_prof.get('network_role','follower').upper()}]",
                fg=THEME["success"]
            )
            if self.current_profile_id == active_prof["id"]:
                self.btn_autostart_toggle.config(text="⏸ Desactivar Arranque", bg=THEME["danger"])
            else:
                self.btn_autostart_toggle.config(text="⚡ Cambiar Arranque a ESTE", bg=THEME["purple"])
        else:
            self.lbl_badge_dot.config(fg=THEME["danger"])
            self.lbl_badge_text.config(text="Arranque Inactivo", fg=THEME["text_muted"])
            self.btn_autostart_toggle.config(text="⚡ Activar este perfil en el Arranque", bg=THEME["success"])

    def toggle_autostart(self):
        if not self.current_profile_id:
            return

        self.save_current_settings()
        prof = self.profile_mgr.get_profile(self.current_profile_id)
        if not prof or not prof.get("file_path"):
            messagebox.showwarning("Atención", "Debés elegir un archivo de medios antes de activar el arranque.")
            return

        is_active = self.autostart_mgr.is_active() and self.profile_mgr.is_autostart_enabled()
        active_id = self.profile_mgr.get_active_profile()
        active_id = active_id["id"] if active_id else None

        if is_active and active_id == self.current_profile_id:
            self.autostart_mgr.disable()
            self.profile_mgr.set_autostart_enabled(False)
            self.set_status("Arranque automático desactivado.")
        else:
            self.profile_mgr.set_active_profile(self.current_profile_id)
            self.autostart_mgr.enable(prof)
            self.profile_mgr.set_autostart_enabled(True)
            self.set_status(f"¡Arranque configurado con '{prof['name']}'!")

        self.reload_profiles_list()
        self.update_autostart_badge()

    # ============================================================
    # PRUEBA EN VIVO CON SYNC & OSC
    # ============================================================
    def toggle_test_playback(self):
        if self.active_daemon is not None:
            # Detener prueba
            self.active_daemon.stop()
            self.active_daemon = None
            self.btn_test.config(text="▶ Probar Reproducción / Sync Ahora", bg=THEME["primary"])
            self.set_status("Prueba finalizada.")
            self._restart_live_osc_listener()
            return

        self.save_current_settings()
        prof = self.profile_mgr.get_profile(self.current_profile_id)
        if not prof or not prof.get("file_path"):
            messagebox.showwarning("Atención", "Por favor seleccioná un archivo de video o audio para probar.")
            return

        # Pausar monitor pasivo para no colisionar con el puerto del daemon
        if self.live_monitor_receiver:
            self.live_monitor_receiver.stop()
            self.live_monitor_receiver = None

        self.set_status(f"Iniciando prueba en modo {prof.get('network_role', 'follower').upper()}...")
        try:
            self.active_daemon = SyncDaemon(self.profile_mgr)
            self.active_daemon.start(profile_id=self.current_profile_id)
            self.btn_test.config(text="⏹ Detener Prueba", bg=THEME["danger"])
            self.set_status(f"Prueba en curso con perfil '{prof['name']}'. Enviá comandos OSC al puerto {prof.get('osc_port', 9000)}.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo iniciar la prueba: {e}")
            self.active_daemon = None
            self._restart_live_osc_listener()

    def set_status(self, text: str):
        self.lbl_status.config(text=text)

    def on_close(self):
        if self.active_daemon:
            self.active_daemon.stop()
        if self.live_monitor_receiver:
            self.live_monitor_receiver.stop()
        self.destroy()

def main():
    app = VLCAutoPlayApp()
    app.mainloop()

if __name__ == "__main__":
    main()
