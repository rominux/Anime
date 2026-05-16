#!/bin/bash
cd "$(dirname "$0")"
[ -d .venv ] && source .venv/bin/activate
python app.py
