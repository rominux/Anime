# AnimeProgTest

An anime management system with web interface for watching, downloading, and tracking anime progress via AniList integration.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Configuration](#configuration)
- [Core Files](#core-files)
- [Web Templates](#web-templates)
- [API Routes](#api-routes)
- [Usage](#usage)
- [Architecture](#architecture)

---

## Overview

This project combines two systems:

1. **Web Interface** (Flask): Browse anime from your AniList, manage downloads, watch episodes in-browser
2. **CLI Downloader** (src/): Download anime from Anime-Sama or AnimeHeaven

The system supports:
- English anime via AnimeHeaven (web interface)
- French anime via Anime-Sama (web interface + CLI)
- AniList integration for progress tracking
- Streaming downloaded episodes in the browser
- Multi-language (EN/FR) interfaces

---

## Features

### New in v2.0

- **Real-time Download Tracker**: Top-bar SSE-powered download progress display (auto-hides when idle)
- **Enhanced Video Player**: HTML5 player with playback speed controls (0.5x - 2x)
- **Unified Download Manager**: Thread-safe queue-based download system
- **Automated Cloudflare Bypass**: cloudscraper integration (no manual cookie entry)
- **Environment-based Configuration**: All settings via `.env` file
- **Improved Error Handling**: Proper exception logging instead of silent failures

### Core Features

- In-browser video streaming with HTTP Range support (seekable videos)
- Bulk download/delete operations
- AniList progress sync
- Episode status tracking (watched, downloaded, available, unreleased)
- Keyboard shortcuts for video player
- Auto-advance to next episode
- Seasonal anime suggestions

---

## Project Structure

```
AnimeProgTest/
├── app.py                 # Flask web server & API routes
├── logic.py               # AniList API + AnimeHeaven scraper
├── logic_fr.py            # Anime-Sama integration
├── download_manager.py    # Unified thread-safe download manager
├── requirements.txt       # Python dependencies
├── .env                   # Environment configuration
├── .env.example           # Environment template
├── templates/             # Jinja2 HTML templates
│   ├── home.html         # Portal/landing page
│   ├── index.html        # English interface
│   ├── fr_index.html     # French interface
│   ├── anilist_index.html# AniList management
│   └── watch.html        # In-browser video player
├── src/                  # CLI downloader
│   ├── main.py           # CLI entry point
│   ├── var.py            # Configuration & constants
│   └── utils/
│       ├── cloudflare/  # Cloudflare bypass
│       └── ...          # Other utilities
├── start.sh              # Linux startup script
└── start.bat             # Windows startup script
```

---

## Installation

### 1. Clone and Setup Virtual Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Linux/Mac:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Install FFmpeg

**Linux:**
```bash
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
Download from https://ffmpeg.org/download.html and add to PATH.

### 3. Configure Environment

Copy the example environment file and edit:

```bash
cp .env.example .env
```

Edit `.env` with your settings:
```env
ANIME_DIR=C:\Users\YourName\Anime
ANILIST_TOKEN=your_token_here
ANILIST_USERNAME=YourUsername
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
CLOUDFLARE_MODE=cloudscraper
```

### 4. Get AniList Token (Optional)

1. Go to https://anilist.co/settings/developer
2. Create a new personal access token
3. Add it to `.env` as `ANILIST_TOKEN`

---

## Configuration

### Environment Variables (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| `ANIME_DIR` | Directory for downloaded anime | Platform-specific |
| `ANILIST_TOKEN` | AniList API token | Empty |
| `ANILIST_USERNAME` | AniList username | Pate0Sucre |
| `FLASK_HOST` | Web server host | 0.0.0.0 |
| `FLASK_PORT` | Web server port | 5000 |
| `FLASK_DEBUG` | Enable debug mode | false |
| `MAX_CONCURRENT_DOWNLOADS` | Max parallel downloads | 3 |
| `CLOUDFLARE_MODE` | Cloudflare bypass: `cloudscraper`, `selenium`, `manual` | cloudscraper |
| `LOG_LEVEL` | Logging level | INFO |

---

## Core Files

### download_manager.py - Unified Download Manager

Thread-safe singleton class managing all downloads:

```python
from download_manager import get_download_manager, DownloadTask, DownloadSource

manager = get_download_manager()

# Add English download
task = DownloadTask(
    anime_data={"nom_dossier": "...", "nom_complet": "..."},
    episodes=[1, 2, 3],
    source=DownloadSource.ENGLISH
)
manager.add_task(task)

# Get status
status = manager.get_status()
# {
#   "phase": "DOWNLOAD",
#   "active_downloads": [...],
#   "search_queue_size": 0,
#   "download_queue_size": 1
# }
```

**Features:**
- `queue.Queue` for thread-safe operations
- SSE notifications for real-time UI updates
- Progress tracking per episode
- Automatic worker thread management

### app.py - Web Server

**Key Routes:**

| Route | Purpose |
|-------|---------|
| `/api/downloads/stream` | SSE endpoint for real-time download status |
| `/api/downloads/status` | JSON endpoint for download status |
| `/watch/<nom>/<ep>` | Video player page |
| `/api/watch/stream/<nom>/<ep>` | Video streaming with Range support |

### logic.py - English/AniList Logic

Handles AniList API integration and AnimeHeaven scraping.

### logic_fr.py - French/Anime-Sama Logic

Handles Anime-Sama integration with cloudscraper support.

---

## Web Templates

### index.html - English Interface

**New Features:**
- Real-time download tracker (top bar, SSE-powered)
- Auto-hides when no active downloads
- Shows progress percentage and source badge (EN/FR)
- Episode status updates via download manager

### watch.html - Video Player

**New Features:**
- Playback speed controls: 0.5x, 0.75x, 1x, 1.25x, 1.5x, 1.75x, 2x
- Volume slider
- 10-second skip buttons
- Progress bar with buffered indicator
- Number keys (1-9) for quick seek to percentage
- Responsive design

**Keyboard Shortcuts:**
| Key | Action |
|-----|--------|
| Space/K | Play/Pause |
| Left Arrow | -10 seconds |
| Right Arrow | +10 seconds |
| Up Arrow | Volume +10% |
| Down Arrow | Volume -10% |
| M | Toggle mute |
| F | Toggle fullscreen |
| Escape | Exit fullscreen / Go back |
| 1-9 | Seek to 10%-90% |

---

## API Routes

### Download Status

**GET /api/downloads/status**
```json
{
  "phase": "DOWNLOAD",
  "current_search": "My Hero Academia",
  "current_download": "One Piece",
  "search_queue_size": 2,
  "download_queue_size": 3,
  "active_downloads": [
    {
      "key": "One_Piece_100",
      "anime_name": "One Piece",
      "episode": 100,
      "progress": 45.5,
      "source": "english"
    }
  ]
}
```

**GET /api/downloads/stream** (SSE)
```
data: {"phase": "DOWNLOAD", "active_downloads": [...]}

```

---

## Usage

### Starting the Web Server

```bash
# Activate virtual environment
source .venv/bin/activate

# Run
python app.py
```

Server starts at `http://localhost:5000`

### CLI Downloader

```bash
python -m src.main --url "https://anime-sama.fr/.../saison1/vostfr/" --episodes "1,2,3"
python -m src.main --search "One Piece" --latest
```

---

## Architecture

### Thread Safety

The `DownloadManager` class uses:
- `queue.Queue` for work queues
- `threading.Lock` for shared state
- Observer pattern with SSE for UI updates

### Cloudflare Bypass

Three modes available via `CLOUDFLARE_MODE`:

1. **cloudscraper** (default): Uses cloudscraper library
2. **selenium**: Uses undetected-chromedriver (requires Chrome)
3. **manual**: Requires manual cookie entry

### Video Streaming

Flask streaming with HTTP Range headers:
- Partial content responses (206)
- Supports seeking in HTML5 video
- Chunked transfer encoding
- CORS headers for cross-origin access

---

## Dependencies

**Python Packages:**
- `Flask>=3.0.0` - Web framework
- `requests>=2.31.0` - HTTP client
- `beautifulsoup4>=4.12.0` - HTML parsing
- `cloudscraper>=1.2.71` - Cloudflare bypass
- `tqdm>=4.66.0` - Progress bars
- `python-dotenv>=1.0.0` - Environment variables
- `colorama>=0.4.6` - Colored CLI output

**External Tools:**
- `ffmpeg` - Video conversion (required for M3U8 downloads)

---

## Troubleshooting

### Video not playing

Ensure FFmpeg is installed and in PATH:
```bash
ffmpeg -version
```

### Downloads failing with 403

Cloudflare bypass may be needed. Set in `.env`:
```env
CLOUDFLARE_MODE=cloudscraper
```

### AniList sync not working

Check your `ANILIST_TOKEN` in `.env` is valid.

---

## License

This project uses code from Anime-Sama Downloader (https://github.com/sertrafurr/Anime-Sama-Downloader)
