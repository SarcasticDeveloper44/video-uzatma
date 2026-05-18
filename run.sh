#!/usr/bin/env bash
# Linux/macOS launcher — delegates to cross-platform run.py
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
    echo "HATA: python3 PATH'te bulunamadı." >&2
    exit 2
fi
exec "$PY" "$DIR/run.py" "$@"
