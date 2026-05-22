import os
import re
import time
import requests
import threading
import difflib
import random
import datetime
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

import socket
import urllib3.util.connection as urllib3_cn

def allowed_gai_family():
    return socket.AF_INET
urllib3_cn.allowed_gai_family = allowed_gai_family

from tqdm import tqdm
from bs4 import BeautifulSoup

if os.name == 'nt':
    _DEFAULT_ANIME = os.path.join(os.environ['USERPROFILE'], 'Anime')
else:
    _DEFAULT_ANIME = os.path.join(os.path.expanduser('~'), 'Anime')
ANIME_DIR = os.getenv('ANIME_DIR', _DEFAULT_ANIME)

ANILIST_TOKEN = os.getenv('ANILIST_TOKEN', '')
MAX_CONCURRENT_DOWNLOADS = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '3'))
DOWNLOAD_CHUNK_SIZE = int(os.getenv('DOWNLOAD_CHUNK_SIZE', str(4 * 1024 * 1024)))

_shared_session = None
_session_lock = threading.Lock()

def get_session():
    global _shared_session
    if _shared_session is None:
        with _session_lock:
            if _shared_session is None:
                _shared_session = requests.Session()
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=20,
                    pool_maxsize=40,
                    max_retries=2
                )
                _shared_session.mount('https://', adapter)
                _shared_session.mount('http://', adapter)
    return _shared_session

ACTIVE_DOWNLOADS = set()
SEARCH_QUEUE = []
DOWNLOAD_QUEUE = []
FINISHED_DOWNLOADS = []

CURRENT_SEARCH = None
CURRENT_DOWNLOAD = None
PHASE = "IDLE"
WORKER_RUNNING = False

def print_status(etape=""):
    if PHASE == "SEARCH":
        name = CURRENT_SEARCH['anime']['nom_complet'].split(' ;;; ')[0] if CURRENT_SEARCH else ""
        rest = [a['anime']['nom_complet'].split(' ;;; ')[0] for a in SEARCH_QUEUE]
        done = [a['anime']['nom_complet'].split(' ;;; ')[0] for a in DOWNLOAD_QUEUE]
        msg = f"🔍 {name}" if name else ""
        if rest: msg += f" +{len(rest)} en file"
        if done: msg += f" | ✓ {len(done)} trouves"
        if etape: msg = f"{msg} — {etape}" if msg else etape
        if msg: print(msg)
    elif PHASE == "DOWNLOAD":
        current = CURRENT_DOWNLOAD['anime']['nom_complet'].split(' ;;; ')[0] if CURRENT_DOWNLOAD else ""
        rest = [a['anime']['nom_complet'].split(' ;;; ')[0] for a in DOWNLOAD_QUEUE]
        msg = f"⬇ {current}" if current else ""
        if rest: msg += f" +{len(rest)} en attente"
        if FINISHED_DOWNLOADS: msg += f" | ✓ {len(FINISHED_DOWNLOADS)} termines"
        if etape: msg = f"{msg} — {etape}" if msg else etape
        if msg: print(msg)
    elif PHASE == "IDLE":
        if FINISHED_DOWNLOADS:
            print(f"✓ Termines : {FINISHED_DOWNLOADS}")
        if etape:
            print(etape)

def add_to_queue(anime_data, episodes):
    global WORKER_RUNNING
    for ep in episodes:
        ACTIVE_DOWNLOADS.add(f"{anime_data['nom_dossier']}_{ep}")
    SEARCH_QUEUE.append({"anime": anime_data, "episodes": episodes})
    if not WORKER_RUNNING:
        WORKER_RUNNING = True
        t = threading.Thread(target=queue_worker, daemon=True)
        t.start()
    else:
        print_status()

