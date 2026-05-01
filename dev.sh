#!/bin/bash
# Inicia backend e frontend juntos. Ctrl+C encerra os dois.
set -e
trap "kill 0" EXIT SIGINT SIGTERM

echo "▶ Backend  → http://localhost:8000"
echo "▶ Frontend → http://localhost:5173"
echo ""

.venv/bin/uvicorn numis_geek.api.app:app --reload --port 8000 &
npm run dev --prefix frontend &

wait
