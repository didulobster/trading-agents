#!/usr/bin/env bash
# Stop the API server started by server-start.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .server.pid ]]; then
  echo "no .server.pid; server not started by server-start.sh"
  exit 0
fi

pid=$(cat .server.pid)
pkill -TERM -P "$pid" 2>/dev/null || true
kill -TERM "$pid" 2>/dev/null || true
rm .server.pid
echo "server stopped (pid $pid)"
