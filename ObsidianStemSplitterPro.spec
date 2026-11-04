# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = [
    'unittest',
    'numpy.testing',
    'scipy.signal',
    'scipy.special',
    'scipy.spatial',
    'soundfile',
    'librosa',
    'pygame',
    'demucs',
    'torch',
    'torchaudio',
    'config',
    'audio_engine',
    'stem_player',
    'obsidian_stem_splitter_pro',
]

# Explicitly bundle self-contained FFmpeg and FFprobe binaries
static_ffmpeg_dir = r"C:\Users\PaulMagennisTCNS\AppData\Local\Programs\Python\Python312\Lib\site-packages\static_ffmpeg\bin\win32"
ff_exe = os.path.join(static_ffmpeg_dir, "ffmpeg.exe")
fp_exe = os.path.join(static_ffmpeg_dir, "ffprobe.exe")
if os.path.exists(ff_exe):
    binaries.append((ff_exe, "."))
if os.path.exists(fp_exe):
    binaries.append((fp_exe, "."))

# Collect third party packages & assets
for pkg in ['customtkinter', 'tkinterdnd2', 'static_ffmpeg', 'yt_dlp', 'pygame', 'soundfile', 'demucs', 'librosa']:
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception as e:
        print(f"Notice collecting {pkg}: {e}")

# Bundle application assets (logo, animated DAW spectrum GIF)
assets_src = os.path.join(os.path.abspath('.'), 'assets')
if os.path.exists(assets_src):
    datas.append((assets_src, 'assets'))

a = Analysis(
    ['obsidian_stem_splitter_pro.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],  # Never exclude unittest or standard modules needed by numpy/scipy!
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ObsidianStemSplitterPro',
    icon='assets/app_icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Safe clean directory patch to prevent WinError 32 if Windows Explorer is open
import PyInstaller.building.utils
import PyInstaller.building.api
import os, shutil

def safe_make_clean_directory(path):
    if os.path.exists(path):
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)
                else:
                    os.unlink(item_path)
            except Exception:
                pass
    else:
        os.makedirs(path, exist_ok=True)

PyInstaller.building.utils._make_clean_directory = safe_make_clean_directory
PyInstaller.building.api._make_clean_directory = safe_make_clean_directory

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ObsidianStemSplitterPro',
)
