@echo off
title JARVIS
cd /d "%~dp0"
echo [%date% %time%] Lancement demande >> demarrage.log
rem Attend qu'Internet reponde (20 s maximum), au lieu de 20 s fixes
set /a essais=0
:attente
ping -n 1 -w 1000 8.8.8.8 >nul 2>&1
if not errorlevel 1 goto pret
set /a essais+=1
if %essais% geq 20 goto pret
timeout /t 1 /nobreak >nul
goto attente
:pret
echo [%date% %time%] Reseau pret apres %essais% essai(s) >> demarrage.log
where python >nul 2>&1
if errorlevel 1 (
  echo [%date% %time%] ERREUR: python introuvable >> demarrage.log
  echo Python est introuvable. Regarde demarrage.log
  pause
  exit /b
)
echo [%date% %time%] Lancement de jarvis.py >> demarrage.log
python jarvis.py
echo [%date% %time%] jarvis.py s'est arrete (code %errorlevel%) >> demarrage.log
if errorlevel 1 pause
