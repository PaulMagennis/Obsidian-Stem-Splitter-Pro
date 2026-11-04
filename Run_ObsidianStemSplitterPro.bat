@echo off
title Obsidian Stem Splitter Pro - Launcher
cd /d "%~dp0"
echo Starting Obsidian Stem Splitter Pro...
if exist "dist\ObsidianStemSplitterPro\ObsidianStemSplitterPro.exe" (
    start "" "dist\ObsidianStemSplitterPro\ObsidianStemSplitterPro.exe"
) else (
    python obsidian_stem_splitter_pro.py
)
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with code %ERRORLEVEL%.
    pause
)