def queue_worker():
    global PHASE, CURRENT_SEARCH, CURRENT_DOWNLOAD, WORKER_RUNNING
    while SEARCH_QUEUE or DOWNLOAD_QUEUE:
        if SEARCH_QUEUE:
            PHASE = "SEARCH"
            CURRENT_SEARCH = SEARCH_QUEUE.pop(0)
            print_status()
            links = extract_links(CURRENT_SEARCH['anime'], CURRENT_SEARCH['episodes'])
            if links:
                DOWNLOAD_QUEUE.append({"anime": CURRENT_SEARCH['anime'], "links": links})
                print_status("✓ Liens trouves")
            else:
                for ep in CURRENT_SEARCH['episodes']:
                    ACTIVE_DOWNLOADS.discard(f"{CURRENT_SEARCH['anime']['nom_dossier']}_{ep}")
                print_status("✗ Aucun lien")
            CURRENT_SEARCH = None
        if DOWNLOAD_QUEUE and not SEARCH_QUEUE:
            PHASE = "DOWNLOAD"
            CURRENT_DOWNLOAD = DOWNLOAD_QUEUE.pop(0)
            print_status()
            download_links(CURRENT_DOWNLOAD['anime'], CURRENT_DOWNLOAD['links'])
            FINISHED_DOWNLOADS.append(CURRENT_DOWNLOAD['anime']['nom_complet'].split(' ;;; ')[0])
            CURRENT_DOWNLOAD = None
            print_status("✓ Termine")
    PHASE = "IDLE"
    WORKER_RUNNING = False
    print_status()

def nettoyer_nom(nom):
    return re.sub(r'\W+', '_', nom).strip('_').capitalize()

def similarity(a, b):
    if not a or not b: return 0
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

