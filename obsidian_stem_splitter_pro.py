"""
Obsidian Stem Splitter Pro - Studio Multi-Track AI Source Separation Suite
Splits any audio track into 9 individual stems:
1. 🎤 Vocals (Lead & Backings)
2. 🥁 Drums (Rhythm & Percussion)
3. 🎸 Bass (Bass Guitar & Sub-Bass)
4. 🎸 Guitar (Acoustic & Electric Guitars)
5. 🎹 Keyboard & Synth (Piano, Organs & Synthesizers)
6. 🎺 Brass (Trumpets, Horns, Trombones & Brass Sections)
7. 🎷 Woodwind (Flutes, Clarinets, Saxophones & Reeds)
8. 🎻 Stringed Instruments (Violins, Cellos, Orchestral Strings)
9. ✨ Other / Ambience (Incidental FX, Atmosphere & Residuals)

Optimized for NVIDIA GPU (CUDA) with FP16 Half-Precision Acceleration.
Universal native OLE Drag & Drop across the entire user interface.
Thread-safe background operations: ZERO UI FREEZING on playback, scrubbing, or export.
"""

import os
import sys
import re
import time
import math
import shutil
import tempfile
import threading
import traceback
import subprocess
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
import numpy as np
from PIL import Image, ImageTk, ImageSequence

# PyInstaller Windowed Mode Safe Output (Prevents NoneType write crashes when console=False)
class SafeNullWriter:
    def write(self, text): pass
    def flush(self): pass
    def isatty(self): return False

if sys.stdout is None:
    sys.stdout = SafeNullWriter()
if sys.stderr is None:
    sys.stderr = SafeNullWriter()

# Global crash logger to %APPDATA%\ObsidianStemSplitterPro\crash_log.txt
def log_crash(exc_type, exc_val, exc_tb):
    err_str = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
    try:
        log_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "ObsidianStemSplitterPro"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "crash_log.txt", "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR:\n{err_str}\n")
    except Exception:
        pass

sys.excepthook = log_crash

