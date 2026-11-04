@echo off
title Build StemSplitterPro Standalone Executable
cd /d "%~dp0"
echo Compiling StemSplitterPro into Standalone Windows EXE...
python build_exe.py
pause
