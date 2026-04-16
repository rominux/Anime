#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/prog"

source "$SCRIPT_DIR/.venv/bin/activate"

cd "$PROJECT_DIR"
clear
firefox http://127.0.0.1:5000 & 2>/dev/null
python app.py