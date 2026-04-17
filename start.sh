#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/prog"

source "$SCRIPT_DIR/.venv/bin/activate"

cd "$PROJECT_DIR"
clear
python app.py
