import os
import re
import time
import logging
import threading
import queue
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set
from enum import Enum

import requests
from tqdm import tqdm

from dotenv import load_dotenv
from src.var import setup_logging, get_anime_dir

load_dotenv()

setup_logging()
logger = logging.getLogger(__name__)


class DownloadPhase(Enum):
    IDLE = "IDLE"
    SEARCH = "SEARCH"
    DOWNLOAD = "DOWNLOAD"


class DownloadSource(Enum):
    ENGLISH = "english"
    FRENCH = "french"


@dataclass
class DownloadTask:
    anime_data: Dict[str, Any]
    episodes: List[int]
    source: DownloadSource = DownloadSource.ENGLISH


@dataclass
class DownloadProgress:
    anime_name: str
    episode: int
    progress: float = 0.0
    phase: DownloadPhase = DownloadPhase.IDLE
    speed: str = ""
    eta: str = ""
    source: DownloadSource = DownloadSource.ENGLISH


@dataclass
class ActiveDownload:
    key: str
    anime_name: str
    episode: int
    progress: float
    total_size: int = 0
    downloaded_size: int = 0
    source: DownloadSource = DownloadSource.ENGLISH


class Config:
    def __init__(self):
        self.ANIME_DIR = get_anime_dir()
        logger.info(f"Anime directory: {self.ANIME_DIR}")

        self.ANILIST_TOKEN = os.environ.get("ANILIST_TOKEN", "")
        self.ANILIST_USERNAME = os.environ.get("ANILIST_USERNAME", "Pate0Sucre")
        self.MAX_CONCURRENT_DOWNLOADS = int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", "3"))
        self.DOWNLOAD_CHUNK_SIZE = int(os.environ.get("DOWNLOAD_CHUNK_SIZE", "1048576"))

        self.WATCHING_FILE = "Watching.txt"
        self.TOKEN_FILENAME = "token"

        if not self.ANILIST_TOKEN:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            token_path = os.path.join(base_dir, self.TOKEN_FILENAME)
            if os.path.exists(token_path):
                try:
                    with open(token_path, "r", encoding="utf-8") as f:
                        self.ANILIST_TOKEN = f.read().strip()
                        logger.info("AniList token loaded from file")
                except IOError as e:
                    logger.warning(f"Could not read token file: {e}")

        if os.environ.get("ANILIST_TOKEN"):
            self.ANILIST_TOKEN = os.environ.get("ANILIST_TOKEN")
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            token_path = os.path.join(base_dir, self.TOKEN_FILENAME)
            if os.path.exists(token_path):
                try:
                    with open(token_path, "r", encoding="utf-8") as f:
                        self.ANILIST_TOKEN = f.read().strip()
                except IOError as e:
                    logger.warning(f"Could not read token file: {e}")

    def ensure_dir(self):
        os.makedirs(self.ANIME_DIR, exist_ok=True)


