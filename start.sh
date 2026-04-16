#!/bin/bash
source /home/omain/Projets/AnimeProgTest/.venv/bin/activate
/home/omain/Projets/AnimeProgTest
clear
firefox http://127.0.0.1:5000 & 2>/dev/null
python3 /home/omain/Projets/AnimeProgTest/app.py
