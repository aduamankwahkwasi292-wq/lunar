@echo off
setlocal
echo ==========================================
echo   Lunar AI - Local Setup ^& Start
echo   (on-device LLM + voice, no API keys)
echo ==========================================
echo.

echo [1/4] Installing Python dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to install dependencies.
    echo Make sure Python and pip are installed and in your PATH.
    pause
    exit /b 1
)

echo.
echo [2/4] Checking Ollama (local AI engine)...
where ollama >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Ollama is not installed.
    echo Install it from https://ollama.com/download then re-run this script.
    pause
    exit /b 1
)
REM Start the Ollama server in the background if it isn't already running
start "" /b ollama serve >nul 2>nul
echo Pulling local models if needed (first run may take a few minutes)...
ollama pull qwen2.5:1.5b
ollama pull nomic-embed-text

echo.
echo [3/4] Setting up local voice models (Piper TTS + Whisper STT)...
python backend\setup_models.py

echo.
echo [4/4] Starting Lunar AI server...
echo.
echo Open your browser and go to: http://localhost:8000
echo Press Ctrl+C to stop the server.
echo.

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir backend
