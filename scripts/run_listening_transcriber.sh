#!/bin/zsh
set -euo pipefail

cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src
exec /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/.venv/bin/python \
  -m uvicorn web.listening_service:app --host 127.0.0.1 --port 9112
