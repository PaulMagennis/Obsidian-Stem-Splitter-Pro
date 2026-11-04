@echo off
title Push Obsidian Stem Splitter Pro to GitHub
echo ============================================================
echo   OBSIDIAN STEM SPLITTER PRO - PUSH TO GITHUB
echo ============================================================
echo.
cd /d "%~dp0"
echo Pushing branch 'main' to origin...
echo (If prompted, click 'Sign in with your browser' to authenticate)
echo.
"C:\Program Files\Git\cmd\git.exe" push -u origin main
echo.
if %ERRORLEVEL% EQU 0 (
    echo ============================================================
    echo SUCCESS! Repository pushed to GitHub!
    echo ============================================================
) else (
    echo ============================================================
    echo Notice: If push failed, ensure:
    echo 1. You created the repository on GitHub:
    echo    https://github.com/new
    echo    Repository name: Obsidian-Stem-Splitter-Pro
    echo 2. You have permission to push to https://github.com/PaulMagennis/Obsidian-Stem-Splitter-Pro
    echo ============================================================
)
echo.
pause