def clean_search_term(text):
    if not text: return ""
    text = text.replace("'", "'")
    text = re.sub(r'[^\w\s\']', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_season_number(text):
    text = text.lower()
    match = re.search(r'(\d+)(?:st|nd|rd|th)?\s*season', text)
    if match: return int(match.group(1))
    match = re.search(r'season\s*(\d+)', text)
    if match: return int(match.group(1))
    return None

def get_anilist_data(username=None, status="CURRENT"):
    if not username:
        username = os.getenv('ANILIST_USERNAME', '')
    query = """
    query ($userName: String, $status: MediaListStatus) {
      MediaListCollection(userName: $userName, type: ANIME, status: $status, sort: [UPDATED_TIME_DESC]) {
        lists { entries { updatedAt progress media { id title { romaji english } episodes nextAiringEpisode { episode } siteUrl coverImage { large } } } }
      }
    }
    """
    try:
        resp = get_session().post("https://graphql.anilist.co", json={"query": query, "variables": {"userName": username, "status": status}}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except:
        return []

    resultats = []
    try:
        lists = data.get("data", {}).get("MediaListCollection", {}).get("lists", [])
        for liste in lists:
            for e in liste["entries"]:
                media = e["media"]
                romaji = media["title"].get("romaji") or "Inconnu"
                english = media["title"].get("english")
                nom_affiche = f"{romaji} ;;; {english}" if english else romaji
                progress = e["progress"] or 0
                total = media["episodes"]
                next_ep = media["nextAiringEpisode"]
                episodes_sortis = (next_ep["episode"] - 1) if next_ep else (total if total else progress)
                total_estime = total if isinstance(total, int) else (episodes_sortis + 12)
                resultats.append({
                    "id": media["id"],
                    "nom_complet": nom_affiche,
                    "nom_dossier": nettoyer_nom(romaji),
                    "titres": {"romaji": romaji, "english": english},
                    "progress": progress,
                    "sortie": episodes_sortis,
                    "total": total_estime,
                    "lien": media.get("siteUrl"),
                    "img": media["coverImage"]["large"],
                    "updatedAt": e.get("updatedAt", 0)
                })
        return resultats
    except:
        return []

def get_user_media_ids(username=None):
    if not username:
        username = os.getenv('ANILIST_USERNAME', '')
    query = """
    query ($userName: String) {
      MediaListCollection(userName: $userName, type: ANIME) {
        lists { entries { media { id } } }
      }
    }
    """
    try:
        resp = get_session().post("https://graphql.anilist.co", json={"query": query, "variables": {"userName": username}}, timeout=5)
        data = resp.json()
        ids = set()
        for liste in data.get("data", {}).get("MediaListCollection", {}).get("lists", []):
            for entry in liste["entries"]:
                ids.add(entry["media"]["id"])
        return ids
    except:
        return set()

def get_seasonal_suggestions():
    now = datetime.datetime.now()
    month = now.month
    year = now.year
    season_map = {1: "WINTER", 2: "WINTER", 3: "WINTER", 4: "SPRING", 5: "SPRING", 6: "SPRING",
                  7: "SUMMER", 8: "SUMMER", 9: "SUMMER", 10: "FALL", 11: "FALL", 12: "FALL"}
    season = season_map[month]

    excluded_ids = get_user_media_ids()
    query = """
    query ($season: MediaSeason, $seasonYear: Int) {
      Page(page: 1, perPage: 50) {
        media(season: $season, seasonYear: $seasonYear, sort: SCORE_DESC, type: ANIME, isAdult: false) {
          id title { romaji english } episodes nextAiringEpisode { episode } siteUrl coverImage { large }
        }
      }
    }
    """
    try:
        resp = get_session().post("https://graphql.anilist.co", json={"query": query, "variables": {"season": season, "seasonYear": year}}, timeout=10)
        data = resp.json()
        resultats = []
        for media in data.get("data", {}).get("Page", {}).get("media", []):
            if media["id"] in excluded_ids: continue
            romaji = media["title"].get("romaji")
            english = media["title"].get("english")
            nom_affiche = f"{romaji} ;;; {english}" if english else romaji
            total = media["episodes"]
            next_ep = media["nextAiringEpisode"]
            episodes_sortis = (next_ep["episode"] - 1) if next_ep else (total if total else 0)
            total_estime = total if total else (episodes_sortis + 12)
            resultats.append({
                "id": media["id"], "nom_complet": nom_affiche, "nom_dossier": nettoyer_nom(romaji),
                "titres": {"romaji": romaji, "english": english}, "progress": 0,
                "sortie": episodes_sortis, "total": total_estime, "lien": media.get("siteUrl"),
                "img": media["coverImage"]["large"]
            })
        return resultats
    except:
        return []

def get_airing_schedule():
    query = """
    query {
      Page(page: 1, perPage: 50) {
        airingSchedules(notYetAired: true, sort: TIME) {
          airingAt episode media { id title { romaji english } coverImage { medium } }
        }
      }
    }
    """
    try:
        resp = get_session().post("https://graphql.anilist.co", json={"query": query}, headers={"Content-Type": "application/json"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data: return []
        schedule_by_day = {}
        for item in data.get("data", {}).get("Page", {}).get("airingSchedules", []):
            airing_time = datetime.datetime.fromtimestamp(item["airingAt"])
            day_key = airing_time.strftime("%Y-%m-%d")
            if day_key not in schedule_by_day:
                schedule_by_day[day_key] = {
                    "day": airing_time.strftime("%A"),
                    "date": airing_time.strftime("%d %b"),
                    "animes": []
                }
            media = item.get("media", {})
            schedule_by_day[day_key]["animes"].append({
                "id": media.get("id"),
                "title": media.get("title", {}).get("romaji", ""),
                "episode": item.get("episode"),
                "time": airing_time.strftime("%H:%M"),
                "cover": media.get("coverImage", {}).get("medium")
            })
        now = datetime.datetime.now()
        today_key = now.strftime("%Y-%m-%d")
        return [schedule_by_day[k] for k in sorted(schedule_by_day.keys()) if k >= today_key]
    except:
        return []

def update_anilist_entry(media_id, episode_num, total_episodes):
    if not ANILIST_TOKEN: return False
    status = "CURRENT"
    if total_episodes and isinstance(total_episodes, int) and episode_num >= total_episodes:
        status = "COMPLETED"
    query = """mutation ($id: Int, $progress: Int, $status: MediaListStatus) { SaveMediaListEntry (mediaId: $id, progress: $progress, status: $status) { id status } }"""
    try:
        get_session().post("https://graphql.anilist.co", json={"query": query, "variables": {"id": media_id, "progress": episode_num, "status": status}}, headers={"Authorization": "Bearer " + ANILIST_TOKEN})
        return True
    except:
        return False

def update_anilist_status(media_id, new_status="CURRENT"):
    if not ANILIST_TOKEN: return False
    query = """mutation ($id: Int, $status: MediaListStatus) { SaveMediaListEntry (mediaId: $id, status: $status) { id status } }"""
    try:
        get_session().post("https://graphql.anilist.co", json={"query": query, "variables": {"id": media_id, "status": new_status}}, headers={"Authorization": "Bearer " + ANILIST_TOKEN})
        return True
    except:
        return False

def get_anime_details(anime_data):
    nom_dossier = anime_data['nom_dossier']
    path = os.path.join(ANIME_DIR, nom_dossier)
    total = anime_data.get('total', 0)
    sortie = anime_data.get('sortie', 0)
    progress = anime_data.get('progress', 0)

    if not os.path.exists(path):
        return [{"ep": i, "status": "watched" if i <= progress else ("released" if i <= sortie else "unreleased")} for i in range(1, total + 1)]

    details = []
    for i in range(1, total + 1):
        file_path = os.path.join(path, f"{i}.mp4")
        exists = os.path.exists(file_path)
        is_downloading = f"{nom_dossier}_{i}" in ACTIVE_DOWNLOADS
        if is_downloading:
            status = "downloading"
        elif exists:
            status = "watched_kept" if i <= progress else "downloaded"
        elif i <= progress:
            status = "watched"
        else:
            status = "released" if i <= sortie else "unreleased"
        details.append({"ep": i, "status": status})
    return details

def get_soup(url, session, cookies=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    }
    try:
        resp = session.get(url, headers=headers, cookies=cookies, timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, 'html.parser')
    except:
        return None

def trouver_bon_anime(session, titres):
    site_base = "https://animeheaven.me/search.php?s="
    romaji = titres.get('romaji')
    english = titres.get('english')
    candidats = []

    if english: candidats.append(clean_search_term(english))
    if romaji: candidats.append(clean_search_term(romaji))
    if english:
        short = " ".join(clean_search_term(english).split()[:2])
        if len(short) > 3: candidats.append(short)
    if romaji:
        short = " ".join(clean_search_term(romaji).split()[:2])
        if len(short) > 3: candidats.append(short)

    candidats_uniques = list(dict.fromkeys(candidats))

    for titre_rech in candidats_uniques:
        wanted_season = extract_season_number(titre_rech)
        url_search = f"{site_base}{titre_rech.replace(' ', '+')}"
        soup = get_soup(url_search, session)
        if not soup: continue
        elements = soup.select("div.similarimg a, div.p1 a")
        if not elements: continue
        best_score = 0
        best_url = None
        for el in elements:
            nom_site = el.text.strip()
            found_season = extract_season_number(nom_site)
            if wanted_season is not None and found_season is not None and wanted_season != found_season:
                continue
            score = max(similarity(english or "", nom_site), similarity(romaji or "", nom_site))
            if score > best_score:
                best_score = score
                href = el.get('href')
                best_url = f"https://animeheaven.me/{href}" if not href.startswith('http') else href
        if best_url and best_score > 0.45:
            return best_url
    return None

def extract_links(anime_data, episodes_list):
    titres = anime_data.get('titres', {})
    episodes_list = sorted(episodes_list, key=lambda x: int(x))
    links_dict = {}

    session = get_session()
    print_status("Recherche de l'anime (API rapide)...")
    anime_url = trouver_bon_anime(session, titres)

    if not anime_url:
        print_status("Echec : Anime introuvable.")
        time.sleep(2)
        return {}

    print_status("Scan des IDs d'episodes...")
    soup = get_soup(anime_url, session)
    if not soup: return {}

    ep_ids = {}
    for a_tag in soup.find_all('a'):
        watch_div = a_tag.find('div', class_='watch2')
        if watch_div:
            ep_num_txt = watch_div.text.strip()
            ep_id = a_tag.get("id")
            if ep_num_txt.isdigit() and ep_id:
                ep_ids[int(ep_num_txt)] = ep_id

    previous_extracted_url = None
    for ep_num in episodes_list:
        ep_num = int(ep_num)
        target_id = ep_ids.get(ep_num)
        if not target_id: continue

        print_status(f"Extraction du lien Ep {ep_num}...")
        for attempt in range(3):
            try:
                cookies = {"key": str(target_id)}
                gate_url = f"https://animeheaven.me/gate.php?refresh={random.randint(1, 9999999)}"
                gate_soup = get_soup(gate_url, session, cookies=cookies)
                if not gate_soup: raise Exception("gate.php error")
                video_source = gate_soup.select_one('video source')
                if not video_source or not video_source.get('src'): raise Exception("No source")
                video_url = video_source.get("src")
                if video_url == previous_extracted_url:
                    time.sleep(1)
                    continue
                links_dict[ep_num] = video_url
                previous_extracted_url = video_url
                break
            except:
                time.sleep(1)
    return links_dict

def _download_single_episode(anime_name, nom_dossier, ep_num, video_url):
    dest_dir = os.path.join(ANIME_DIR, nom_dossier)
    os.makedirs(dest_dir, exist_ok=True)
    target_file = os.path.join(dest_dir, f"{ep_num}.mp4")

    try:
        r = get_session().get(video_url, stream=True, timeout=30)
        r.raise_for_status()
        total_size = int(r.headers.get('content-length', 0))
        with open(target_file, "wb") as f, tqdm(
            total=total_size, unit='iB', unit_scale=True, unit_divisor=1024, ncols=90,
            desc=f"{anime_name[:20]} Ep{ep_num}"
        ) as bar:
            for chunk in r.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    size = f.write(chunk)
                    bar.update(size)
        return True
    except:
        if os.path.exists(target_file):
            try: os.remove(target_file)
            except: pass
        return False
    finally:
        ACTIVE_DOWNLOADS.discard(f"{nom_dossier}_{ep_num}")

def download_links(anime_data, links_dict):
    nom_dossier = anime_data['nom_dossier']
    anime_name = anime_data['nom_complet'].split(' ;;; ')[0]
    os.makedirs(os.path.join(ANIME_DIR, nom_dossier), exist_ok=True)
    episodes_list = sorted(links_dict.keys(), key=int)
    total = len(episodes_list)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
        futures = {}
        for ep_num in episodes_list:
            video_url = links_dict[ep_num]
            futures[executor.submit(_download_single_episode, anime_name, nom_dossier, ep_num, video_url)] = ep_num

        for i, future in enumerate(as_completed(futures), 1):
            ep_num = futures[future]
            success = future.result()
            status = "OK" if success else "ECHEC"
            print_status(f"[{i}/{total}] Ep {ep_num} {status}")

def delete_episodes(nom_dossier, episodes_list):
    count = 0
    for ep in episodes_list:
        path = os.path.join(ANIME_DIR, nom_dossier, f"{ep}.mp4")
        if os.path.exists(path):
            os.remove(path)
            count += 1
    return count

def open_local_file(nom_dossier, episode):
    path = os.path.join(ANIME_DIR, nom_dossier, f"{episode}.mp4")
    if os.path.exists(path):
        if os.name == 'nt':
            os.startfile(path)
        else:
            try: subprocess.call(('xdg-open', path))
            except: subprocess.call(('open', path))
        return True
    return False

def pull_all_user_data(username=None):
    if not username:
        username = os.getenv('ANILIST_USERNAME', '')
    result = {}
    for status in ["CURRENT", "PLANNING", "COMPLETED"]:
        data = get_anilist_data(username=username, status=status)
        for item in data:
            item['list_status'] = status
            aid = item['id']
            if aid not in result:
                result[aid] = item
    return list(result.values())

def push_entry_to_anilist(anilist_id, progress, total_episodes, status):
    return update_anilist_entry(anilist_id, progress, total_episodes)
