#!/usr/bin/env bash
# Start the API server on port 8000 in the background. Logs go to .server.log.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .server.pid ]] && kill -0 "$(cat .server.pid)" 2>/dev/null; then
  echo "server already running (pid $(cat .server.pid))"
  exit 0
fi

nohup uv run uvicorn app.main:app --port 8000 > .server.log 2>&1 &
echo $! > .server.pid

for _ in {1..30}; do
  if curl -s -o /dev/null localhost:8000/docs; then
    echo "server up on :8000 (pid $(cat .server.pid), log .server.log)"
    exit 0
  fi
  sleep 1
done
echo "server did not come up in 30s; see .server.log" >&2
exit 1
