import os
import sys
import logging
import threading
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    session: Any
    headers: Dict[str, str]
    cookies: Dict[str, str]
    user_agent: str


class CloudflareBypass:
    _instance: Optional["CloudflareBypass"] = None
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
        self._session: Optional[Any] = None
        self._session_lock = threading.Lock()
        self._cached_headers: Optional[Dict[str, str]] = None
        self._cached_user_agent: Optional[str] = None

    def _get_cloudscraper_session(self) -> Tuple[Any, Dict[str, str]]:
        try:
            import cloudscraper
        except ImportError:
            logger.warning("cloudscraper not installed, falling back to requests")
            return self._get_requests_session()

        try:
            scraper = cloudscraper.create_scraper(
                browser={
                    "browser": "chrome",
                    "platform": "windows",
                    "desktop": True,
                },
                delay=10,
            )

            default_headers = {
                "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }

            return scraper, default_headers

        except Exception as e:
            logger.error(f"Failed to create cloudscraper session: {e}")
            return self._get_requests_session()

    def _get_selenium_session(self) -> Tuple[Any, Dict[str, str]]:
        try:
            import undetected_chromedriver as uc
            from selenium.webdriver.chrome.options import Options
        except ImportError:
            logger.warning("undetected_chromedriver not installed")
            return self._get_requests_session()

        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")

            driver = uc.Chrome(options=chrome_options, version_main=None)
            driver.implicitly_wait(15)

            user_agent = driver.execute_script(
                "return navigator.userAgent;"
            )

            headers = {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9",
            }

            return driver, headers

        except Exception as e:
            logger.error(f"Failed to create Selenium session: {e}")
            return self._get_requests_session()

    def _get_requests_session(self) -> Tuple[Any, Dict[str, str]]:
        import requests

        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
        })

        return session, dict(session.headers)

    def get_session(self, mode: Optional[str] = None) -> SessionInfo:
        from src.var import get_cloudflare_mode

        if mode is None:
            mode = get_cloudflare_mode()

        with self._session_lock:
            if self._session is not None:
                return SessionInfo(
                    session=self._session,
                    headers=self._cached_headers or {},
                    cookies=getattr(self._session, "cookies", {}),
                    user_agent=self._cached_user_agent or "",
                )

            if mode == "cloudscraper":
                self._session, self._cached_headers = self._get_cloudscraper_session()
            elif mode == "selenium":
                self._session, self._cached_headers = self._get_selenium_session()
            else:
                self._session, self._cached_headers = self._get_requests_session()

            self._cached_user_agent = self._cached_headers.get("User-Agent", "")

            return SessionInfo(
                session=self._session,
                headers=self._cached_headers,
                cookies=getattr(self._session, "cookies", {}),
                user_agent=self._cached_user_agent,
            )

    def invalidate_session(self):
        with self._session_lock:
            if self._session is not None:
                try:
                    if hasattr(self._session, "close"):
                        self._session.close()
                except Exception:
                    pass
                self._session = None
                self._cached_headers = None
                self._cached_user_agent = None


def get_cf_session(mode: Optional[str] = None) -> SessionInfo:
    bypass = CloudflareBypass()
    return bypass.get_session(mode)


def invalidate_cf_session():
    bypass = CloudflareBypass()
    bypass.invalidate_session()
