#!/bin/bash
echo "=========================================="
echo "  Lunar AI - Local Setup & Start"
echo "  (on-device LLM + voice, no API keys)"
echo "=========================================="
echo ""

echo "[1/4] Installing Python dependencies..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Failed to install dependencies."
    echo "Make sure Python and pip are installed."
    exit 1
fi

echo ""
echo "[2/4] Checking Ollama (local AI engine)..."
if ! command -v ollama >/dev/null 2>&1; then
    echo ""
    echo "ERROR: Ollama is not installed."
    echo "Install it from https://ollama.com/download then re-run this script."
    exit 1
fi
# Start the Ollama server in the background if it isn't already running
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    ollama serve >/dev/null 2>&1 &
    sleep 2
fi
echo "Pulling local models if needed (first run may take a few minutes)..."
ollama pull qwen2.5:1.5b
ollama pull nomic-embed-text

echo ""
echo "[3/4] Setting up local voice models (Piper TTS + Whisper STT)..."
python backend/setup_models.py

echo ""
echo "[4/4] Starting Lunar AI server..."
echo ""
echo "Open your browser and go to: http://localhost:8000"
echo "Press Ctrl+C to stop the server."
echo ""

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
