@echo off
title Stem Splitter Pro - Launcher
cd /d "%~dp0"
echo Starting Stem Splitter Pro...
python stem_splitter_gui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
    pause
)