class DownloadManager:
    _instance: Optional["DownloadManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._state_lock = threading.Lock()

        self._config = Config()

        self._active_downloads: Dict[str, ActiveDownload] = {}
        self._search_queue: queue.Queue = queue.Queue()
        self._download_queue: queue.Queue = queue.Queue()
        self._finished_downloads: List[str] = []

        self._phase = DownloadPhase.IDLE
        self._current_search: Optional[Dict] = None
        self._current_download: Optional[Dict] = None
        self._worker_running = False
        self._worker_thread: Optional[threading.Thread] = None

        self._subscribers: List[threading.Event] = []
        self._update_event = threading.Event()

        logger.info("DownloadManager initialized")

    @property
    def config(self) -> Config:
        return self._config

    @property
    def anime_dir(self) -> str:
        return self._config.ANIME_DIR

    @property
    def anilist_token(self) -> str:
        return self._config.ANILIST_TOKEN

    def subscribe(self) -> threading.Event:
        event = threading.Event()
        with self._state_lock:
            # Limit subscribers to prevent resource exhaustion
            if len(self._subscribers) >= 10:
                logger.warning(f"[DownloadManager] Too many subscribers ({len(self._subscribers)}), not adding more")
                return event
            self._subscribers.append(event)
            logger.info(f"[DownloadManager] Subscriber added. Total: {len(self._subscribers)}")
        return event

    def unsubscribe(self, event: threading.Event):
        with self._state_lock:
            if event in self._subscribers:
                self._subscribers.remove(event)
                logger.info(f"[DownloadManager] Subscriber removed. Total: {len(self._subscribers)}")

    def _notify_subscribers(self):
        self._update_event.set()
        for event in self._subscribers:
            event.set()

    def get_active_downloads(self) -> List[Dict[str, Any]]:
        with self._state_lock:
            return [
                {
                    "key": ad.key,
                    "anime_name": ad.anime_name,
                    "episode": ad.episode,
                    "progress": ad.progress,
                    "total_size": ad.total_size,
                    "downloaded_size": ad.downloaded_size,
                    "source": ad.source.value,
                }
                for ad in self._active_downloads.values()
            ]

    def has_active_downloads(self) -> bool:
        with self._state_lock:
            return len(self._active_downloads) > 0

    def get_status(self) -> Dict[str, Any]:
        active_downloads_list = self.get_active_downloads()
        with self._state_lock:
            return {
                "phase": self._phase.value,
                "current_search": (
                    self._current_search["anime"]["nom_complet"].split(" ;;; ")[0]
                    if self._current_search else None
                ),
                "current_download": (
                    self._current_download["anime"]["nom_complet"].split(" ;;; ")[0]
                    if self._current_download else None
                ),
                "search_queue_size": self._search_queue.qsize(),
                "download_queue_size": self._download_queue.qsize(),
                "finished_downloads": self._finished_downloads[-10:],
                "active_downloads": active_downloads_list,
            }

    def add_task(self, task: DownloadTask) -> bool:
        try:
            with self._state_lock:
                for ep in task.episodes:
                    key = f"{task.anime_data['nom_dossier']}_{ep}"
                    self._active_downloads[key] = ActiveDownload(
                        key=key,
                        anime_name=task.anime_data["nom_complet"].split(" ;;; ")[0],
                        episode=ep,
                        progress=0.0,
                        source=task.source,
                    )

            self._search_queue.put(task)
            self._notify_subscribers()

            if not self._worker_running:
                self._start_worker()

            return True
        except Exception as e:
            logger.error(f"Error adding task to queue: {e}")
            return False

    def _start_worker(self):
        with self._state_lock:
            if self._worker_running:
                return
            self._worker_running = True

        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("Download worker started - Processing queue")

    def _worker_loop(self):
        while True:
            try:
                if not self._search_queue.empty():
                    with self._state_lock:
                        self._phase = DownloadPhase.SEARCH
                    self._process_search_queue()
                elif not self._download_queue.empty():
                    with self._state_lock:
                        self._phase = DownloadPhase.DOWNLOAD
                    self._process_download_queue()
                else:
                    with self._state_lock:
                        if self._phase != DownloadPhase.IDLE:
                            self._phase = DownloadPhase.IDLE
                            self._notify_subscribers()
                        if not self._worker_running:
                            break
                    time.sleep(0.5)
                    continue

                with self._state_lock:
                    if self._search_queue.empty() and self._download_queue.empty():
                        self._worker_running = False
                        self._phase = DownloadPhase.IDLE
                        self._notify_subscribers()
                        logger.info("Download worker finished - queues empty")
                        break

            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                time.sleep(1)

    def _process_search_queue(self):
        while not self._search_queue.empty():
            try:
                task = self._search_queue.get_nowait()
            except queue.Empty:
                break

            with self._state_lock:
                self._current_search = {"anime": task.anime_data, "episodes": task.episodes}
            self._notify_subscribers()

            links = {}
            try:
                if task.source == DownloadSource.ENGLISH:
                    links = self._extract_links_en(task.anime_data, task.episodes)
                else:
                    links = self._extract_links_fr(task.anime_data, task.episodes)
            except Exception as e:
                logger.error(f"Link extraction failed: {e}")

            if links:
                self._download_queue.put(
                    {
                        "anime": task.anime_data,
                        "links": links,
                        "source": task.source,
                    }
                )
            else:
                with self._state_lock:
                    for ep in task.episodes:
                        key = f"{task.anime_data['nom_dossier']}_{ep}"
                        self._active_downloads.pop(key, None)

            with self._state_lock:
                self._current_search = None
            self._notify_subscribers()

    def _process_download_queue(self):
        while not self._download_queue.empty():
            try:
                job = self._download_queue.get_nowait()
            except queue.Empty:
                break

            anime_name = job["anime"]["nom_complet"].split(" ;;; ")[0]
            source = job.get("source", DownloadSource.ENGLISH)
            nom_dossier = job["anime"]["nom_dossier"]

            with self._state_lock:
                self._current_download = job
            self._notify_subscribers()

            dest_dir = os.path.join(self._config.ANIME_DIR, nom_dossier)
            os.makedirs(dest_dir, exist_ok=True)

            for ep_num, video_url in job["links"].items():
                key = f"{nom_dossier}_{ep_num}"
                try:
                    self._download_file(
                        video_url,
                        os.path.join(dest_dir, f"{ep_num}.mp4"),
                        anime_name,
                        ep_num,
                        source,
                    )
                except requests.exceptions.RequestException as e:
                    logger.error(f"Download failed for {anime_name} Ep {ep_num}: {e}")

            with self._state_lock:
                for ep_num in job["links"].keys():
                    key = f"{nom_dossier}_{ep_num}"
                    self._active_downloads.pop(key, None)
                self._finished_downloads.append(anime_name)
                self._current_download = None
            self._notify_subscribers()

    def _extract_links_en(self, anime_data, episodes_list):
        try:
            import logic
            return logic.extract_links(anime_data, episodes_list)
        except Exception as e:
            logger.error(f"English link extraction failed: {e}")
            return {}

    def _extract_links_fr(self, anime_data, episodes_urls):
        try:
            import logic_fr
            result = {}
            for ep_num, url in episodes_urls.items():
                result[ep_num] = url
            return result
        except Exception as e:
            logger.error(f"French link extraction failed: {e}")
            return {}

    def _download_file(
        self,
        url: str,
        save_path: str,
        anime_name: str,
        episode: int,
        source: DownloadSource,
    ):
        key = f"{os.path.basename(os.path.dirname(save_path))}_{episode}"
        last_notify_time = time.time()
        downloaded_size = 0
        progress = 0.0

        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            block_size = self._config.DOWNLOAD_CHUNK_SIZE

            with open(save_path, "wb") as f, tqdm(
                total=total_size,
                unit="iB",
                unit_scale=True,
                unit_divisor=1024,
                ncols=90,
                desc=f"{anime_name[:20]} Ep{episode}",
            ) as bar:
                for chunk in response.iter_content(chunk_size=block_size):
                    if chunk:
                        size = f.write(chunk)
                        bar.update(size)
                        downloaded_size += size

                        if total_size > 0:
                            progress = (downloaded_size / total_size) * 100
                            current_time = time.time()
                            if current_time - last_notify_time >= 0.5:
                                with self._state_lock:
                                    if key in self._active_downloads:
                                        ad = self._active_downloads[key]
                                        ad.downloaded_size = downloaded_size
                                        ad.progress = progress
                                self._notify_subscribers()
                                last_notify_time = current_time

        except requests.exceptions.RequestException as e:
            logger.error(f"Download error: {e}")
            if os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except OSError:
                    pass
            raise

    def clear_finished(self):
        with self._state_lock:
            self._finished_downloads.clear()
        self._notify_subscribers()

    def cancel_download(self, key: str) -> bool:
        with self._state_lock:
            if key in self._active_downloads:
                del self._active_downloads[key]
                self._notify_subscribers()
                return True
        return False


_manager_instance: Optional[DownloadManager] = None
_manager_lock = threading.Lock()


def get_download_manager() -> DownloadManager:
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = DownloadManager()
    return _manager_instance
