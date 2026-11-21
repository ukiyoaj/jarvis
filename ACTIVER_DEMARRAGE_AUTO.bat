@echo off
title JARVIS - Activer le demarrage automatique
cd /d "%~dp0"
echo [%date% %time%] Activation >> demarrage.log
rem Supprime l'ancien raccourci (evite un double lancement)
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\JARVIS.lnk" 2>nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v JARVIS /t REG_SZ /d "cmd.exe /c start \"JARVIS\" /min \"%~dp0LANCER_JARVIS.bat\"" /f >> demarrage.log 2>&1
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v JARVIS >> demarrage.log 2>&1
if errorlevel 1 (
  echo  [ERREUR] Activation ratee. Regarde demarrage.log
) else (
  echo.
  echo  [OK] JARVIS se lancera tout seul a chaque demarrage de Windows.
)
echo.
pause
