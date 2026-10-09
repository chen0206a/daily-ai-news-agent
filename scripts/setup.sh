#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock
.venv/bin/python -m pip install --no-deps -e './backend[dev]'
test -f .env || cp .env.example .env
cd frontend
npm ci
npm run build
printf 'Configure .env, then start the backend and frontend using README commands.\n'
