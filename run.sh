#!/usr/bin/env bash
# Starts cyber-news-agregate at http://127.0.0.1:8740 (builds the page first when
# its source is newer than the last build). Stop it with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
if [ ! -d frontend/dist ] || [ -n "$(find frontend/src frontend/index.html -newer frontend/dist -print -quit)" ]; then
  # nvm puts npm on the PATH of a terminal only: find it for a service too.
  if ! command -v npm >/dev/null && [ -s "$HOME/.nvm/nvm.sh" ]; then
    set +eu  # nvm is not written for strict mode
    . "$HOME/.nvm/nvm.sh" >/dev/null
    set -eu
  fi
  if command -v npm >/dev/null; then
    (cd frontend && { [ -d node_modules ] || npm install --no-fund --no-audit; } && npm run build)
  elif [ -d frontend/dist ]; then
    echo "npm not found: serving the page as last built" >&2
  else
    echo "npm not found and the page was never built: install Node, then run this again" >&2
    exit 1
  fi
fi
cd backend
exec uv run uvicorn radar.app:app --host 127.0.0.1 --port "${PORT:-8740}"
