#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

echo "=== Starting Candidly AI Platform Services ==="

# 1. Start Backend (FastAPI / Uvicorn)
if lsof -i :8000 -t >/dev/null 2>&1; then
    echo "Backend already running on port 8000 (PID $(lsof -i :8000 -t | head -n 1))"
else
    echo "Starting Uvicorn backend on port 8000..."
    nohup "$DIR/.venv/bin/uvicorn" backend.app.main:app --host 0.0.0.0 --port 8000 --reload </dev/null >/dev/null 2>&1 &
    sleep 2
    echo "Backend started."
fi

# 2. Start Frontend (Vite)
if lsof -i :3000 -t >/dev/null 2>&1; then
    echo "Frontend already running on port 3000 (PID $(lsof -i :3000 -t | head -n 1))"
else
    echo "Starting Vite frontend on port 3000..."
    cd "$DIR/frontend"
    nohup npm run dev </dev/null >/dev/null 2>&1 &
    sleep 2
    echo "Frontend started."
fi

echo "=== All services online at http://localhost:3000 ==="
