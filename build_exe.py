"""
Obsidian Stem Splitter Pro - PyInstaller Build Script
Compiles Obsidian Stem Splitter Pro into a standalone Windows executable.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

def build():
    proj_dir = Path(__file__).resolve().parent
    os.chdir(proj_dir)

    print("=" * 60)
    print("   OBSIDIAN STEM SPLITTER PRO - COMPILING STANDALONE EXE")
    print("=" * 60)

    # Clean previous build artifacts
    for d in ["build", "dist"]:
        p = proj_dir / d
        if p.exists():
            print(f"Cleaning {d}/ directory...")
            try:
                shutil.rmtree(p)
            except Exception as e:
                print(f"Notice: {e}")

    spec_file = proj_dir / "ObsidianStemSplitterPro.spec"

    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        str(spec_file)
    ]

    print(f"Executing: {' '.join(cmd)}")
    res = subprocess.run(cmd)

    if res.returncode == 0:
        dist_dir = proj_dir / "dist" / "ObsidianStemSplitterPro"
        exe_path = dist_dir / "ObsidianStemSplitterPro.exe"
        
        # Ensure ffmpeg and ffprobe are present in dist directory
        static_bin_dir = Path(sys.executable).parent / "Lib" / "site-packages" / "static_ffmpeg" / "bin" / "win32"
        for bin_name in ["ffmpeg.exe", "ffprobe.exe"]:
            target = dist_dir / bin_name
            if not target.exists():
                src = static_bin_dir / bin_name
                if src.exists():
                    shutil.copy2(src, target)
                    print(f"Copied {bin_name} to {dist_dir}")

        # Ensure assets are copied to dist directory
        assets_src = proj_dir / "assets"
        assets_dst = dist_dir / "assets"
        if assets_src.exists():
            shutil.copytree(assets_src, assets_dst, dirs_exist_ok=True)
            print(f"Copied assets to {assets_dst}")

        if exe_path.exists():
            print("\n" + "=" * 60)
            print("BUILD SUCCESSFUL!")
            print(f"Standalone Executable: {exe_path}")
            print(f"Executable Size: {exe_path.stat().st_size / (1024*1024):.2f} MB")
            print("=" * 60)
        else:
            print("\nBuild finished. Check dist/ directory.")
    else:
        print(f"\nBuild failed with return code {res.returncode}")

if __name__ == "__main__":
    build()
