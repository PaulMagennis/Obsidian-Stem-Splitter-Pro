@echo off
title Build Obsidian Stem Splitter Pro Standalone Executable
cd /d "%~dp0"
echo Compiling Obsidian Stem Splitter Pro into Standalone Windows EXE...
python build_exe.py
pause
