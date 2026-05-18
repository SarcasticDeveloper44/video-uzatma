#!/usr/bin/env bash
# macOS launcher — double-clickable from Finder (Finder opens .command files
# in Terminal). For Linux/macOS terminal use, run.sh works the same.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
    echo "HATA: python3 PATH'te bulunamadı."
    echo "macOS için: brew install python3   (veya https://www.python.org)"
    read -p "Devam etmek için Enter'a bas..."
    exit 2
fi
exec "$PY" "$DIR/run.py" "$@"
