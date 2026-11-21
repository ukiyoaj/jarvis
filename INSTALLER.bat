@echo off
chcp 65001 > nul 2>&1
title JARVIS COMPLETE v4.0 - Installation
color 0A
cls

echo.
echo  ================================================
echo   JARVIS COMPLETE v4.0 - ASUS TUF GAMING
echo   Installation automatique
echo  ================================================
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  Relancement en Administrateur...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

echo  [1/7] Verification de Python...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo  ERREUR: Python non trouve !
    echo  Telechargez Python sur : https://www.python.org/downloads/
    echo  IMPORTANT: Cochez "Add Python to PATH" pendant l installation !
    start https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version
echo  OK - Python detecte.
echo.

echo  [2/7] Mise a jour pip...
python -m pip install --upgrade pip -q
echo  OK
echo.

echo  [3/7] Installation des dependances...
pip install speechrecognition pyttsx3 requests keyboard psutil pillow pyautogui colorama numpy -q
pip install pygetwindow schedule deep-translator pygame opencv-python google-generativeai -q
pip install pywin32 mediapipe -q
pip install pyaudio -q 2>nul || echo  INFO: PyAudio - voir README si probleme
echo  OK - Dependances installees.
echo.

echo  [4/7] Ollama - IA locale RTX 4070...
winget install Ollama.Ollama -s winget --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
if %errorlevel% equ 0 (
    echo  OK - Ollama installe. LLaMA 3 en telechargement...
    start /min cmd /c "ollama pull llama3"
) else (
    echo  INFO: Installez Ollama manuellement sur https://ollama.ai
)
echo.

echo  [5/7] Configuration...
powershell -Command "(Get-Content '%~dp0config.json') -replace 'VOTRE_NOM', '%USERNAME%' | Set-Content '%~dp0config.json'"
echo  OK - Configure pour: %USERNAME%
echo.

echo  [6/7] Raccourci Bureau...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\JARVIS COMPLETE.lnk'); $s.TargetPath = 'python'; $s.Arguments = '\"%~dp0jarvis.py\"'; $s.WorkingDirectory = '%~dp0'; $s.Save()"
echo  OK - Raccourci cree.
echo.

echo  [7/7] Configuration des cles API
echo  ================================================
echo.
echo  GEMINI PRO (votre abonnement illimite):
echo  Site: https://aistudio.google.com
echo.
set /p GEMINI_PRO=  Cle Gemini PRO (Entree pour passer): 
echo.
echo  GRATUITS:
echo  Groq:    https://console.groq.com
echo  Mistral: https://console.mistral.ai
echo.
set /p GROQ=  Cle Groq (Entree pour passer): 
set /p MISTRAL=  Cle Mistral (Entree pour passer): 
set /p GEMINI=  Cle Gemini Free (Entree pour passer): 
echo.
echo  VOIX ElevenLabs (gratuit 10000 chars/mois):
echo  Site: https://elevenlabs.io
echo.
set /p ELEVENLABS=  Cle ElevenLabs (Entree pour passer): 

if not "%GEMINI_PRO%"=="" powershell -Command "(Get-Content '%~dp0config.json') -replace 'YOUR_GEMINI_PRO_KEY', '%GEMINI_PRO%' | Set-Content '%~dp0config.json'"
if not "%GROQ%"=="" powershell -Command "(Get-Content '%~dp0config.json') -replace 'YOUR_GROQ_KEY', '%GROQ%' | Set-Content '%~dp0config.json'"
if not "%MISTRAL%"=="" powershell -Command "(Get-Content '%~dp0config.json') -replace 'YOUR_MISTRAL_KEY', '%MISTRAL%' | Set-Content '%~dp0config.json'"
if not "%GEMINI%"=="" powershell -Command "(Get-Content '%~dp0config.json') -replace 'YOUR_GEMINI_KEY', '%GEMINI%' | Set-Content '%~dp0config.json'"
if not "%ELEVENLABS%"=="" powershell -Command "(Get-Content '%~dp0config.json') -replace 'YOUR_ELEVENLABS_KEY', '%ELEVENLABS%' | Set-Content '%~dp0config.json'"

echo.
echo  ================================================
echo   INSTALLATION TERMINEE !
echo  ================================================
echo.
echo  LANCER: Double-clic JARVIS COMPLETE sur le Bureau
echo  ACTIVER: Dites Jarvis ou Ctrl+Shift+J
echo.
echo  N oubliez pas d ajouter dans config.json:
echo  - gmail_address et gmail_app_password
echo  - instagram_username et instagram_password
echo.
set /p GO=  Lancer JARVIS maintenant ? (O/N):
if /i "%GO%"=="O" start python "%~dp0jarvis.py"
echo.
pause
