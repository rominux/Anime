# Anime Manager

Gestionnaire d'animes avec téléchargement automatique, synchronisation AniList, planning des diffusions et lecteur intégré.

## Fonctionnalités

- **AniList Sync** — Import/export de la liste (Watching/Planning/Completed)
- **Téléchargements parallélisés** — File d'attente, extraction depuis AnimeHeaven, download multi-thread
- **Planning** — Calendrier des prochains épisodes filtré par votre liste
- **Suggestions** — Animés de la saison avec cache hors-ligne
- **Streaming local** — Lecteur vidéo custom (speed, skip, plein écran)
- **Mode hors-ligne** — Suggestions et planning mis en cache en SQLite

## Installation

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install -r requirements.txt
cp .env.example .env
```

Éditez `.env` avec votre token et nom d'utilisateur AniList.

## Utilisation

```bash
python app.py
# ou
./start.sh    # Linux/macOS
start.bat     # Windows
```

Ouvrez http://localhost:5000

## Configuration

Voir `.env.example` pour toutes les options disponibles.
