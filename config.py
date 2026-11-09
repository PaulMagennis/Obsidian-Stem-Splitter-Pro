"""
Obsidian Stem Splitter Pro - Configuration & Settings
Defines stem categories, UI colors, audio defaults, and persistent configurations.
"""

import os
import json
from pathlib import Path

APP_NAME = "Obsidian Stem Splitter Pro"
APP_VERSION = "2.0.0"

# Target stems definition: (stem_id, display_name, icon, default_color)
STEM_DEFINITIONS = [
    ("vocals", "Vocals", "🎤", "#FF4B4B"),
    ("drums", "Drums", "🥁", "#FFA500"),
    ("guitar", "Guitar", "🎸", "#FFD700"),
    ("bass", "Bass", "🎸", "#00E676"),
    ("keyboard", "Keyboard & Synth", "🎹", "#00B0FF"),
    ("brass", "Brass", "🎺", "#7C4DFF"),
    ("woodwind", "Woodwind", "🎷", "#E040FB"),
    ("strings", "Stringed Instruments", "🎻", "#FF4081"),
    ("other", "Other / Ambience", "✨", "#78909C"),
]

STEM_MAP = {s[0]: s for s in STEM_DEFINITIONS}

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus",
    ".wma", ".aif", ".aiff", ".alac", ".ape", ".wv", ".mka", ".webm"
}

# Theme palette (Obsidian Dark Glass Studio with Neon Highlights)
COLORS = {
    "bg_darkest": "#0D0E11",
    "bg_dark": "#14161C",
    "bg_card": "#1E2028",
    "bg_card_hover": "#262933",
    "border": "#2E3240",
    "neon_orange": "#FF6600",
    "neon_green": "#00FF66",
    "border_highlight": "#00FF66",
    "accent_cyan": "#00FF66",     # Replaced blue/cyan with neon green
    "accent_purple": "#8A2BE2",
    "accent_green": "#00FF66",    # Vibrant neon green
    "accent_amber": "#FFB300",
    "accent_red": "#FF4444",
    "text_primary": "#FFFFFF",
    "text_secondary": "#A0A5B5",
    "text_muted": "#62677A",
}

SETTINGS_FILE = Path(os.environ.get("APPDATA", str(Path.home()))) / "ObsidianStemSplitterPro" / "settings.json"

DEFAULT_SETTINGS = {
    "export_format": "WAV (24-bit Lossless)",
    "wav_bit_depth": "24-bit",
    "mp3_bitrate": 320,
    "sample_rate": 44100,
    "normalize_stems": True,
    "peak_ceiling_db": -0.5,
    "use_gpu": True,
    "use_fp16": True,
    "chunk_overlap": 0.25,
    "output_folder": "",
    "active_stems": [s[0] for s in STEM_DEFINITIONS],
}

def load_settings():
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = DEFAULT_SETTINGS.copy()
                merged.update(data)
                return merged
    except Exception as e:
        print(f"Error loading settings: {e}")
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"Error saving settings: {e}")
