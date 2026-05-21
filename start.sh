#!/bin/bash
# Start both backend and frontend
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"

ROOT=/mnt/c/Users/phoeb/repo/PrivateAccountant

echo "Starting Ollama..."
ollama serve &

echo "Starting FastAPI backend..."
cd "$ROOT"
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000 &

echo "Starting Next.js frontend..."
cd "$ROOT/frontend"
npm run dev &

echo ""
echo "All services started:"
echo "  Frontend → http://localhost:3000"
echo "  Backend  → http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop all."
wait
