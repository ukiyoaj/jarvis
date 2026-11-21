@echo off
title JARVIS - Desactiver le demarrage automatique
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v JARVIS /f >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\JARVIS.lnk" 2>nul
echo.
echo  [OK] JARVIS ne se lancera plus au demarrage de Windows.
echo.
pause