def get_asset_path(filename: str) -> Path:
    """Resolves asset file paths across local workspace, PyInstaller _MEIPASS bundle, and exe folder."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            p = Path(meipass) / "assets" / filename
            if p.exists():
                return p
            p = Path(meipass) / filename
            if p.exists():
                return p
        exe_dir = Path(sys.executable).parent
        p = exe_dir / "assets" / filename
        if p.exists():
            return p
        p = exe_dir / filename
        if p.exists():
            return p

    local_p = Path(__file__).resolve().parent / "assets" / filename
    if local_p.exists():
        return local_p

    return Path(__file__).resolve().parent / filename

# Safe, native OLE Drag & Drop via TkinterDnD
try:
    from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD
    HAS_TKDND = True
except ImportError:
    HAS_TKDND = False
    DND_FILES = None
    DND_TEXT = None
    TkinterDnD = None

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

from config import (
    APP_NAME, APP_VERSION, STEM_DEFINITIONS, STEM_MAP, AUDIO_EXTENSIONS,
    COLORS, load_settings, save_settings
)
from audio_engine import (
    load_audio, save_audio, get_hardware_info, StemSeparationEngine, DependencyManager
)
from stem_player import StemPlayer, HAS_PYGAME

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

_BASE_CLASSES = (ctk.CTk, TkinterDnD.DnDWrapper) if HAS_TKDND else (ctk.CTk,)


class ObsidianStemSplitterApp(*_BASE_CLASSES):
    """Main application window for Obsidian Stem Splitter Pro."""

    def __init__(self):
        super().__init__()

        # Hook Tkinter callback exceptions to safe logger
        self.report_callback_exception = lambda et, ev, tb: log_crash(et, ev, tb)

        # Initialize TkinterDnD native extension if present
        if HAS_TKDND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception as e:
                print(f"TkinterDnD require notice: {e}")

        self.title(f"{APP_NAME} v{APP_VERSION} — Studio Multi-Track AI Source Separation")
        self.geometry("1280x920")
        self.minsize(1080, 800)
        self.configure(fg_color=COLORS["bg_darkest"])

        ico_file = get_asset_path("app_icon.ico")
        if ico_file.exists():
            try:
                self.iconbitmap(str(ico_file))
            except Exception:
                pass

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.settings = load_settings()
        self.hw_info = get_hardware_info()

        self.engine = StemSeparationEngine(
            use_gpu=self.settings.get("use_gpu", True),
            use_fp16=self.settings.get("use_fp16", True)
        )
        self.player = StemPlayer()

        # State
        self.current_audio_path = None
        self.current_audio_data = None
        self.current_sr = 44100
        self.current_duration = 0.0
        self.separated_stems = {}
        self.stem_checkboxes = {}
        self.mixer_strips = {}
        self.selected_stems = set()
        self._last_selected_stem = None
        self.is_separating = False
        self.is_exporting = False
        self._is_user_scrubbing = False
        self._last_scrub_time = 0.0
        self._vu_was_active = False
        self._daw_frames = []
        self._daw_frame_idx = 0

        # Original Audio Preview Player state (separate from 9-stem mixer player)
        self._orig_channel = None
        self._orig_sound = None
        self._orig_int16 = None
        self._is_orig_playing = False
        self._is_orig_paused = False
        self._orig_play_start_time = 0.0
        self._orig_pause_offset = 0.0
        self._orig_volume = 1.0
        self._prev_orig_volume = 1.0
        self._is_orig_scrubbing = False
        self._ab_mode = "MIX"

        self._build_ui()
        self._setup_dnd()
        self._start_vu_meter_timer()

        # Always set 100% volume for each stem whenever the software opens
        for sid, _, _, _ in STEM_DEFINITIONS:
            self.player.set_volume(sid, 1.0)
            self.player.stem_mutes[sid] = False
            self.player.stem_solos[sid] = False
        self.bind_all("<Key>", self._on_global_key)

    def _safe_after(self, delay_ms: int, func, *args):
        """Thread-safe UI callback invoker that catches mainloop teardown or destroyed window errors."""
        try:
            return self.after(delay_ms, func, *args)
        except Exception:
            return None

    def _start_daw_animation(self):
        """Animates the DAW audio track separating into spectrum frames in a continuous loop while open."""
        try:
            if self._daw_frames and hasattr(self, "daw_anim_lbl"):
                self._daw_frame_idx = (self._daw_frame_idx + 1) % len(self._daw_frames)
                self.daw_anim_lbl.configure(image=self._daw_frames[self._daw_frame_idx])
        except Exception:
            pass
        finally:
            self._safe_after(45, self._start_daw_animation)

    def _on_close(self):
        """Clean application shutdown preventing zombie background threads."""
        try:
            self._on_orig_stop()
        except Exception:
            pass
        try:
            self.player.close()
            self.engine.abort()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)

    def _build_ui(self):
        # Master scrollable frame
        self.main_container = ctk.CTkScrollableFrame(
            self, fg_color=COLORS["bg_darkest"],
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["neon_green"]
        )
        self.main_container.pack(fill="both", expand=True, padx=16, pady=16)

        self._build_header()
        self._build_drop_zone()
        self._build_stem_selector_grid()
        self._build_engine_options()
        self._build_action_bar()
        self._build_mixing_desk()
        self._build_export_hub()

    def _build_header(self):
        self.header_card = ctk.CTkFrame(
            self.main_container,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=2,
            border_color=COLORS["neon_orange"]
        )
        self.header_card.pack(fill="x", pady=(0, 16))

        inner = ctk.CTkFrame(self.header_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        # Left Cluster: Big visible logo + Title & hardware info
        left_box = ctk.CTkFrame(inner, fg_color="transparent")
        left_box.pack(side="left", fill="y", anchor="w")

        logo_path = get_asset_path("logo.jpg")
        if logo_path.exists():
            try:
                logo_pil = Image.open(logo_path)
                self.logo_ctk = ctk.CTkImage(light_image=logo_pil, dark_image=logo_pil, size=(92, 92))
                self.logo_lbl = ctk.CTkLabel(left_box, image=self.logo_ctk, text="")
                self.logo_lbl.pack(side="left", padx=(0, 16))
            except Exception as e:
                print(f"Notice loading logo: {e}")

        # Text inside left box
        text_box = ctk.CTkFrame(left_box, fg_color="transparent")
        text_box.pack(side="left", fill="y", anchor="w")

        title_lbl = ctk.CTkLabel(
            text_box,
            text=f"🎛️ {APP_NAME.upper()}",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["neon_green"]
        )
        title_lbl.pack(anchor="w", pady=(2, 2))

        sub_lbl = ctk.CTkLabel(
            text_box,
            text="High-Resolution 9-Stem AI Source Separation Studio • NVIDIA GPU CUDA Accelerated",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        )
        sub_lbl.pack(anchor="w", pady=(0, 6))

        # Hardware Badge Pill
        badge_frame = ctk.CTkFrame(
            text_box,
            fg_color=COLORS["bg_dark"],
            corner_radius=14,
            border_width=1,
            border_color=COLORS["neon_orange"]
        )
        badge_frame.pack(anchor="w")

        if self.hw_info["is_cuda"]:
            hw_text = f"🟢 NVIDIA CUDA: {self.hw_info['device_name']} ({self.hw_info['vram_gb']} GB VRAM)"
            hw_color = COLORS["neon_green"]
        else:
            hw_text = f"🟢 {self.hw_info['device_name']} [Multi-Threaded]"
            hw_color = COLORS["neon_green"]

        hw_lbl = ctk.CTkLabel(
            badge_frame,
            text=hw_text,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=hw_color
        )
        hw_lbl.pack(padx=12, pady=4)

        # Right Cluster: Looping Animated DAW Audio Track separating into spectrum
        daw_box = ctk.CTkFrame(
            inner,
            fg_color=COLORS["bg_dark"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["neon_orange"]
        )
        daw_box.pack(side="right", padx=(12, 0), anchor="e")

        self._daw_frames = []
        self._daw_frame_idx = 0
        daw_path = get_asset_path("daw_spectrum.gif")
        if daw_path.exists():
            try:
                daw_gif = Image.open(daw_path)
                for f_img in ImageSequence.Iterator(daw_gif):
                    f_rgba = f_img.copy().convert("RGBA")
                    self._daw_frames.append(ctk.CTkImage(light_image=f_rgba, dark_image=f_rgba, size=(360, 86)))
            except Exception as e:
                print(f"Notice loading DAW animation: {e}")

        if self._daw_frames:
            self.daw_anim_lbl = ctk.CTkLabel(daw_box, image=self._daw_frames[0], text="")
            self.daw_anim_lbl.pack(padx=3, pady=3)
            self._start_daw_animation()
        else:
            fallback_lbl = ctk.CTkLabel(
                daw_box,
                text="🎚️ DAW MULTI-TRACK SPECTRUM",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLORS["neon_green"]
            )
            fallback_lbl.pack(padx=20, pady=20)

    def _build_drop_zone(self):
        self.drop_card = ctk.CTkFrame(
            self.main_container,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=2,
            border_color=COLORS["neon_orange"]
        )
        self.drop_card.pack(fill="x", pady=(0, 16), ipady=12)

        self.drop_icon = ctk.CTkLabel(
            self.drop_card,
            text="🎵",
            font=ctk.CTkFont(size=36)
        )
        self.drop_icon.pack(pady=(12, 4))

        self.drop_text = ctk.CTkLabel(
            self.drop_card,
            text="Drag & Drop Any Audio File Here",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["neon_green"]
        )
        self.drop_text.pack(pady=2)

        self.drop_subtext = ctk.CTkLabel(
            self.drop_card,
            text="Drop files anywhere onto the app window • Supports MP3, WAV, FLAC, M4A, OGG, AIFF, AAC, WMA, WebM",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"]
        )
        self.drop_subtext.pack(pady=(0, 10))

        # Button row
        btn_row = ctk.CTkFrame(self.drop_card, fg_color="transparent")
        btn_row.pack(pady=4)

        self.browse_btn = ctk.CTkButton(
            btn_row,
            text="📂 Browse Audio File...",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=COLORS["border"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["neon_green"],
            command=self._on_browse_file
        )
        self.browse_btn.pack(side="left", padx=8)

        if HAS_YTDLP:
            self.yt_btn = ctk.CTkButton(
                btn_row,
                text="🔗 Import from YouTube URL",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=COLORS["border"],
                hover_color=COLORS["bg_card_hover"],
                border_width=1,
                border_color=COLORS["neon_orange"],
                command=self._prompt_youtube_url
            )
            self.yt_btn.pack(side="left", padx=8)

        # File metadata banner & Original Track Preview Player (inside the drag & drop box)
        self.meta_frame = ctk.CTkFrame(
            self.drop_card,
            fg_color=COLORS["bg_dark"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["neon_orange"]
        )

        meta_top = ctk.CTkFrame(self.meta_frame, fg_color="transparent")
        meta_top.pack(fill="x", padx=14, pady=(6, 2))

        self.meta_lbl = ctk.CTkLabel(
            meta_top,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["neon_green"]
        )
        self.meta_lbl.pack(side="left", fill="x", expand=True)

        self.unload_btn = ctk.CTkButton(
            meta_top,
            text="✕ Unload",
            width=70,
            height=24,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#3a1c1c",
            hover_color="#552222",
            border_width=1,
            border_color=COLORS["accent_red"],
            text_color="#ff6666",
            command=self._on_clear_track
        )
        self.unload_btn.pack(side="right", padx=(8, 0))

        # Preview Transport & Volume Row for Original Track
        prev_row = ctk.CTkFrame(self.meta_frame, fg_color="transparent")
        prev_row.pack(fill="x", padx=12, pady=(2, 8))

        # Play / Pause original track
        self.orig_play_btn = ctk.CTkButton(
            prev_row,
            text="▶ Play Original Track",
            width=165,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLORS["accent_green"],
            hover_color="#00b359",
            text_color="#000000",
            command=self._on_orig_play_toggle
        )
        self.orig_play_btn.pack(side="left", padx=4)

        # Stop original track
        self.orig_stop_btn = ctk.CTkButton(
            prev_row,
            text="⏹ Stop",
            width=70,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLORS["border"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            command=self._on_orig_stop
        )
        self.orig_stop_btn.pack(side="left", padx=4)

        # Time label (e.g. 00:00 / 03:45)
        self.orig_time_lbl = ctk.CTkLabel(
            prev_row,
            text="00:00 / 00:00",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        )
        self.orig_time_lbl.pack(side="left", padx=10)

        # Original Volume Controls (packed right)
        orig_vol_box = ctk.CTkFrame(prev_row, fg_color="transparent")
        orig_vol_box.pack(side="right", padx=(8, 2))

        self.orig_vol_btn = ctk.CTkButton(
            orig_vol_box,
            text="🔊 Vol",
            width=68,
            height=30,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            text_color=COLORS["neon_green"],
            command=self._on_orig_vol_btn_click
        )
        self.orig_vol_btn.pack(side="left", padx=(0, 4))

        self.orig_vol_slider = ctk.CTkSlider(
            orig_vol_box,
            from_=0.0,
            to=1.5,
            width=80,
            height=16,
            progress_color=COLORS["neon_green"],
            command=self._on_orig_vol_slider
        )
        self.orig_vol_slider.set(1.0)
        self.orig_vol_slider.pack(side="left", padx=4)

        self.orig_vol_entry = ctk.CTkEntry(
            orig_vol_box,
            width=48,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            justify="center",
            fg_color=COLORS["bg_card"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            text_color=COLORS["neon_green"]
        )
        self.orig_vol_entry.insert(0, "100%")
        self.orig_vol_entry.pack(side="left", padx=4)
        self.orig_vol_entry.bind("<Return>", lambda e: self._on_orig_entry_submit())
        self.orig_vol_entry.bind("<FocusOut>", lambda e: self._on_orig_entry_submit())
        self.orig_vol_entry.bind("<FocusIn>", lambda e: self._safe_after(10, lambda: self.orig_vol_entry.select_range(0, "end")))

        self.orig_100_btn = ctk.CTkButton(
            orig_vol_box,
            text="100%",
            width=46,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            text_color=COLORS["neon_green"],
            command=lambda: self._set_orig_volume_val(1.0)
        )
        self.orig_100_btn.pack(side="left", padx=2)

        # Scrubber slider (middle, expands)
        self.orig_scrub_slider = ctk.CTkSlider(
            prev_row,
            from_=0.0,
            to=1.0,
            progress_color=COLORS["neon_green"],
            command=self._on_orig_scrub_move
        )
        self.orig_scrub_slider.set(0.0)
        self.orig_scrub_slider.pack(side="left", fill="x", expand=True, padx=8)

        # Bind press and release to commit seek smoothly across both widget and inner canvas
        on_orig_press = lambda e: setattr(self, "_is_orig_scrubbing", True)
        self.orig_scrub_slider.bind("<ButtonPress-1>", on_orig_press)
        self.orig_scrub_slider.bind("<ButtonRelease-1>", self._on_orig_scrub_release)
        if hasattr(self.orig_scrub_slider, "_canvas"):
            self.orig_scrub_slider._canvas.bind("<ButtonPress-1>", on_orig_press, add="+")
            self.orig_scrub_slider._canvas.bind("<ButtonRelease-1>", self._on_orig_scrub_release, add="+")

    def _build_stem_selector_grid(self):
        section_box = ctk.CTkFrame(
            self.main_container,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=2,
            border_color=COLORS["neon_orange"]
        )
        section_box.pack(fill="x", pady=(0, 16), padx=0)

        # Header inside section
        sec_header = ctk.CTkFrame(section_box, fg_color="transparent")
        sec_header.pack(fill="x", padx=16, pady=(12, 8))

        sec_title = ctk.CTkLabel(
            sec_header,
            text="🎯 TARGET INSTRUMENT STEMS (9 SEPARATE TRACKS)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["neon_green"]
        )
        sec_title.pack(side="left")

        # Quick select buttons
        quick_box = ctk.CTkFrame(sec_header, fg_color="transparent")
        quick_box.pack(side="right")

        sel_all = ctk.CTkButton(
            quick_box, text="Select All", width=80, height=26,
            font=ctk.CTkFont(size=11), fg_color=COLORS["border"],
            border_width=1, border_color=COLORS["neon_orange"],
            hover_color=COLORS["bg_card_hover"],
            command=lambda: self._set_all_stems(True)
        )
        sel_all.pack(side="left", padx=4)

        desel_all = ctk.CTkButton(
            quick_box, text="Clear", width=60, height=26,
            font=ctk.CTkFont(size=11), fg_color=COLORS["border"],
            border_width=1, border_color=COLORS["neon_orange"],
            hover_color=COLORS["bg_card_hover"],
            command=lambda: self._set_all_stems(False)
        )
        desel_all.pack(side="left", padx=4)

        # 3x3 Grid for 9 Stems
        grid_frame = ctk.CTkFrame(section_box, fg_color="transparent")
        grid_frame.pack(fill="x", padx=16, pady=(0, 16))

        active_stems = self.settings.get("active_stems", [s[0] for s in STEM_DEFINITIONS])

        for idx, (stem_id, name, icon, color) in enumerate(STEM_DEFINITIONS):
            row = idx // 3
            col = idx % 3
            grid_frame.grid_columnconfigure(col, weight=1)

            card = ctk.CTkFrame(
                grid_frame,
                fg_color=COLORS["bg_dark"],
                corner_radius=8,
                border_width=1,
                border_color=COLORS["neon_orange"]
            )
            card.grid(row=row, column=col, padx=6, pady=6, sticky="ew")

            cb_var = ctk.BooleanVar(value=(stem_id in active_stems))
            self.stem_checkboxes[stem_id] = cb_var

            cb = ctk.CTkCheckBox(
                card,
                text=f"{icon}  {name}",
                variable=cb_var,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=COLORS["text_primary"],
                fg_color=color,
                hover_color=color,
                border_color=COLORS["border"]
            )
            cb.pack(padx=12, pady=10, anchor="w")

    def _build_engine_options(self):
        opt_frame = ctk.CTkFrame(
            self.main_container,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=2,
            border_color=COLORS["neon_orange"]
        )
        opt_frame.pack(fill="x", pady=(0, 16), padx=0)

        inner = ctk.CTkFrame(opt_frame, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        # GPU acceleration toggle
        self.gpu_var = ctk.BooleanVar(value=self.settings.get("use_gpu", True))
        gpu_cb = ctk.CTkSwitch(
            inner,
            text="⚡ NVIDIA GPU CUDA Acceleration",
            variable=self.gpu_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            progress_color=COLORS["neon_green"],
            command=self._on_gpu_toggle
        )
        gpu_cb.pack(side="left", padx=8)

        # FP16 Half precision toggle
        self.fp16_var = ctk.BooleanVar(value=self.settings.get("use_fp16", True))
        fp16_cb = ctk.CTkSwitch(
            inner,
            text="🚀 FP16 Half-Precision (2x Speed & 50% VRAM)",
            variable=self.fp16_var,
            font=ctk.CTkFont(size=12),
            progress_color=COLORS["neon_green"]
        )
        fp16_cb.pack(side="left", padx=16)

        # Peak normalization toggle
        self.norm_var = ctk.BooleanVar(value=self.settings.get("normalize_stems", True))
        norm_cb = ctk.CTkSwitch(
            inner,
            text="📊 Peak Normalize Stems (-0.5 dBTP)",
            variable=self.norm_var,
            font=ctk.CTkFont(size=12),
            progress_color=COLORS["neon_green"]
        )
        norm_cb.pack(side="left", padx=16)

    def _build_action_bar(self):
        action_card = ctk.CTkFrame(
            self.main_container,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=2,
            border_color=COLORS["neon_orange"]
        )
        action_card.pack(fill="x", pady=(0, 16))

        inner = ctk.CTkFrame(action_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)

        # Large Separate Button - NEON GREEN
        self.separate_btn = ctk.CTkButton(
            inner,
            text="⚡ SEPARATE 9 STEMS NOW",
            font=ctk.CTkFont(size=16, weight="bold"),
            height=46,
            fg_color=COLORS["neon_green"],
            hover_color="#00cc52",
            text_color="#000000",
            corner_radius=8,
            command=self._start_separation
        )
        self.separate_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Cancel button
        self.cancel_btn = ctk.CTkButton(
            inner,
            text="⏹ Cancel",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=46,
            width=110,
            fg_color=COLORS["accent_red"],
            hover_color="#cc0000",
            state="disabled",
            command=self._abort_separation
        )
        self.cancel_btn.pack(side="right")

        # Progress bar & status row
        self.prog_frame = ctk.CTkFrame(action_card, fg_color="transparent")
        self.prog_frame.pack(fill="x", padx=16, pady=(0, 14))

        self.progress_bar = ctk.CTkProgressBar(
            self.prog_frame,
            fg_color=COLORS["bg_dark"],
            progress_color=COLORS["neon_green"],
            height=12
        )
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", pady=(0, 6))

        self.status_lbl = ctk.CTkLabel(
            self.prog_frame,
            text="Ready. Drop an audio file or click Browse to begin separation.",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        )
        self.status_lbl.pack(anchor="w")

    def _build_mixing_desk(self):
        mixer_card = ctk.CTkFrame(
            self.main_container,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=2,
            border_color=COLORS["neon_orange"]
        )
        mixer_card.pack(fill="x", pady=(0, 16))

        # Header & Master transport
        header = ctk.CTkFrame(mixer_card, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 8))

        title = ctk.CTkLabel(
            header,
            text="🎚️ 9-TRACK STEM MIXING CONSOLE & STUDIO PLAYER",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["neon_green"]
        )
        title.pack(side="left")

        self.selection_badge = ctk.CTkLabel(
            header,
            text="💡 Tip: Click strip to select | Shift/Ctrl for multi-select | Press [M] Mute, [S] Solo",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"]
        )
        self.selection_badge.pack(side="right")

        # Transport controls
        trans_frame = ctk.CTkFrame(
            mixer_card,
            fg_color=COLORS["bg_dark"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["neon_orange"]
        )
        trans_frame.pack(fill="x", padx=16, pady=(0, 12), ipady=4)

        t_inner = ctk.CTkFrame(trans_frame, fg_color="transparent")
        t_inner.pack(fill="x", padx=12, pady=6)

        self.play_btn = ctk.CTkButton(
            t_inner,
            text="▶ Play",
            width=80,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLORS["accent_green"],
            hover_color="#00b359",
            text_color="#000000",
            command=self._on_play_toggle
        )
        self.play_btn.pack(side="left", padx=4)

        self.stop_btn = ctk.CTkButton(
            t_inner,
            text="⏹ Stop",
            width=70,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLORS["border"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            command=self._on_stop_playback
        )
        self.stop_btn.pack(side="left", padx=4)

        # Seamless Section Looping
        self.loop_btn = ctk.CTkButton(
            t_inner,
            text="🔁 Loop: OFF",
            width=92,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["border"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            command=self._on_toggle_loop
        )
        self.loop_btn.pack(side="left", padx=4)

        # Instant A/B Comparison Toggle (Original vs. 9-Stem Mix)
        self.ab_btn = ctk.CTkButton(
            t_inner,
            text="🎧 A/B Test",
            width=88,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            text_color=COLORS["neon_green"],
            command=self._on_ab_toggle
        )
        self.ab_btn.pack(side="left", padx=4)

        self.time_lbl = ctk.CTkLabel(
            t_inner,
            text="00:00 / 00:00",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        )
        self.time_lbl.pack(side="left", padx=12)

        # Master Volume control box in the top box of 9-track mixing console
        self._prev_master_vol = 1.0
        master_box = ctk.CTkFrame(t_inner, fg_color="transparent")
        master_box.pack(side="right", padx=(8, 2))

        # Master Volume Button
        self.master_vol_btn = ctk.CTkButton(
            master_box,
            text="🔊 Master Vol",
            width=105,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            text_color=COLORS["neon_green"],
            command=self._on_master_vol_btn_click
        )
        self.master_vol_btn.pack(side="left", padx=(0, 6))

        # Master Volume Slider (0.0 to 1.5, default 1.0 = 100%)
        self.master_vol_slider = ctk.CTkSlider(
            master_box,
            from_=0.0,
            to=1.5,
            width=85,
            height=16,
            progress_color=COLORS["neon_green"],
            command=self._on_master_slider_change
        )
        self.master_vol_slider.set(1.0)
        self.master_vol_slider.pack(side="left", padx=4)

        # Master Volume Percentage Entry (Editable percentage)
        self.master_vol_entry = ctk.CTkEntry(
            master_box,
            width=50,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            justify="center",
            fg_color=COLORS["bg_card"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            text_color=COLORS["neon_green"]
        )
        self.master_vol_entry.insert(0, "100%")
        self.master_vol_entry.pack(side="left", padx=4)
        self.master_vol_entry.bind("<Return>", lambda e: self._on_master_entry_submit())
        self.master_vol_entry.bind("<FocusOut>", lambda e: self._on_master_entry_submit())
        self.master_vol_entry.bind("<FocusIn>", lambda e: self._safe_after(10, lambda: self.master_vol_entry.select_range(0, "end")))

        # Master Volume 100% Reset Button
        self.master_100_btn = ctk.CTkButton(
            master_box,
            text="100%",
            width=46,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            text_color=COLORS["neon_green"],
            command=lambda: self._set_master_volume_val(1.0)
        )
        self.master_100_btn.pack(side="left", padx=2)

        # Master Output VU Meter & Red Clip Indicator
        self.master_vu = ctk.CTkProgressBar(
            master_box,
            width=70,
            height=14,
            progress_color=COLORS["neon_green"],
            fg_color=COLORS["bg_dark"]
        )
        self.master_vu.set(0.0)
        self.master_vu.pack(side="left", padx=(6, 2))

        self.clip_lbl = ctk.CTkLabel(
            master_box,
            text="CLIP",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLORS["border"],
            width=30
        )
        self.clip_lbl.pack(side="left", padx=(2, 0))

        # Timeline scrubber with smooth release commit
        self.timeline_slider = ctk.CTkSlider(
            t_inner,
            from_=0.0,
            to=1.0,
            progress_color=COLORS["neon_green"],
            command=self._on_scrub_move
        )
        self.timeline_slider.set(0.0)
        self.timeline_slider.pack(side="left", fill="x", expand=True, padx=8)

        # Bind press and release to commit seek smoothly across both widget and inner canvas
        on_press = lambda e: setattr(self, "_is_user_scrubbing", True)
        self.timeline_slider.bind("<ButtonPress-1>", on_press)
        self.timeline_slider.bind("<ButtonRelease-1>", self._on_scrub_release)
        if hasattr(self.timeline_slider, "_canvas"):
            self.timeline_slider._canvas.bind("<ButtonPress-1>", on_press, add="+")
            self.timeline_slider._canvas.bind("<ButtonRelease-1>", self._on_scrub_release, add="+")

        # 9 Stem Channel Strips
        self.channels_container = ctk.CTkFrame(mixer_card, fg_color="transparent")
        self.channels_container.pack(fill="x", padx=16, pady=(0, 16))

        for stem_id, name, icon, color in STEM_DEFINITIONS:
            strip = self._create_channel_strip(self.channels_container, stem_id, name, icon, color)
            self.mixer_strips[stem_id] = strip

    def _create_channel_strip(self, parent, stem_id, name, icon, color):
        strip_frame = ctk.CTkFrame(
            parent,
            fg_color=COLORS["bg_dark"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["neon_orange"]
        )
        strip_frame.pack(fill="x", pady=4, padx=0)

        inner = ctk.CTkFrame(strip_frame, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=6)

        # Multi-select click handlers
        click_handler = lambda e, sid=stem_id: self._on_strip_click(e, sid)
        strip_frame.bind("<Button-1>", click_handler)
        inner.bind("<Button-1>", click_handler)

        # Stem name & icon (clicking selects the strip)
        lbl = ctk.CTkLabel(
            inner,
            text=f"{icon} {name}",
            width=175,
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=color,
            cursor="hand2"
        )
        lbl.pack(side="left", padx=(4, 6))
        lbl.bind("<Button-1>", click_handler)

        # VU Meter
        vu_meter = ctk.CTkProgressBar(
            inner,
            width=90,
            height=8,
            fg_color=COLORS["bg_card"],
            progress_color=color
        )
        vu_meter.set(0.0)
        vu_meter.pack(side="left", padx=6)
        vu_meter.bind("<Button-1>", click_handler)

        # Volume Slider (Initialized to 100% / 1.0)
        vol_slider = ctk.CTkSlider(
            inner,
            from_=0.0,
            to=1.5,
            width=135,
            progress_color=color,
            command=lambda val, sid=stem_id: self._on_stem_volume(sid, val)
        )
        vol_slider.set(1.0)
        vol_slider.pack(side="left", padx=6)

        # Volume Entry (Clickable / Editable percentage input)
        vol_entry = ctk.CTkEntry(
            inner,
            width=50,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            justify="center",
            fg_color=COLORS["bg_card"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            text_color=COLORS["text_primary"]
        )
        vol_entry.insert(0, "100%")
        vol_entry.pack(side="left", padx=4)

        # Bindings for percentage entry
        vol_entry.bind("<Return>", lambda e, sid=stem_id: self._on_stem_vol_entry_submit(sid))
        vol_entry.bind("<FocusOut>", lambda e, sid=stem_id: self._on_stem_vol_entry_submit(sid))
        vol_entry.bind("<FocusIn>", lambda e, entry=vol_entry: self._safe_after(10, lambda: entry.select_range(0, "end")))

        # 100% Reset Button (Click puts volume to 100%)
        reset_btn = ctk.CTkButton(
            inner,
            text="100%",
            width=46,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["neon_orange"],
            text_color=COLORS["neon_green"],
            command=lambda sid=stem_id: self._on_stem_volume_100(sid)
        )
        reset_btn.pack(side="left", padx=4)

        # Mute button [M]
        mute_btn = ctk.CTkButton(
            inner,
            text="M",
            width=32,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["border"],
            command=lambda sid=stem_id: self._on_stem_mute(sid)
        )
        mute_btn.pack(side="left", padx=4)

        # Solo button [S]
        solo_btn = ctk.CTkButton(
            inner,
            text="S",
            width=32,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["border"],
            command=lambda sid=stem_id: self._on_stem_solo(sid)
        )
        solo_btn.pack(side="left", padx=4)

        # Phase Invert button [Ø]
        phase_btn = ctk.CTkButton(
            inner,
            text="Ø",
            width=28,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["border"],
            command=lambda sid=stem_id: self._on_stem_phase(sid)
        )
        phase_btn.pack(side="left", padx=4)

        # Save single stem button
        save_btn = ctk.CTkButton(
            inner,
            text="💾 Save",
            width=70,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border"],
            command=lambda sid=stem_id: self._on_save_single_stem(sid)
        )
        save_btn.pack(side="right", padx=4)

        return {
            "frame": strip_frame,
            "inner": inner,
            "lbl": lbl,
            "vu": vu_meter,
            "slider": vol_slider,
            "vol_entry": vol_entry,
            "reset_btn": reset_btn,
            "mute_btn": mute_btn,
            "solo_btn": solo_btn,
            "phase_btn": phase_btn,
            "save_btn": save_btn,
        }

    def _build_export_hub(self):
        exp_card = ctk.CTkFrame(
            self.main_container,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=2,
            border_color=COLORS["neon_orange"]
        )
        exp_card.pack(fill="x", pady=(0, 20))

        inner = ctk.CTkFrame(exp_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)

        # Format selector
        fmt_box = ctk.CTkFrame(inner, fg_color="transparent")
        fmt_box.pack(side="left", padx=(0, 16))

        fmt_lbl = ctk.CTkLabel(
            fmt_box,
            text="Format:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        )
        fmt_lbl.pack(side="left", padx=(0, 6))

        self.format_menu = ctk.CTkOptionMenu(
            fmt_box,
            values=["WAV (24-bit Lossless)", "WAV (16-bit CD)", "FLAC (Lossless)", "MP3 (320 kbps)"],
            width=190,
            fg_color=COLORS["border"],
            button_color=COLORS["neon_green"],
            button_hover_color="#00cc52",
            text_color="#000000"
        )
        self.format_menu.set("WAV (24-bit Lossless)")
        self.format_menu.pack(side="left")

        # Action Buttons - EXPORT ALL 9 STEMS IS NEON GREEN
        self.exp_all_btn = ctk.CTkButton(
            inner,
            text="📦 EXPORT ALL 9 STEMS",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            fg_color=COLORS["neon_green"],
            hover_color="#00cc52",
            text_color="#000000",
            command=self._on_export_all_stems
        )
        self.exp_all_btn.pack(side="right", padx=6)

        self.mixdown_btn = ctk.CTkButton(
            inner,
            text="🎧 EXPORT CUSTOM MIXDOWN",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            fg_color=COLORS["accent_purple"],
            hover_color="#6c1bb8",
            command=self._on_export_custom_mixdown
        )
        self.mixdown_btn.pack(side="right", padx=6)

    # --- UNIVERSAL DRAG AND DROP HANDLING ---
    def _setup_dnd(self):
        if not HAS_TKDND:
            return

        targets = [
            self,
            self.main_container,
            self.drop_card,
            self.drop_icon,
            self.drop_text,
            self.drop_subtext,
        ]

        for widget in targets:
            try:
                if DND_TEXT:
                    TkinterDnD.DnDWrapper.drop_target_register(widget, DND_FILES, DND_TEXT)
                else:
                    TkinterDnD.DnDWrapper.drop_target_register(widget, DND_FILES)

                TkinterDnD.DnDWrapper.dnd_bind(widget, "<<Drop>>", self._on_drop)
                TkinterDnD.DnDWrapper.dnd_bind(widget, "<<DragEnter>>", self._on_drag_enter)
                TkinterDnD.DnDWrapper.dnd_bind(widget, "<<DragLeave>>", self._on_drag_leave)
            except Exception as e:
                print(f"Widget DnD bind notice: {e}")

    def _on_drag_enter(self, event):
        self.drop_card.configure(border_color=COLORS["neon_green"])

    def _on_drag_leave(self, event):
        self.drop_card.configure(border_color=COLORS["neon_orange"])

    def _on_drop(self, event):
        if self.is_separating or self.is_exporting:
            return

        self.drop_card.configure(border_color=COLORS["neon_orange"])
        raw_data = getattr(event, "data", "")
        if not raw_data:
            return

        clean_raw = raw_data.strip().strip("{}").strip('"')
        if clean_raw.startswith("http://") or clean_raw.startswith("https://"):
            self._handle_youtube_url(clean_raw)
            return

        file_paths = []
        if "{" in raw_data and "}" in raw_data:
            file_paths = re.findall(r"\{([^}]+)\}", raw_data)
        if not file_paths:
            file_paths = [p.strip().strip('"') for p in raw_data.strip().split("\n") if p.strip()]

        if file_paths:
            self._load_file_path(file_paths[0])

    def _on_browse_file(self):
        if self.is_separating or self.is_exporting:
            return

        types = [
            ("All Supported Audio", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.aiff *.wma *.webm"),
            ("WAV Audio", "*.wav"),
            ("MP3 Audio", "*.mp3"),
            ("FLAC Lossless", "*.flac"),
            ("All Files", "*.*")
        ]
        chosen = filedialog.askopenfilename(filetypes=types)
        if chosen:
            self._load_file_path(chosen)

    def _load_file_path(self, path_str: str):
        path = Path(path_str.strip().strip('"'))
        if not path.exists():
            messagebox.showerror("File Error", f"File not found:\n{path_str}")
            return

        ext = path.suffix.lower()
        if ext not in AUDIO_EXTENSIONS:
            messagebox.showwarning("Format Notice", f"Extension '{ext}' might not be a standard audio file. Attempting decode...")

        if hasattr(self, "player") and self.player:
            self.player.stop()
        self._on_orig_stop()
        self.separated_stems.clear()
        if hasattr(self, "play_btn"):
            self.play_btn.configure(text="▶ Play", fg_color=COLORS["accent_green"])
        if hasattr(self, "timeline_slider"):
            self.timeline_slider.set(0.0)
        self._update_time_label(0.0, 0.0)

        self.current_audio_path = str(path)
        self.status_lbl.configure(text=f"Loading metadata for {path.name}...")
        self.update_idletasks()

        try:
            data, sr = load_audio(str(path))
            self.current_audio_data = data
            self.current_sr = sr
            n_samples = data.shape[1]
            self.current_duration = n_samples / float(sr)

            mins = int(self.current_duration // 60)
            secs = int(self.current_duration % 60)
            size_mb = path.stat().st_size / (1024 * 1024)

            meta_text = (
                f"🎵  {path.name}   |   Duration: {mins:02d}:{secs:02d}   |   "
                f"Sample Rate: {sr/1000:.1f} kHz   |   Channels: Stereo   |   Size: {size_mb:.2f} MB"
            )
            self.meta_lbl.configure(text=meta_text)
            self.meta_frame.pack(fill="x", padx=16, pady=(8, 4))
            self.status_lbl.configure(
                text=f"Loaded: {path.name}. Ready for separation.",
                text_color=COLORS["text_secondary"]
            )
            # Initialize original track preview player
            self._init_orig_player(data, sr)
        except Exception as e:
            messagebox.showerror("Audio Load Error", f"Failed to load audio:\n{e}")

    def _prompt_youtube_url(self):
        if self.is_separating or self.is_exporting:
            return
        dialog = ctk.CTkInputDialog(text="Enter YouTube Video or Music URL:", title="Import from YouTube")
        url = dialog.get_input()
        if url:
            self._handle_youtube_url(url.strip())

    def _handle_youtube_url(self, url: str):
        if not HAS_YTDLP:
            messagebox.showerror("Missing Module", "yt-dlp is required for YouTube imports.")
            return

        clean_url = url.strip().strip('"').strip("'")
        if not clean_url:
            return
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            clean_url = "https://" + clean_url

        self.is_separating = True
        self.browse_btn.configure(state="disabled")
        if hasattr(self, "yt_btn"):
            self.yt_btn.configure(state="disabled")
        self.separate_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress_bar.set(0.05)
        self.status_lbl.configure(
            text="⬇ Connecting to YouTube & fetching audio stream...",
            text_color=COLORS["neon_green"]
        )

        def worker():
            try:
                tmp_dir = Path(tempfile.gettempdir()) / "ObsidianStemSplitterYT"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                # Safe ASCII id_timestamp template avoids Windows invalid characters in video titles
                safe_out_tmpl = str(tmp_dir / "%(id)s_%(epoch)s.%(ext)s")
                last_ui_update = [0.0]

                def progress_hook(d):
                    status = d.get("status")
                    if status == "downloading":
                        now = time.time()
                        if now - last_ui_update[0] < 0.12:
                            return
                        last_ui_update[0] = now
                        downloaded = d.get("downloaded_bytes", 0)
                        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                        pct = max(0.0, min(1.0, downloaded / float(total)))
                        gui_pct = 0.05 + pct * 0.40
                        speed = d.get("_speed_str", "").strip()
                        eta = d.get("_eta_str", "").strip()
                        pct_text = f"{int(pct * 100)}%"
                        msg = f"⬇ Downloading YouTube Audio: {pct_text}"
                        if speed:
                            msg += f" ({speed})"
                        if eta:
                            msg += f" [ETA {eta}]"
                        self._safe_after(0, lambda p=gui_pct, m=msg: (
                            self.progress_bar.set(p),
                            self.status_lbl.configure(text=m, text_color=COLORS["neon_green"])
                        ))
                    elif status == "finished":
                        self._safe_after(0, lambda: (
                            self.progress_bar.set(0.48),
                            self.status_lbl.configure(
                                text="🔄 Converting YouTube stream to high-quality studio WAV with FFmpeg...",
                                text_color=COLORS["neon_green"]
                            )
                        ))

                ff_bin = DependencyManager.get_ffmpeg()
                ff_dir = str(Path(ff_bin).parent) if ff_bin and Path(ff_bin).is_file() else ff_bin
                is_pure_playlist = "playlist?list=" in clean_url or ("list=" in clean_url and "v=" not in clean_url and "youtu.be" not in clean_url)

                ydl_opts = {
                    "format": "ba/ba*/140/251/bestaudio/best",
                    "outtmpl": safe_out_tmpl,
                    "playlist_items": "1",
                    "noplaylist": not is_pure_playlist,
                    "extractor_args": {
                        "youtube": {
                            "player_client": ["android_music", "android", "web"]
                        }
                    },
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "wav",
                        "preferredquality": "0",
                    }],
                    "progress_hooks": [progress_hook],
                    "ffmpeg_location": ff_dir,
                    "socket_timeout": 15,
                    "retries": 3,
                    "nocheckcertificate": True,
                    "http_headers": {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    "quiet": True,
                    "no_warnings": True,
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(clean_url, download=True)
                    if not info:
                        raise ValueError("Failed to extract video information from YouTube.")

                    if "entries" in info:
                        entries = [e for e in info.get("entries", []) if e]
                        if not entries:
                            raise ValueError("No valid entries found in YouTube playlist.")
                        info = entries[0]

                    title = info.get("title", "YouTube Track")
                    req_dl = info.get("requested_downloads")
                    wav_path = None
                    if req_dl and len(req_dl) > 0 and "filepath" in req_dl[0]:
                        candidate = Path(req_dl[0]["filepath"])
                        if candidate.exists():
                            wav_path = str(candidate)

                    if not wav_path:
                        candidate = Path(ydl.prepare_filename(info)).with_suffix(".wav")
                        if candidate.exists():
                            wav_path = str(candidate)

                    if not wav_path:
                        wavs = sorted(tmp_dir.glob("*.wav"), key=lambda f: f.stat().st_mtime, reverse=True)
                        if wavs:
                            wav_path = str(wavs[0])

                    if not wav_path or not Path(wav_path).exists():
                        raise FileNotFoundError("Audio was downloaded but the output WAV file could not be located.")

                def on_download_success(path_to_wav, vid_title):
                    self.is_separating = False
                    self._load_file_path(path_to_wav)
                    mins = int(self.current_duration // 60)
                    secs = int(self.current_duration % 60)
                    self.meta_lbl.configure(
                        text=f"📺 YouTube: {vid_title}   |   Duration: {mins:02d}:{secs:02d}   |   Sample Rate: {self.current_sr/1000:.1f} kHz"
                    )
                    self.status_lbl.configure(
                        text=f"✅ Downloaded: {vid_title}. Automatically separating into 9 stems...",
                        text_color=COLORS["neon_green"]
                    )
                    # Automatically trigger stem separation as requested!
                    self._safe_after(200, self._start_separation)

                self._safe_after(0, lambda: on_download_success(wav_path, title))

            except Exception as e:
                log_crash(type(e), e, e.__traceback__)
                err_text = str(e)
                if "is unavailable" in err_text:
                    display_err = "This YouTube video is unavailable or private."
                elif "Sign in" in err_text:
                    display_err = "YouTube bot protection triggered for this video. Please try another link."
                else:
                    display_err = f"Failed to download audio from YouTube:\n{err_text}"
                self._safe_after(0, lambda: messagebox.showerror("YouTube Download Error", display_err))
                self._safe_after(0, lambda: self.status_lbl.configure(
                    text="YouTube download failed.", text_color=COLORS["accent_red"]
                ))
                self._safe_after(0, self._reset_separation_ui)

        threading.Thread(target=worker, daemon=True).start()

    # --- STEM SELECTION HELPERS ---
    def _set_all_stems(self, state: bool):
        if self.is_separating:
            return
        for var in self.stem_checkboxes.values():
            var.set(state)

    def _on_gpu_toggle(self):
        use_gpu = self.gpu_var.get()
        self.engine.use_gpu = use_gpu and (self.hw_info["device"] == "cuda")
        self.engine.device = "cuda" if self.engine.use_gpu else "cpu"

    # --- SEPARATION EXECUTION ---
    def _start_separation(self):
        if self.is_separating or self.is_exporting:
            return

        if not self.current_audio_path:
            messagebox.showinfo("Select Audio", "Please select or drop an audio track first.")
            return

        active_stems = [sid for sid, var in self.stem_checkboxes.items() if var.get()]
        if not active_stems:
            messagebox.showwarning("No Stems Selected", "Please select at least one instrument stem to separate.")
            return

        self.is_separating = True
        self._on_orig_stop()
        if hasattr(self, "orig_play_btn"):
            self.orig_play_btn.configure(state="disabled")
        if hasattr(self, "orig_stop_btn"):
            self.orig_stop_btn.configure(state="disabled")
        self.separate_btn.configure(state="disabled")
        self.browse_btn.configure(state="disabled")
        if hasattr(self, "yt_btn"):
            self.yt_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress_bar.set(0.0)

        def progress_cb(pct: float, stage: str):
            self._safe_after(0, lambda: self._update_progress(pct, stage))

        def worker():
            try:
                stems = self.engine.separate(
                    self.current_audio_path,
                    target_stems=active_stems,
                    progress_callback=progress_cb
                )
                self.separated_stems = stems

                # Buffer stems for player in the background thread (ZERO UI FREEZE)
                progress_cb(0.96, "Buffering stems for audio mixer...")
                try:
                    self.player.load_stems(stems, self.current_sr)
                except Exception as pe:
                    print(f"Notice during stem buffering: {pe}")

                progress_cb(1.0, "Separation complete! Stems ready in Mixing Console.")
                self._safe_after(50, self._on_separation_complete)
            except InterruptedError:
                self._safe_after(0, lambda: self.status_lbl.configure(text="Separation aborted by user."))
            except Exception as e:
                log_crash(type(e), e, e.__traceback__)
                err_text = str(e)
                self._safe_after(0, lambda: messagebox.showerror("Separation Error", f"An error occurred during separation:\n{err_text}"))
                self._safe_after(0, lambda: self.status_lbl.configure(text=f"Error: {err_text}"))
            finally:
                self._safe_after(0, self._reset_separation_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _update_progress(self, pct: float, stage: str):
        self.progress_bar.set(pct)
        self.status_lbl.configure(
            text=f"{int(pct * 100)}% - {stage}",
            text_color=COLORS["text_secondary"]
        )

    def _abort_separation(self):
        self.engine.abort()
        self.cancel_btn.configure(state="disabled")

    def _reset_separation_ui(self):
        self.is_separating = False
        self.separate_btn.configure(state="normal")
        self.browse_btn.configure(state="normal")
        if hasattr(self, "yt_btn"):
            self.yt_btn.configure(state="normal")
        if hasattr(self, "orig_play_btn"):
            self.orig_play_btn.configure(state="normal")
        if hasattr(self, "orig_stop_btn"):
            self.orig_stop_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

    def _on_separation_complete(self):
        self.status_lbl.configure(
            text="✅ Separation Complete! All 9 stems loaded into the Mixing Console below.",
            text_color=COLORS["accent_green"]
        )
        self.progress_bar.set(1.0)
        self._update_time_label(0.0, self.player.duration_seconds)

        # Reset all stems in mixer strictly to 100% volume, unmuted, and unsoloed
        for sid, strip in self.mixer_strips.items():
            strip["slider"].set(1.0)
            strip["vol_entry"].delete(0, "end")
            strip["vol_entry"].insert(0, "100%")
            strip["mute_btn"].configure(fg_color=COLORS["border"])
            strip["solo_btn"].configure(fg_color=COLORS["border"])
            self.player.set_volume(sid, 1.0)
        self.selected_stems.clear()
        self._refresh_mixer_selection_ui()

    # --- ORIGINAL TRACK PREVIEW PLAYER (DRAG & DROP ZONE) ---
    def _init_orig_player(self, data: np.ndarray, sr: int):
        """Initializes direct in-memory playback for the original unseparated track."""
        try:
            if hasattr(self, "player") and self.player:
                if not self.player.is_initialized or self.player._mixer_initialized_sr != sr:
                    self.player._init_mixer(sr)
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=sr, size=-16, channels=2, buffer=1024)
                pygame.mixer.set_num_channels(24)

            # Convert (2, n_samples) float32 to interleaved contiguous int16 in RAM (ZERO DISK I/O)
            clipped = np.clip(data.T * 32767.0, -32768.0, 32767.0).astype(np.int16)
            self._orig_int16 = np.ascontiguousarray(clipped)
            self._orig_sound = pygame.sndarray.make_sound(self._orig_int16)
            self._orig_channel = pygame.mixer.Channel(23)
            eff_vol = min(1.0, max(0.0, self._orig_volume))
            self._orig_channel.set_volume(eff_vol)
        except Exception as e:
            print(f"Notice initializing original preview player: {e}")
            self._orig_sound = None
            self._orig_channel = None

        self._is_orig_playing = False
        self._is_orig_paused = False
        self._orig_play_start_time = 0.0
        self._orig_pause_offset = 0.0

        if hasattr(self, "orig_play_btn"):
            self.orig_play_btn.configure(state="normal", text="▶ Play Original Track", fg_color=COLORS["accent_green"], text_color="#000000")
        if hasattr(self, "orig_stop_btn"):
            self.orig_stop_btn.configure(state="normal")
        if hasattr(self, "orig_scrub_slider"):
            self.orig_scrub_slider.configure(state="normal")
            self.orig_scrub_slider.set(0.0)
        if hasattr(self, "orig_time_lbl"):
            self._update_orig_time_label(0.0, self.current_duration)

    def _on_orig_play_toggle(self):
        """Toggles play/pause for the original unprocessed audio track."""
        if self._orig_sound is None or self.current_duration <= 0:
            messagebox.showinfo("No Audio Loaded", "Please select or drop an audio file first.")
            return

        # Mutual exclusion: stop 9-stem mixer player if running
        if hasattr(self, "player") and self.player and self.player.is_playing:
            self._on_stop_playback()

        if not self._is_orig_playing:
            dur = self.current_duration
            cur_pct = self.orig_scrub_slider.get()
            start_pos = cur_pct * dur if dur > 0 else 0.0
            if dur > 0 and start_pos >= dur - 0.2:
                start_pos = 0.0
                self.orig_scrub_slider.set(0.0)
            self._play_orig_from(start_pos)
            self.orig_play_btn.configure(text="⏸ Pause", fg_color=COLORS["accent_amber"], text_color="#000000")
        elif self._is_orig_paused:
            self._play_orig_from(self._orig_pause_offset)
            self.orig_play_btn.configure(text="⏸ Pause", fg_color=COLORS["accent_amber"], text_color="#000000")
        else:
            self._is_orig_paused = True
            self._orig_pause_offset = self._get_orig_current_pos()
            if self._orig_channel:
                try:
                    self._orig_channel.stop()
                except Exception:
                    pass
            self.orig_play_btn.configure(text="▶ Play Original Track", fg_color=COLORS["accent_green"], text_color="#000000")

    def _play_orig_from(self, start_pos_seconds: float):
        """Starts original track playback from start_pos_seconds."""
        start_pos_seconds = max(0.0, min(start_pos_seconds, self.current_duration))
        if self._orig_channel:
            try:
                self._orig_channel.stop()
            except Exception:
                pass

        try:
            import pygame
            if start_pos_seconds < 0.2:
                sound = self._orig_sound
            else:
                start_sample = int(start_pos_seconds * self.current_sr)
                if self._orig_int16 is not None and start_sample < self._orig_int16.shape[0]:
                    sliced = self._orig_int16[start_sample:]
                    sound = pygame.sndarray.make_sound(sliced)
                else:
                    return

            if self._orig_channel is None:
                self._orig_channel = pygame.mixer.Channel(23)
            eff_vol = min(1.0, max(0.0, self._orig_volume))
            self._orig_channel.set_volume(eff_vol)
            self._orig_channel.play(sound)
            self._is_orig_playing = True
            self._is_orig_paused = False
            self._orig_pause_offset = start_pos_seconds
            self._orig_play_start_time = time.time()
        except Exception as e:
            print(f"Play orig preview error: {e}")

    def _on_orig_stop(self):
        """Stops original preview playback and rewinds to beginning."""
        if self._orig_channel:
            try:
                self._orig_channel.stop()
            except Exception:
                pass
        self._is_orig_playing = False
        self._is_orig_paused = False
        self._orig_pause_offset = 0.0
        self._orig_play_start_time = 0.0
        if hasattr(self, "orig_play_btn"):
            self.orig_play_btn.configure(text="▶ Play Original Track", fg_color=COLORS["accent_green"], text_color="#000000")
        if hasattr(self, "orig_scrub_slider"):
            self.orig_scrub_slider.set(0.0)
        if hasattr(self, "orig_time_lbl"):
            self._update_orig_time_label(0.0, self.current_duration)

    def _get_orig_current_pos(self) -> float:
        """Calculates current elapsed position of the original track in seconds."""
        if not self._is_orig_playing:
            return 0.0
        if self._is_orig_paused:
            return self._orig_pause_offset
        elapsed = time.time() - self._orig_play_start_time
        pos = self._orig_pause_offset + elapsed
        return min(self.current_duration, max(0.0, pos))

    def _update_orig_time_label(self, current: float, total: float):
        """Updates the elapsed / total time display for original track."""
        c_min, c_sec = int(current // 60), int(current % 60)
        t_min, t_sec = int(total // 60), int(total % 60)
        if hasattr(self, "orig_time_lbl"):
            self.orig_time_lbl.configure(text=f"{c_min:02d}:{c_sec:02d} / {t_min:02d}:{t_sec:02d}")

    def _on_orig_scrub_move(self, val: float):
        """Called while dragging original track scrubber."""
        self._is_orig_scrubbing = True
        if self.current_duration > 0:
            target_sec = val * self.current_duration
            self._update_orig_time_label(target_sec, self.current_duration)

    def _on_orig_scrub_release(self, event=None):
        """Called on scrubber release - performs instant low-latency seek."""
        self._is_orig_scrubbing = False
        if self.current_duration > 0 and self._orig_sound:
            target_sec = self.orig_scrub_slider.get() * self.current_duration
            if self._is_orig_playing and not self._is_orig_paused:
                self._play_orig_from(target_sec)
            else:
                self._orig_pause_offset = target_sec
                self._update_orig_time_label(target_sec, self.current_duration)

    def _on_orig_vol_btn_click(self):
        """Toggles mute on original audio preview."""
        if self._orig_volume > 0.0:
            self._prev_orig_volume = self._orig_volume
            self._set_orig_volume_val(0.0)
        else:
            restore = self._prev_orig_volume if self._prev_orig_volume > 0.0 else 1.0
            self._set_orig_volume_val(restore)

    def _on_orig_vol_slider(self, val: float):
        """Updates original preview volume from slider."""
        self._set_orig_volume_val(float(val))

    def _on_orig_entry_submit(self):
        """Handles manual volume percentage entry (e.g. '80%', '120')."""
        text = self.orig_vol_entry.get().replace("%", "").strip()
        try:
            pct = float(text)
            vol = max(0.0, min(1.5, pct / 100.0))
            self._set_orig_volume_val(vol)
        except ValueError:
            self.orig_vol_entry.delete(0, "end")
            self.orig_vol_entry.insert(0, f"{int(round(self._orig_volume * 100))}%")

    def _set_orig_volume_val(self, val: float):
        """Sets preview volume, updating button, entry, slider, and audio channel."""
        val = max(0.0, min(1.5, round(float(val), 2)))
        self._orig_volume = val
        if hasattr(self, "orig_vol_slider"):
            self.orig_vol_slider.set(val)
        if hasattr(self, "orig_vol_entry"):
            self.orig_vol_entry.delete(0, "end")
            self.orig_vol_entry.insert(0, f"{int(round(val * 100))}%")
        if hasattr(self, "orig_vol_btn"):
            if val == 0.0:
                self.orig_vol_btn.configure(text="🔇 Muted", fg_color=COLORS["accent_red"], text_color="#ffffff")
            else:
                self.orig_vol_btn.configure(text="🔊 Vol", fg_color=COLORS["bg_card"], text_color=COLORS["neon_green"])
        if self._orig_channel:
            eff_vol = min(1.0, max(0.0, val))
            self._orig_channel.set_volume(eff_vol)

    # --- MIXER & PLAYBACK CONTROLS ---
    def _on_play_toggle(self):
        # Stop original track preview if running
        self._on_orig_stop()
        if not self.separated_stems:
            messagebox.showinfo("No Stems", "Separate an audio track first to preview stems.")
            return

        if not self.player.is_playing:
            dur = self.player.duration_seconds
            cur_pct = self.timeline_slider.get()
            start_pos = cur_pct * dur if dur > 0 else 0.0
            if dur > 0 and start_pos >= dur - 0.2:
                start_pos = 0.0
                self.timeline_slider.set(0.0)
            self.player.play(start_pos)
            self.play_btn.configure(text="⏸ Pause", fg_color=COLORS["accent_amber"])
        elif self.player.is_paused:
            self.player.play(self.player.pause_offset)
            self.play_btn.configure(text="⏸ Pause", fg_color=COLORS["accent_amber"])
        else:
            self.player.pause()
            self.play_btn.configure(text="▶ Play", fg_color=COLORS["accent_green"])

    def _on_stop_playback(self):
        self.player.stop()
        self.play_btn.configure(text="▶ Play", fg_color=COLORS["accent_green"])
        self.timeline_slider.set(0.0)
        self._update_time_label(0.0, self.player.duration_seconds)

    def _on_scrub_move(self, val: float):
        """Called while dragging scrubber - updates time label smoothly without reloading sounds."""
        self._is_user_scrubbing = True
        if self.player.duration_seconds > 0:
            target_sec = val * self.player.duration_seconds
            self._update_time_label(target_sec, self.player.duration_seconds)

    def _on_scrub_release(self, event=None):
        """Called when mouse is released on scrubber - commits the seek instantly."""
        self._is_user_scrubbing = False
        if self.player.duration_seconds > 0 and self.separated_stems:
            target_sec = self.timeline_slider.get() * self.player.duration_seconds
            self.player.seek(target_sec)

    # --- MASTER VOLUME CONTROLS ---
    def _on_master_vol_btn_click(self):
        """Toggles master volume mute/unmute."""
        cur = self.master_vol_slider.get()
        if cur > 0.001:
            self._prev_master_vol = cur
            self._set_master_volume_val(0.0)
            self.master_vol_btn.configure(text="🔇 Muted", text_color=COLORS["accent_red"])
        else:
            restored = self._prev_master_vol if self._prev_master_vol > 0.001 else 1.0
            self._set_master_volume_val(restored)
            self.master_vol_btn.configure(text="🔊 Master Vol", text_color=COLORS["neon_green"])

    def _on_master_slider_change(self, val: float):
        """Called when master volume slider is moved."""
        pct = int(round(val * 100))
        self.master_vol_entry.delete(0, "end")
        self.master_vol_entry.insert(0, f"{pct}%")
        if val <= 0.001:
            self.master_vol_btn.configure(text="🔇 Muted", text_color=COLORS["accent_red"])
        else:
            self.master_vol_btn.configure(text="🔊 Master Vol", text_color=COLORS["neon_green"])
        self.player.set_master_volume(val)

    def _on_master_entry_submit(self):
        """Called when user types in master volume entry."""
        raw = self.master_vol_entry.get().replace("%", "").strip()
        try:
            val = float(raw)
            val = max(0.0, min(val, 150.0))
        except ValueError:
            cur = self.master_vol_slider.get()
            val = cur * 100.0
        pct = int(round(val))
        self.master_vol_entry.delete(0, "end")
        self.master_vol_entry.insert(0, f"{pct}%")
        vol_float = pct / 100.0
        self.master_vol_slider.set(vol_float)
        if vol_float <= 0.001:
            self.master_vol_btn.configure(text="🔇 Muted", text_color=COLORS["accent_red"])
        else:
            self.master_vol_btn.configure(text="🔊 Master Vol", text_color=COLORS["neon_green"])
        self.player.set_master_volume(vol_float)

    def _set_master_volume_val(self, val: float):
        """Directly sets master volume value (0.0 to 1.5)."""
        val = max(0.0, min(val, 1.5))
        self.master_vol_slider.set(val)
        pct = int(round(val * 100))
        self.master_vol_entry.delete(0, "end")
        self.master_vol_entry.insert(0, f"{pct}%")
        if val <= 0.001:
            self.master_vol_btn.configure(text="🔇 Muted", text_color=COLORS["accent_red"])
        else:
            self.master_vol_btn.configure(text="🔊 Master Vol", text_color=COLORS["neon_green"])
        self.player.set_master_volume(val)

    # --- MULTI-STEM SELECTION & CHANNEL CONTROLS ---
    def _on_strip_click(self, event, stem_id: str):
        # Bitwise check for Shift (0x0001) and Control (0x0004) modifiers on Windows Tkinter
        is_shift = bool(event.state & 0x0001)
        is_ctrl = bool(event.state & 0x0004)

        stem_order = [s[0] for s in STEM_DEFINITIONS]

        if is_shift and self._last_selected_stem and self._last_selected_stem in stem_order:
            # Shift-click: contiguous range selection from last selected stem
            idx1 = stem_order.index(self._last_selected_stem)
            idx2 = stem_order.index(stem_id)
            start_idx, end_idx = min(idx1, idx2), max(idx1, idx2)
            for i in range(start_idx, end_idx + 1):
                self.selected_stems.add(stem_order[i])
        elif is_ctrl:
            # Ctrl-click: toggle selection of individual stem
            if stem_id in self.selected_stems:
                self.selected_stems.remove(stem_id)
            else:
                self.selected_stems.add(stem_id)
            self._last_selected_stem = stem_id
        else:
            # Normal click: single selection
            self.selected_stems = {stem_id}
            self._last_selected_stem = stem_id

        self._refresh_mixer_selection_ui()

    def _on_mixer_bg_click(self, event):
        widget = event.widget
        for sid, strip in self.mixer_strips.items():
            if str(widget).startswith(str(strip["frame"])):
                return
        self.selected_stems.clear()
        self._refresh_mixer_selection_ui()

    def _refresh_mixer_selection_ui(self):
        for sid, strip in self.mixer_strips.items():
            is_selected = sid in self.selected_stems
            if is_selected:
                strip["frame"].configure(
                    border_color=COLORS["neon_green"],
                    border_width=2,
                    fg_color="#132418"
                )
            else:
                strip["frame"].configure(
                    border_color=COLORS["neon_orange"],
                    border_width=1,
                    fg_color=COLORS["bg_dark"]
                )

        if hasattr(self, "selection_badge"):
            count = len(self.selected_stems)
            if count == 0:
                self.selection_badge.configure(
                    text="💡 Tip: Click strip to select | Shift/Ctrl for multi-select | Press [M] Mute, [S] Solo",
                    text_color=COLORS["text_secondary"]
                )
            elif count == 1:
                stem_name = next(iter(self.selected_stems))
                self.selection_badge.configure(
                    text=f"🎯 1 STEM SELECTED ({stem_name.upper()}) — Press [M] Mute, [S] Solo, [100%] Reset",
                    text_color=COLORS["neon_green"]
                )
            else:
                self.selection_badge.configure(
                    text=f"🎯 {count} STEMS SELECTED — Press [M] Mute all, [S] Solo, type % or drag fader to control together",
                    text_color=COLORS["neon_green"]
                )

    def _on_stem_volume(self, stem_id: str, val: float):
        if stem_id in self.selected_stems and len(self.selected_stems) > 1:
            targets = [sid for sid, _, _, _ in STEM_DEFINITIONS if sid in self.selected_stems]
        else:
            targets = [stem_id]

        pct = int(val * 100)
        formatted = f"{pct}%"

        for sid in targets:
            self.player.set_volume(sid, val)
            s_strip = self.mixer_strips.get(sid)
            if s_strip:
                if sid != stem_id:
                    s_strip["slider"].set(val)
                s_strip["vol_entry"].delete(0, "end")
                s_strip["vol_entry"].insert(0, formatted)

    def _on_stem_vol_entry_submit(self, stem_id: str):
        strip = self.mixer_strips.get(stem_id)
        if not strip:
            return
        entry = strip["vol_entry"]
        raw = entry.get().strip().replace("%", "").strip()
        try:
            val = float(raw)
            val = max(0.0, min(150.0, val))
            vol_ratio = val / 100.0
            formatted = f"{int(val)}%"
        except (ValueError, TypeError):
            current_val = strip["slider"].get()
            formatted = f"{int(current_val * 100)}%"
            vol_ratio = current_val

        if stem_id in self.selected_stems and len(self.selected_stems) > 1:
            targets = [sid for sid, _, _, _ in STEM_DEFINITIONS if sid in self.selected_stems]
        else:
            targets = [stem_id]

        for sid in targets:
            s_strip = self.mixer_strips.get(sid)
            if s_strip:
                s_strip["slider"].set(vol_ratio)
                s_strip["vol_entry"].delete(0, "end")
                s_strip["vol_entry"].insert(0, formatted)
                self.player.set_volume(sid, vol_ratio)

    def _on_stem_volume_100(self, stem_id: str):
        """Puts volume to 100% for the stem (and all selected stems if multi-selected)."""
        if stem_id in self.selected_stems and len(self.selected_stems) > 1:
            targets = [sid for sid, _, _, _ in STEM_DEFINITIONS if sid in self.selected_stems]
        else:
            targets = [stem_id]

        for sid in targets:
            s_strip = self.mixer_strips.get(sid)
            if s_strip:
                s_strip["slider"].set(1.0)
                s_strip["vol_entry"].delete(0, "end")
                s_strip["vol_entry"].insert(0, "100%")
                self.player.set_volume(sid, 1.0)

    def _on_stem_mute(self, stem_id: str):
        if stem_id in self.selected_stems and len(self.selected_stems) > 1:
            targets = [sid for sid, _, _, _ in STEM_DEFINITIONS if sid in self.selected_stems]
            any_unmuted = any(not self.player.stem_mutes.get(sid, False) for sid in targets)
            new_mute_state = any_unmuted
            self.player.set_multi_mute(targets, new_mute_state)
            for sid in targets:
                s_strip = self.mixer_strips.get(sid)
                if s_strip:
                    s_strip["mute_btn"].configure(
                        fg_color=COLORS["accent_red"] if new_mute_state else COLORS["border"]
                    )
        else:
            is_muted = self.player.toggle_mute(stem_id)
            strip = self.mixer_strips.get(stem_id)
            if strip:
                strip["mute_btn"].configure(
                    fg_color=COLORS["accent_red"] if is_muted else COLORS["border"]
                )

    def _on_stem_solo(self, stem_id: str):
        if stem_id in self.selected_stems and len(self.selected_stems) > 1:
            targets = [sid for sid, _, _, _ in STEM_DEFINITIONS if sid in self.selected_stems]
            any_unsoloed = any(not self.player.stem_solos.get(sid, False) for sid in targets)
            new_solo_state = any_unsoloed
            self.player.set_multi_solo(targets, new_solo_state)
            for sid in targets:
                s_strip = self.mixer_strips.get(sid)
                if s_strip:
                    s_strip["solo_btn"].configure(
                        fg_color=COLORS["accent_green"] if new_solo_state else COLORS["border"]
                    )
        else:
            is_solo = self.player.toggle_solo(stem_id)
            strip = self.mixer_strips.get(stem_id)
            if strip:
                strip["solo_btn"].configure(
                    fg_color=COLORS["accent_green"] if is_solo else COLORS["border"]
                )

    def _on_stem_phase(self, stem_id: str):
        """Toggles 180° phase inversion on a stem and updates the button color."""
        is_inv = self.player.toggle_phase(stem_id)
        strip = self.mixer_strips.get(stem_id)
        if strip and "phase_btn" in strip:
            strip["phase_btn"].configure(
                fg_color=COLORS["accent_amber"] if is_inv else COLORS["border"],
                text_color="#000000" if is_inv else COLORS["text_primary"]
            )

    def _on_toggle_loop(self):
        """Toggles seamless looping across the 9-stem player."""
        is_loop = self.player.toggle_loop()
        if is_loop:
            self.loop_btn.configure(text="🔁 Loop: ON", fg_color=COLORS["accent_purple"])
        else:
            self.loop_btn.configure(text="🔁 Loop: OFF", fg_color=COLORS["border"])

    def _on_ab_toggle(self):
        """Seamlessly toggles playback between the 9-stem mix and the original unseparated track at the exact same playhead."""
        if not self.separated_stems or self.current_audio_data is None:
            messagebox.showinfo("A/B Test", "Separate audio stems first to compare with the original track.")
            return

        if self._ab_mode == "MIX":
            # Switch to Original Preview
            cur_pos = self.player.get_current_position() if self.player.is_playing else self.timeline_slider.get() * self.player.duration_seconds
            was_playing = self.player.is_playing and not self.player.is_paused
            self.player.stop()
            self._ab_mode = "ORIG"
            self.ab_btn.configure(text="🎵 A/B (Orig)", fg_color=COLORS["accent_purple"])
            if was_playing:
                self._play_orig_from(cur_pos)
                self.play_btn.configure(text="▶ Play", fg_color=COLORS["accent_green"])
            else:
                self._orig_pause_offset = cur_pos
                self._update_orig_time_label(cur_pos, self.current_duration)
        else:
            # Switch back to 9-Stem Mix
            cur_pos = self._get_orig_current_pos() if self._is_orig_playing else self.orig_scrub_slider.get() * self.current_duration
            was_playing = self._is_orig_playing and not self._is_orig_paused
            self._on_orig_stop()
            self._ab_mode = "MIX"
            self.ab_btn.configure(text="🎚️ A/B (Mix)", fg_color=COLORS["bg_card"])
            if was_playing:
                self.player.play(cur_pos)
                self.play_btn.configure(text="⏸ Pause", fg_color=COLORS["accent_amber"])
            else:
                self.player.pause_offset = cur_pos
                pct = cur_pos / self.player.duration_seconds if self.player.duration_seconds > 0 else 0.0
                self.timeline_slider.set(pct)
                self._update_time_label(cur_pos, self.player.duration_seconds)

    def _on_clear_track(self):
        """Clears the loaded audio track and stems, resetting to pristine initial state."""
        self._on_orig_stop()
        self._on_stop_playback()
        self.current_audio_data = None
        self.current_audio_path = ""
        self.current_duration = 0.0
        self.separated_stems.clear()
        self.player.load_stems({}, 44100)

        # Hide metadata and preview banner
        self.meta_frame.pack_forget()

        # Reset main status and progress
        self.status_lbl.configure(
            text="Ready. Select or drag & drop an audio file above.",
            text_color=COLORS["text_secondary"]
        )
        self.progress_bar.set(0.0)

        # Reset transport & mixer controls
        self.play_btn.configure(text="▶ Play", fg_color=COLORS["accent_green"])
        self.timeline_slider.set(0.0)
        self._update_time_label(0.0, 0.0)

        for strip in self.mixer_strips.values():
            strip["slider"].set(1.0)
            strip["vol_entry"].delete(0, "end")
            strip["vol_entry"].insert(0, "100%")
            strip["mute_btn"].configure(fg_color=COLORS["border"])
            strip["solo_btn"].configure(fg_color=COLORS["border"])
            if "phase_btn" in strip:
                strip["phase_btn"].configure(fg_color=COLORS["border"], text_color=COLORS["text_primary"])
            strip["vu"].set(0.0)

        if hasattr(self, "master_vu"):
            self.master_vu.set(0.0)
        if hasattr(self, "clip_lbl"):
            self.clip_lbl.configure(text_color=COLORS["border"])

        self.selected_stems.clear()
        self._refresh_mixer_selection_ui()

    def _on_global_key(self, event):
        focused = self.focus_get()
        if focused is not None:
            cls_name = focused.__class__.__name__
            if "Entry" in cls_name or "Text" in cls_name:
                return

        keysym = event.keysym.lower() if event.keysym else ""
        char = event.char.lower() if event.char else ""

        # Pressing 'M' / 'm': mutes/unmutes all selected stems
        if keysym == "m" or char == "m":
            if self.selected_stems:
                targets = [sid for sid, _, _, _ in STEM_DEFINITIONS if sid in self.selected_stems]
                any_unmuted = any(not self.player.stem_mutes.get(sid, False) for sid in targets)
                new_state = any_unmuted
                self.player.set_multi_mute(targets, new_state)
                for sid in targets:
                    strip = self.mixer_strips.get(sid)
                    if strip:
                        strip["mute_btn"].configure(
                            fg_color=COLORS["accent_red"] if new_state else COLORS["border"]
                        )
            return "break"

        # Pressing 'S' / 's': solos/unsolos all selected stems
        elif keysym == "s" or char == "s":
            if self.selected_stems:
                targets = [sid for sid, _, _, _ in STEM_DEFINITIONS if sid in self.selected_stems]
                any_unsoloed = any(not self.player.stem_solos.get(sid, False) for sid in targets)
                new_state = any_unsoloed
                self.player.set_multi_solo(targets, new_state)
                for sid in targets:
                    strip = self.mixer_strips.get(sid)
                    if strip:
                        strip["solo_btn"].configure(
                            fg_color=COLORS["accent_green"] if new_state else COLORS["border"]
                        )
            return "break"

        # Pressing 'P' / 'p': toggles phase inversion for selected stems
        elif keysym == "p" or char == "p":
            if self.selected_stems:
                targets = [sid for sid, _, _, _ in STEM_DEFINITIONS if sid in self.selected_stems]
                for sid in targets:
                    self._on_stem_phase(sid)
            return "break"

        # Spacebar: Smart Play / Pause toggle
        elif keysym == "space":
            if self.current_audio_data is not None and (self._is_orig_playing or not self.separated_stems):
                self._on_orig_play_toggle()
            else:
                self._on_play_toggle()
            return "break"

        # Escape: Clear stem selection
        elif keysym == "escape":
            self.selected_stems.clear()
            self._refresh_mixer_selection_ui()
            return "break"

        # Ctrl+A: Select all stems
        elif keysym == "a" and bool(event.state & 0x0004):
            self.selected_stems = set(sid for sid, _, _, _ in STEM_DEFINITIONS)
            self._refresh_mixer_selection_ui()
            return "break"

    def _update_time_label(self, current: float, total: float):
        c_min, c_sec = int(current // 60), int(current % 60)
        t_min, t_sec = int(total // 60), int(total % 60)
        self.time_lbl.configure(text=f"{c_min:02d}:{c_sec:02d} / {t_min:02d}:{t_sec:02d}")

    def _start_vu_meter_timer(self):
        """Refreshes VU meters, master level, and scrubber position ~25 times per second only when playing."""
        try:
            # 1. 9-stem mixer player updates
            if self.player.is_playing and not self.player.is_paused:
                pos = self.player.get_current_position()
                dur = self.player.duration_seconds

                # Seamless loop check at end of track
                if dur > 0 and pos >= dur - 0.25:
                    if self.player.is_looping:
                        self.player.play(0.0)
                        self.timeline_slider.set(0.0)
                        self._update_time_label(0.0, dur)
                        pos = 0.0
                    else:
                        self._on_stop_playback()

                if dur > 0 and not self._is_user_scrubbing:
                    self.timeline_slider.set(pos / dur)
                    self._update_time_label(pos, dur)

                for stem_id, strip in self.mixer_strips.items():
                    level = self.player.get_level(stem_id)
                    strip["vu"].set(level)

                # Master Output VU and CLIP indicator
                m_level, is_clip = self.player.get_master_level()
                if hasattr(self, "master_vu"):
                    self.master_vu.set(m_level)
                if hasattr(self, "clip_lbl"):
                    self.clip_lbl.configure(text_color=COLORS["accent_red"] if is_clip else COLORS["border"])

                self._vu_was_active = True
            elif self._vu_was_active:
                for strip in self.mixer_strips.values():
                    strip["vu"].set(0.0)
                if hasattr(self, "master_vu"):
                    self.master_vu.set(0.0)
                if hasattr(self, "clip_lbl"):
                    self.clip_lbl.configure(text_color=COLORS["border"])
                self._vu_was_active = False
                if not self.player.is_playing:
                    self.play_btn.configure(text="▶ Play", fg_color=COLORS["accent_green"])

            # 2. Original audio preview player updates
            if self._is_orig_playing and not self._is_orig_paused:
                dur = self.current_duration
                if self._orig_channel and not self._orig_channel.get_busy():
                    # Playback finished naturally
                    self._on_orig_stop()
                elif dur > 0 and not self._is_orig_scrubbing:
                    pos = self._get_orig_current_pos()
                    if pos >= dur - 0.05:
                        self._on_orig_stop()
                    else:
                        self.orig_scrub_slider.set(pos / dur)
                        self._update_orig_time_label(pos, dur)
        except Exception:
            pass
        finally:
            self._safe_after(40, self._start_vu_meter_timer)

    # --- ASYNCHRONOUS EXPORT HUB (ZERO UI HANG) ---
    def _get_export_format_params(self):
        selection = self.format_menu.get()
        if "24-bit" in selection:
            return "WAV", "24-bit", 320
        elif "16-bit" in selection:
            return "WAV", "16-bit", 320
        elif "FLAC" in selection:
            return "FLAC", "24-bit", 320
        else:
            return "MP3", "16-bit", 320

    def _on_save_single_stem(self, stem_id: str):
        if self.is_exporting:
            return
        data = self.separated_stems.get(stem_id)
        if data is None:
            messagebox.showinfo("No Data", "Separate track first before saving stems.")
            return

        fmt, bit_depth, bitrate = self._get_export_format_params()
        ext = fmt.lower()
        orig_name = Path(self.current_audio_path).stem if self.current_audio_path else "track"
        default_filename = f"{orig_name}_{stem_id}.{ext}"

        save_path = filedialog.asksaveasfilename(
            initialfile=default_filename,
            defaultextension=f".{ext}",
            filetypes=[(f"{fmt} Audio", f"*.{ext}")]
        )
        if not save_path:
            return

        self.status_lbl.configure(text=f"Exporting {stem_id} stem...")

        def worker():
            try:
                save_audio(
                    save_path, data, self.current_sr,
                    format_type=fmt, bit_depth=bit_depth, mp3_bitrate=bitrate,
                    normalize=self.norm_var.get()
                )
                self._safe_after(0, lambda: self.status_lbl.configure(
                    text=f"✅ Saved stem to: {Path(save_path).name}",
                    text_color=COLORS["accent_green"]
                ))
            except Exception as e:
                log_crash(type(e), e, e.__traceback__)
                self._safe_after(0, lambda: messagebox.showerror("Save Error", f"Failed to save stem:\n{e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_export_all_stems(self):
        if self.is_exporting or self.is_separating:
            return

        if not self.separated_stems:
            messagebox.showinfo("No Stems", "Separate an audio track first to export stems.")
            return

        orig_dir = str(Path(self.current_audio_path).parent) if self.current_audio_path else ""
        orig_name = Path(self.current_audio_path).stem if self.current_audio_path else "Track"
        target_dir = filedialog.askdirectory(
            initialdir=orig_dir,
            title="Select Folder to Export Stems"
        )
        if not target_dir:
            return

        out_folder = Path(target_dir) / f"{orig_name}_Stems"
        out_folder.mkdir(parents=True, exist_ok=True)

        fmt, bit_depth, bitrate = self._get_export_format_params()
        ext = fmt.lower()
        items = list(self.separated_stems.items())
        total = len(items)

        self.is_exporting = True
        self.exp_all_btn.configure(state="disabled")
        self.mixdown_btn.configure(state="disabled")
        self.progress_bar.set(0.0)

        def worker():
            try:
                for idx, (stem_id, data) in enumerate(items):
                    out_file = out_folder / f"{orig_name}_{stem_id}.{ext}"
                    pct = (idx + 1) / float(total)
                    self._safe_after(0, lambda p=pct, i=idx, sid=stem_id: (
                        self.progress_bar.set(p),
                        self.status_lbl.configure(
                            text=f"Exporting stem {i+1}/{total}: {sid.capitalize()} ({fmt})...",
                            text_color=COLORS["text_secondary"]
                        )
                    ))
                    save_audio(
                        str(out_file), data, self.current_sr,
                        format_type=fmt, bit_depth=bit_depth, mp3_bitrate=bitrate,
                        normalize=self.norm_var.get()
                    )

                self._safe_after(0, lambda: (
                    self.status_lbl.configure(
                        text=f"✅ All 9 stems exported successfully to {out_folder.name}!",
                        text_color=COLORS["accent_green"]
                    ),
                    self.progress_bar.set(1.0)
                ))
                if os.name == "nt":
                    subprocess.Popen(f'explorer "{out_folder}"')
            except Exception as e:
                log_crash(type(e), e, e.__traceback__)
                err_text = str(e)
                self._safe_after(0, lambda: messagebox.showerror("Export Error", f"Export failed:\n{err_text}"))
            finally:
                self._safe_after(0, self._reset_export_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _reset_export_ui(self):
        self.is_exporting = False
        self.exp_all_btn.configure(state="normal")
        self.mixdown_btn.configure(state="normal")

    def _on_export_custom_mixdown(self):
        if self.is_exporting or self.is_separating:
            return

        if not self.separated_stems:
            messagebox.showinfo("No Stems", "Separate an audio track first to export a mixdown.")
            return

        fmt, bit_depth, bitrate = self._get_export_format_params()
        ext = fmt.lower()
        orig_name = Path(self.current_audio_path).stem if self.current_audio_path else "Track"
        default_filename = f"{orig_name}_CustomMix.{ext}"

        save_path = filedialog.asksaveasfilename(
            initialfile=default_filename,
            defaultextension=f".{ext}",
            filetypes=[(f"{fmt} Audio", f"*.{ext}")]
        )
        if not save_path:
            return

        self.is_exporting = True
        self.exp_all_btn.configure(state="disabled")
        self.mixdown_btn.configure(state="disabled")
        self.status_lbl.configure(text="Rendering custom mixdown...")

        def worker():
            try:
                master_mix = self.player.render_mixdown()
                save_audio(
                    save_path, master_mix, self.current_sr,
                    format_type=fmt, bit_depth=bit_depth, mp3_bitrate=bitrate,
                    normalize=self.norm_var.get()
                )
                self._safe_after(0, lambda: self.status_lbl.configure(
                    text=f"✅ Custom mixdown exported to: {Path(save_path).name}",
                    text_color=COLORS["accent_green"]
                ))
            except Exception as e:
                log_crash(type(e), e, e.__traceback__)
                err_text = str(e)
                self._safe_after(0, lambda: messagebox.showerror("Mixdown Error", f"Failed to export mixdown:\n{err_text}"))
            finally:
                self._safe_after(0, self._reset_export_ui)

        threading.Thread(target=worker, daemon=True).start()


def main():
    app = ObsidianStemSplitterApp()
    if len(sys.argv) > 1:
        initial_file = sys.argv[1].strip().strip('"')
        if Path(initial_file).exists():
            app._safe_after(500, lambda: app._load_file_path(initial_file))
    app.mainloop()


if __name__ == "__main__":
    main()
