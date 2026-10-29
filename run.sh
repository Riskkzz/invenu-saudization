#!/usr/bin/env bash
# INVENU — امتثال التوطين: التشغيل على macOS / Linux (يعمل على جهازك فقط، بدون إنترنت بعد أول تشغيل)
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.9+ is required: https://www.python.org/downloads/"
  echo "يتطلب Python 3.9 أو أحدث."
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Python 3.9+ is required (found $(python3 --version 2>&1)): https://www.python.org/downloads/"
  echo "يتطلب Python 3.9 أو أحدث."
  exit 1
fi
if [ ! -f .venv/installed.ok ]; then
  echo "[1/2] First run: preparing local environment (one time, needs internet)..."
  [ -d .venv ] || python3 -m venv .venv
  . .venv/bin/activate
  python -m pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
  touch .venv/installed.ok
else
  . .venv/bin/activate
fi
echo "[2/2] Starting INVENU Saudization tool..."
exec python run.py "$@"
