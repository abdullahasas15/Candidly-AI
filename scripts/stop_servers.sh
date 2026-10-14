#!/usr/bin/env bash

echo "=== Stopping Candidly AI Platform Services ==="

# Kill frontend on port 3000
FRONTEND_PIDS=$(lsof -i :3000 -t 2>/dev/null || true)
if [ -n "$FRONTEND_PIDS" ]; then
    echo "Killing frontend process(es): $FRONTEND_PIDS"
    kill -9 $FRONTEND_PIDS 2>/dev/null || true
fi

# Kill backend on port 8000
BACKEND_PIDS=$(lsof -i :8000 -t 2>/dev/null || true)
if [ -n "$BACKEND_PIDS" ]; then
    echo "Killing backend process(es): $BACKEND_PIDS"
    kill -9 $BACKEND_PIDS 2>/dev/null || true
fi

echo "=== All services stopped cleanly ==="
