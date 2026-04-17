import os
import logging
import subprocess
from typing import Dict, List

try:
    import requests_cache
    requests_cache.install_cache('anime_scraper_cache', expire_after=3600)
except ImportError:
    pass

from dotenv import load_dotenv
from src.var import get_anime_dir

load_dotenv()

logger = logging.getLogger(__name__)

ANIME_DIR = get_anime_dir()
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def search_anime_sama(query: str) -> List[Dict]:
    from src.utils.search.search_anime import search_anime

    try:
        results = search_anime(query, headers=HEADERS)
        return [r for r in results if r.get('support') != "Unsupported"]
    except Exception as e:
        logger.error(f"Anime-Sama search failed: {e}")
        return []


def get_anime_sama_details(base_url: str) -> Dict:
    from src.utils.search.expand_catalogue import expand_catalogue_url
    from src.utils.fetch.fetch_episodes import fetch_episodes

    try:
        seasons = expand_catalogue_url(base_url, headers=HEADERS)
    except Exception as e:
        logger.error(f"Failed to expand catalogue URL: {e}")
        seasons = []

    active_url = base_url

    if seasons and not ("vostfr" in base_url.lower() or "vf" in base_url.lower()):
        active_url = seasons[0]['url']

    try:
        episodes_data = fetch_episodes(active_url, headers=HEADERS)
    except Exception as e:
        logger.error(f"Failed to fetch episodes: {e}")
        episodes_data = {}

    if not episodes_data:
        return {"seasons": seasons, "episodes": [], "active_url": active_url}

    player_choice = list(episodes_data.keys())[0]
    ep_urls = episodes_data[player_choice]

    episodes = []
    for i, url in enumerate(ep_urls, 1):
        episodes.append({"ep": i, "url": url, "status": "released"})

    return {"seasons": seasons, "episodes": episodes, "active_url": active_url}


def add_to_queue_fr(nom_dossier: str, episodes_urls: Dict) -> None:
    from download_manager import get_download_manager, DownloadTask, DownloadSource

    dest_dir = os.path.join(ANIME_DIR, nom_dossier)
    os.makedirs(dest_dir, exist_ok=True)

    task = DownloadTask(
        anime_data={"nom_dossier": nom_dossier, "nom_complet": nom_dossier},
        episodes=list(episodes_urls.keys()),
        source=DownloadSource.FRENCH,
    )

    manager = get_download_manager()
    manager.add_task(task)


def fr_queue_worker():
    from src.utils.fetch.fetch_video_source import fetch_video_source
    from src.utils.download.download_video import download_video
    from src.utils.ts.convert_ts_to_mp4 import convert_ts_to_mp4

    from download_manager import get_download_manager

    manager = get_download_manager()
    status = manager.get_status()

    while status['download_queue_size'] > 0 or status['active_downloads']:
        for dl in status.get('active_downloads', []):
            if dl.get('source') == 'french':
                job = {
                    'nom_dossier': dl.get('anime_name'),
                    'ep_num': dl.get('episode'),
                    'url': None,
                    'dest_dir': os.path.join(ANIME_DIR, dl.get('anime_name'))
                }

                video_src = None
                try:
                    video_src = fetch_video_source(job['url'])
                except Exception as e:
                    logger.error(f"Failed to fetch video source: {e}")
                    continue

                if not video_src:
                    continue

                save_path = os.path.join(job['dest_dir'], f"{job['ep_num']}.mp4")

                if "m3u8" in video_src:
                    logger.info(f"Downloading episode {job['ep_num']} (FFmpeg)")
                    headers = f"Referer: {job['url']}\r\nUser-Agent: {HEADERS['User-Agent']}\r\n"

                    cmd = [
                        "ffmpeg",
                        "-hide_banner", "-loglevel", "error", "-stats", "-y",
                        "-headers", headers,
                        "-i", video_src,
                        "-c", "copy",
                        save_path
                    ]

                    try:
                        subprocess.run(cmd, check=True, timeout=3600)
                        logger.info(f"Download complete: {save_path}")
                    except subprocess.TimeoutExpired:
                        logger.error(f"FFmpeg timeout for {save_path}")
                    except subprocess.CalledProcessError as e:
                        logger.error(f"FFmpeg error: {e}")

                else:
                    try:
                        success, output_path = download_video(
                            video_src, save_path, url=job['url'],
                            automatic_mp4=True, interactive=False
                        )
                        if success and output_path and output_path.endswith('.ts'):
                            convert_ts_to_mp4(output_path, save_path, pre_selected_tool='ffmpeg')
                            try:
                                os.remove(output_path)
                            except OSError:
                                pass
                    except Exception as e:
                        logger.error(f"Download error: {e}")

        import time
        time.sleep(1)
        status = manager.get_status()
