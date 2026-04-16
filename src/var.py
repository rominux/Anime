import os
import sys
import random
import logging
from dotenv import load_dotenv

load_dotenv()

def setup_logging(level=None):
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO").upper()

    log_level = getattr(logging, level, logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout
    )

    return logging.getLogger(__name__)


class SourceDomains:
    _SOURCES = {
        "sendvid": ("SendVid", ["sendvid.com"]),
        "dingtezuni": ("Dingtezuni", ["dingtezuni.com"]),
        "sibnet": ("Sibnet", ["video.sibnet.ru"]),
        "oneupload": ("OneUpload", ["oneupload.net", "oneupload.to"]),
        "vidmoly": ("Vidmoly", ["vidmoly.net", "vidmoly.to", "vidmoly.biz"]),
        "movearn": ("Movearnpre", ["movearnpre.com", "ovaltinecdn.com"]),
        "mivalyo": ("Mivalyo", ["mivalyo.com"]),
        "smooth": ("Smoothpre", ["smoothpre.com", "Smoothpre.com"]),
        "embed4me": ("Embed4me", ["embed4me.com", "embed4me"]),
    }

    ONEUPLOAD = _SOURCES["oneupload"][1]
    VIDMOLY = _SOURCES["vidmoly"][1]
    MOVARNPRE = _SOURCES["movearn"][1]

    PLAYERS = [d for _, domains in _SOURCES.values() for d in domains]

    DISPLAY_NAMES = {d: name for name, domains in _SOURCES.values() for d in domains}

    DOMAIN_MAP = {
        k: (val[1] if len(val[1]) > 1 else val[1][0])
        for k, val in _SOURCES.items()
    }


def get_anime_dir() -> str:
    anime_dir = os.environ.get("ANIME_DIR")
    if anime_dir:
        return anime_dir

    if os.name == "nt":
        return os.path.expanduser(r"C:\Users\Omain\Anime")
    elif _is_termux():
        return "/data/data/com.termux/files/home/storage/shared/Anime"
    else:
        return "/mnt/MySSD/Users/Omain/Anime/"


def _is_termux() -> bool:
    termux_paths = [
        "/data/data/com.termux",
        "/com.termux",
    ]
    return any(os.path.exists(p) for p in termux_paths) or os.environ.get("TERMUX_VERSION")


def get_anilist_token() -> str:
    token = os.environ.get("ANILIST_TOKEN")
    if token:
        return token

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    token_path = os.path.join(base_dir, "token")
    if os.path.exists(token_path):
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except (IOError, OSError):
            pass
    return ""


def get_domain() -> str:
    return os.environ.get("ANIME_SAMA_DOMAIN", "anime-sama.to")


def get_flask_host() -> str:
    return os.environ.get("FLASK_HOST", "0.0.0.0")


def get_flask_port() -> int:
    return int(os.environ.get("FLASK_PORT", "5000"))


def get_flask_debug() -> bool:
    return os.environ.get("FLASK_DEBUG", "false").lower() == "true"


def get_cloudflare_mode() -> str:
    return os.environ.get("CLOUDFLARE_MODE", "cloudscraper")


def get_max_concurrent_downloads() -> int:
    return int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", "3"))


def generate_requests_headers(cf_clearance: str, user_agent: str = None) -> dict:
    if user_agent is None:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.8",
        "Referer": "https://anime-sama.si/",
        "Origin": "https://anime-sama.si",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    if cf_clearance and cf_clearance != "None":
        headers["Cookie"] = f"cf_clearance={cf_clearance}"

    return headers


class Colors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def print_header():
    header = f"""
{Colors.HEADER}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║                 ANIME-SAMA VIDEO DOWNLOADER                  ║
╚══════════════════════════════════════════════════════════════╝
{Colors.ENDC}
{Colors.OKCYAN}📺 Download anime episodes from anime-sama.fr easily!{Colors.ENDC}
"""
    print(header)


def print_tutorial():
    tutorial = f"""
{Colors.BOLD}{Colors.HEADER}🎓 COMPLETE TUTORIAL - HOW TO USE{Colors.ENDC}
{Colors.BOLD}{'='*65}{Colors.ENDC}

{Colors.OKGREEN}{Colors.BOLD}Step 1: Find Your Anime on Anime-Sama{Colors.ENDC}
├─ 🌐 Visit: {Colors.OKCYAN}https://anime-sama.fr/catalogue/{Colors.ENDC}
├─ 🔍 Search for your desired anime (e.g., "Roshidere")
├─ 📺 Click on the anime title to view seasons
└─ 📂 Navigate to your preferred season and language

{Colors.OKGREEN}{Colors.BOLD}Step 2: Get the Complete URL{Colors.ENDC}
├─ 🎯 Choose your preferred option:
│   ├─ Season (saison1, saison2, etc.)
│   └─ Language (vostfr, vf, etc.)
├─ 📋 Copy the FULL URL from browser address bar
└─ ✅ Example URL format:
    {Colors.OKCYAN}https://anime-sama.fr/catalogue/roshidere/saison1/vostfr/{Colors.ENDC}

{Colors.OKGREEN}{Colors.BOLD}Step 3: Run This Program{Colors.ENDC}
├─ 🚀 Start the downloader
├─ 📝 Paste the complete URL when prompted
├─ ⚡ Program will automatically fetch available episodes
└─ 🎮 Follow the interactive prompts

{Colors.WARNING}{Colors.BOLD}📌 IMPORTANT NOTES:{Colors.ENDC}
├─ ✅ Supported sources: See inside of the github README
├─ ❌ Other sources are not supported (see GitHub for details)
├─ 🔗 URL must be the complete path including season/language
└─ 📁 Videos save to ./videos/ by default (customizable)

{Colors.OKGREEN}{Colors.BOLD}🎯 Example URLs that work:{Colors.ENDC}
├─ https://anime-sama.fr/catalogue/roshidere/saison1/vostfr/
├─ https://anime-sama.fr/catalogue/demon-slayer/saison1/vf/
├─ https://anime-sama.fr/catalogue/attack-on-titan/saison3/vostfr/
├─ https://anime-sama.fr/catalogue/one-piece/saison1/vostfr/

{Colors.BOLD}{'='*65}{Colors.ENDC}
"""
    print(tutorial)


def print_separator(char: str = "─", length: int = 65):
    print(f"{Colors.OKBLUE}{char * length}{Colors.ENDC}")


def print_status(message: str, status_type: str = "info"):
    icons = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
        "loading": "⏳",
    }
    colors = {
        "info": Colors.OKBLUE,
        "success": Colors.OKGREEN,
        "warning": Colors.WARNING,
        "error": Colors.FAIL,
        "loading": Colors.OKCYAN,
    }

    icon = icons.get(status_type, "ℹ️")
    color = colors.get(status_type, Colors.OKBLUE)
    print(f"{color}{icon} {message}{Colors.ENDC}")
