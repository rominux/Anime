import os
import re
import time
import logging
import requests
import threading
import difflib
import random
import datetime
import subprocess

from tqdm import tqdm
from bs4 import BeautifulSoup

from dotenv import load_dotenv
from src.var import get_anime_dir, get_anilist_token

load_dotenv()

logger = logging.getLogger(__name__)

import socket
import urllib3.util.connection as urllib3_cn

def allowed_gai_family():
    return socket.AF_INET
urllib3_cn.allowed_gai_family = allowed_gai_family

ANIME_DIR = get_anime_dir()
ANILIST_TOKEN = get_anilist_token()

WATCHING_FILE = "Watching.txt"
TOKEN_FILENAME = "token"

def print_status(etape=""):
    if etape:
        logger.info(f"[STATUS] {etape}")

def nettoyer_nom(nom):
    return re.sub(r'\W+', '_', nom).strip('_').capitalize()

def similarity(a, b):
    if not a or not b:
        return 0
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

def clean_search_term(text):
    if not text:
        return ""
    text = text.replace("'", "'")
    text = re.sub(r'[^\w\s\']', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_season_number(text):
    text = text.lower()
    match = re.search(r'(\d+)(?:st|nd|rd|th)?\s*season', text)
    if match:
        return int(match.group(1))
    match = re.search(r'season\s*(\d+)', text)
    if match:
        return int(match.group(1))
    return None

def get_anilist_data(username="Pate0Sucre", status="CURRENT"):
    query = """
    query ($userName: String, $status: MediaListStatus) {
      MediaListCollection(userName: $userName, type: ANIME, status: $status, sort: [UPDATED_TIME_DESC]) {
        lists { entries { updatedAt progress media { id title { romaji english } episodes nextAiringEpisode { episode } siteUrl coverImage { large } } } }
      }
    }
    """
    try:
        resp = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"userName": username, "status": status}},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        logger.error("AniList API request timed out")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"AniList API request failed: {e}")
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
    except (KeyError, TypeError) as e:
        logger.error(f"Failed to parse AniList response: {e}")
        return []

def get_user_media_ids(username="Pate0Sucre"):
    query = """
    query ($userName: String) {
      MediaListCollection(userName: $userName, type: ANIME) {
        lists { entries { media { id } } }
      }
    }
    """
    try:
        resp = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"userName": username}},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        ids = set()
        for liste in data.get("data", {}).get("MediaListCollection", {}).get("lists", []):
            for entry in liste["entries"]:
                ids.add(entry["media"]["id"])
        return ids
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get user media IDs: {e}")
        return set()

def get_seasonal_suggestions():
    now = datetime.datetime.now()
    month = now.month
    year = now.year

    if month in [1, 2, 3]:
        season = "WINTER"
    elif month in [4, 5, 6]:
        season = "SPRING"
    elif month in [7, 8, 9]:
        season = "SUMMER"
    else:
        season = "FALL"

    excluded_ids = get_user_media_ids()

    query = """
    query ($season: MediaSeason, $seasonYear: Int) {
      Page(page: 1, perPage: 50) {
        media(season: $season, seasonYear: $seasonYear, sort: [SCORE_DESC], type: ANIME, isAdult: false) {
          id title { romaji english } episodes nextAiringEpisode { episode } siteUrl coverImage { large }
        }
      }
    }
    """
    try:
        resp = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"season": season, "seasonYear": year}},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        resultats = []

        for media in data.get("data", {}).get("Page", {}).get("media", []):
            if media["id"] in excluded_ids:
                continue
            romaji = media["title"].get("romaji")
            english = media["title"].get("english")
            nom_affiche = f"{romaji} ;;; {english}" if english else romaji
            total = media["episodes"]
            next_ep = media["nextAiringEpisode"]
            episodes_sortis = (next_ep["episode"] - 1) if next_ep else (total if total else 0)
            total_estime = total if total else (episodes_sortis + 12)

            resultats.append({
                "id": media["id"],
                "nom_complet": nom_affiche,
                "nom_dossier": nettoyer_nom(romaji),
                "titres": {"romaji": romaji, "english": english},
                "progress": 0,
                "sortie": episodes_sortis,
                "total": total_estime,
                "lien": media.get("siteUrl"),
                "img": media["coverImage"]["large"]
            })
        return resultats
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch seasonal suggestions: {e}")
        return []

def update_anilist_entry(media_id, episode_num, total_episodes):
    if not ANILIST_TOKEN:
        return False
    status = "CURRENT"
    if total_episodes and isinstance(total_episodes, int) and episode_num >= total_episodes:
        status = "COMPLETED"

    query = """mutation ($id: Int, $progress: Int, $status: MediaListStatus) { SaveMediaListEntry (mediaId: $id, progress: $progress, status: $status) { id status } }"""

    try:
        resp = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"id": media_id, "progress": episode_num, "status": status}},
            headers={"Authorization": "Bearer " + ANILIST_TOKEN},
            timeout=10
        )
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to update AniList entry: {e}")
        return False

def update_anilist_status(media_id, new_status="CURRENT"):
    if not ANILIST_TOKEN:
        return False

    query = """mutation ($id: Int, $status: MediaListStatus) { SaveMediaListEntry (mediaId: $id, status: $status) { id status } }"""

    try:
        resp = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"id": media_id, "status": new_status}},
            headers={"Authorization": "Bearer " + ANILIST_TOKEN},
            timeout=10
        )
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to update AniList status: {e}")
        return False

def get_anime_details(anime_data):
    nom_dossier = anime_data['nom_dossier']
    path = os.path.join(ANIME_DIR, nom_dossier)
    details = []

    logger.debug(f"[logic] Getting details for {nom_dossier} from {path}")

    if not os.path.exists(path):
        logger.debug(f"[logic] Path doesn't exist, creating default episode list")
        for i in range(1, anime_data['total'] + 1):
            status = "released" if i <= anime_data['sortie'] else "unreleased"
            details.append({"ep": i, "status": status})
        return details

    for i in range(1, anime_data['total'] + 1):
        file_path = os.path.join(path, f"{i}.mp4")
        exists = os.path.exists(file_path)
        status = "unknown"
        if exists:
            status = "watched_kept" if i <= anime_data['progress'] else "downloaded"
        else:
            status = "released" if i <= anime_data['sortie'] else "unreleased"
        details.append({"ep": i, "status": status})

    logger.debug(f"[logic] Returning {len(details)} episode details")
    return details

def get_soup(url, session, cookies=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    }
    try:
        resp = session.get(url, headers=headers, cookies=cookies, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, 'html.parser')
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch soup from {url}: {e}")
        return None

def trouver_bon_anime(session, titres):
    site_base = "https://animeheaven.me/search.php?s="
    romaji = titres.get('romaji')
    english = titres.get('english')
    candidats = []

    if english:
        candidats.append(clean_search_term(english))
    if romaji:
        candidats.append(clean_search_term(romaji))
    if english:
        short = " ".join(clean_search_term(english).split()[:2])
        if len(short) > 3:
            candidats.append(short)
    if romaji:
        short = " ".join(clean_search_term(romaji).split()[:2])
        if len(short) > 3:
            candidats.append(short)

    candidats_uniques = list(dict.fromkeys(candidats))

    for titre_rech in candidats_uniques:
        wanted_season = extract_season_number(titre_rech)
        url_search = f"{site_base}{titre_rech.replace(' ', '+')}"
        soup = get_soup(url_search, session)

        if not soup:
            continue

        elements = soup.select("div.similarimg a, div.p1 a")
        if not elements:
            continue

        best_score = 0
        best_url = None

        for el in elements:
            nom_site = el.text.strip()
            found_season = extract_season_number(nom_site)

            if wanted_season is not None and found_season is not None:
                if wanted_season != found_season:
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

    session = requests.Session()

    print_status("Recherche de l'anime (API rapide)...")
    anime_url = trouver_bon_anime(session, titres)

    if not anime_url:
        print_status("Echec : Anime introuvable.")
        time.sleep(2)
        return {}

    print_status("Scan des IDs d'episodes...")
    soup = get_soup(anime_url, session)
    if not soup:
        return {}

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

        if not target_id:
            continue

        print_status(f"Extraction du lien Ep {ep_num}...")
        retries = 0
        while retries < 3:
            try:
                cookies = {"key": str(target_id)}
                anti_cache = random.randint(1, 9999999)
                gate_url = f"https://animeheaven.me/gate.php?refresh={anti_cache}"

                gate_soup = get_soup(gate_url, session, cookies=cookies)
                if not gate_soup:
                    raise ValueError("Erreur requete gate.php")

                video_source = gate_soup.select_one('video source')
                if not video_source or not video_source.get('src'):
                    raise ValueError("Lien introuvable dans gate.php")

                video_url = video_source.get("src")

                if video_url == previous_extracted_url:
                    time.sleep(1)
                    retries += 1
                    continue

                links_dict[ep_num] = video_url
                previous_extracted_url = video_url
                break

            except (ValueError, requests.exceptions.RequestException) as e:
                logger.warning(f"Retry {retries + 1}/3 for Ep {ep_num}: {e}")
                retries += 1
                time.sleep(1)

    return links_dict

def download_links(anime_data, links_dict):
    nom_dossier = anime_data['nom_dossier']
    anime_name = anime_data['nom_complet'].split(' ;;; ')[0]

    dest_dir = os.path.join(ANIME_DIR, nom_dossier)
    os.makedirs(dest_dir, exist_ok=True)

    episodes_list = sorted(list(links_dict.keys()), key=int)

    for ep_num in episodes_list:
        video_url = links_dict[ep_num]
        action_text = f"anime {anime_name} episode {ep_num}"
        print_status(action_text)

        try:
            r = requests.get(video_url, stream=True, timeout=60)
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            block_size = 1024 * 1024
            target_file = os.path.join(dest_dir, f"{ep_num}.mp4")

            with open(target_file, "wb") as f, tqdm(
                total=total_size, unit='iB', unit_scale=True, unit_divisor=1024, ncols=90
            ) as bar:
                for chunk in r.iter_content(chunk_size=block_size):
                    if chunk:
                        size = f.write(chunk)
                        bar.update(size)
        except requests.exceptions.RequestException as e:
            logger.error(f"Download failed for {anime_name} Ep {ep_num}: {e}")
            target_file = os.path.join(dest_dir, f"{ep_num}.mp4")
            if os.path.exists(target_file):
                try:
                    os.remove(target_file)
                except OSError:
                    pass

def delete_episodes(nom_dossier, episodes_list):
    count = 0
    for ep in episodes_list:
        path = os.path.join(ANIME_DIR, nom_dossier, f"{ep}.mp4")
        if os.path.exists(path):
            try:
                os.remove(path)
                count += 1
            except OSError as e:
                logger.error(f"Failed to delete {path}: {e}")
    return count

def delete_all_episodes(nom_dossier):
    path = os.path.join(ANIME_DIR, nom_dossier)
    if os.path.exists(path):
        for f in os.listdir(path):
            if f.endswith('.mp4'):
                try:
                    os.remove(os.path.join(path, f))
                except OSError as e:
                    logger.error(f"Failed to delete {f}: {e}")

def delete_episodes_before(nom_dossier, before_episode):
    path = os.path.join(ANIME_DIR, nom_dossier)
    if os.path.exists(path):
        for f in os.listdir(path):
            if f.endswith('.mp4'):
                try:
                    ep_num = int(f.replace('.mp4', ''))
                    if ep_num < before_episode:
                        os.remove(os.path.join(path, f))
                except (ValueError, OSError) as e:
                    logger.error(f"Failed to process {f}: {e}")

def open_local_file(nom_dossier, episode):
    path = os.path.join(ANIME_DIR, nom_dossier, f"{episode}.mp4")
    if os.path.exists(path):
        if os.name == 'nt':
            os.startfile(path)
        else:
            try:
                subprocess.call(('xdg-open', path))
            except FileNotFoundError:
                try:
                    subprocess.call(('open', path))
                except FileNotFoundError:
                    logger.error("No application found to open video file")
        return True
    return False

def search_anilist(query):
    graphql_query = """
    query ($search: String) {
      Page(page: 1, perPage: 30) {
        media(search: $search, type: ANIME, sort: SEARCH_MATCH, isAdult: false) {
          id title { romaji english } episodes nextAiringEpisode { episode } siteUrl coverImage { large }
        }
      }
    }
    """
    try:
        resp = requests.post(
            "https://graphql.anilist.co",
            json={"query": graphql_query, "variables": {"search": query}},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        resultats = []

        for media in data.get("data", {}).get("Page", {}).get("media", []):
            romaji = media["title"].get("romaji")
            english = media["title"].get("english")
            nom_affiche = f"{romaji} ;;; {english}" if english else romaji
            total = media["episodes"]
            next_ep = media["nextAiringEpisode"]
            episodes_sortis = (next_ep["episode"] - 1) if next_ep else (total if total else 0)

            resultats.append({
                "id": media["id"],
                "nom_complet": nom_affiche,
                "nom_dossier": nettoyer_nom(romaji),
                "titres": {"romaji": romaji, "english": english},
                "progress": 0,
                "sortie": episodes_sortis,
                "total": total,
                "lien": media.get("siteUrl"),
                "img": media["coverImage"]["large"]
            })
        return resultats
    except requests.exceptions.RequestException as e:
        logger.error(f"AniList search failed: {e}")
        return []


def cache_cover(anime_data):
    nom_dossier = anime_data.get("nom_dossier")
    if not nom_dossier:
        return False
    
    anime_dir = os.path.join(ANIME_DIR, nom_dossier)
    os.makedirs(anime_dir, exist_ok=True)
    
    cover_path_jpg = os.path.join(anime_dir, "cover.jpg")
    cover_path_png = os.path.join(anime_dir, "cover.png")
    
    if os.path.exists(cover_path_jpg) or os.path.exists(cover_path_png):
        return True
    
    img_url = anime_data.get("img")
    if not img_url:
        return False
    
    try:
        resp = requests.get(img_url, timeout=15, stream=True)
        resp.raise_for_status()
        
        content_type = resp.headers.get("Content-Type", "")
        if "png" in content_type.lower():
            target_path = cover_path_png
        else:
            target_path = cover_path_jpg
        
        with open(target_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        logger.info(f"[CACHE] Downloaded cover for {nom_dossier}")
        return True
    except Exception as e:
        logger.error(f"[CACHE] Failed to download cover for {nom_dossier}: {e}")
        return False


def cache_all_covers(anime_list):
    for anime in anime_list:
        threading.Thread(target=cache_cover, args=(anime,), daemon=True).start()


def get_local_cover_path(nom_dossier):
    anime_dir = os.path.join(ANIME_DIR, nom_dossier)
    cover_jpg = os.path.join(anime_dir, "cover.jpg")
    cover_png = os.path.join(anime_dir, "cover.png")
    
    if os.path.exists(cover_jpg):
        return cover_jpg
    if os.path.exists(cover_png):
        return cover_png
    return None


def get_airing_schedule(username="Pate0Sucre"):
    try:
        resp = requests.post(
            "https://graphql.anilist.co",
            json={
                "query": """
                query ($userName: String) {
                  MediaListCollection(userName: $userName, type: ANIME, status_in: [CURRENT, PLANNING]) {
                    lists { entries { status progress media { id title { romaji english } nextAiringEpisode { episode airingAt } coverImage { large } } } }
                  }
                }
                """,
                "variables": {"userName": username}
            },
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch airing schedule: {e}")
        return []
    
    schedule_by_day = {}
    day_names_en = {
        "Monday": "Lundi",
        "Tuesday": "Mardi",
        "Wednesday": "Mercredi",
        "Thursday": "Jeudi",
        "Friday": "Vendredi",
        "Saturday": "Samedi",
        "Sunday": "Dimanche"
    }
    month_names_en = {
        "January": "Janvier", "February": "Février", "March": "Mars",
        "April": "Avril", "May": "Mai", "June": "Juin",
        "July": "Juillet", "August": "Août", "September": "Septembre",
        "October": "Octobre", "November": "Novembre", "December": "Décembre"
    }
    
    now = datetime.datetime.now()
    today_ts = int(now.timestamp())
    week_later_ts = int((now + datetime.timedelta(days=7)).timestamp())
    
    try:
        lists = data.get("data", {}).get("MediaListCollection", {}).get("lists", [])
        for liste in lists:
            for entry in liste["entries"]:
                media = entry["media"]
                entry_status = entry.get("status", "CURRENT")
                next_ep = media.get("nextAiringEpisode")
                if next_ep and next_ep.get("airingAt"):
                    airing_ts = next_ep["airingAt"]
                    if airing_ts < today_ts or airing_ts > week_later_ts:
                        continue
                    dt = datetime.datetime.fromtimestamp(airing_ts)
                    day_key = dt.strftime("%Y-%m-%d")
                    day_display = day_names_en.get(dt.strftime("%A"), dt.strftime("%A"))
                    
                    if day_key not in schedule_by_day:
                        month_en = dt.strftime("%B")
                        month_fr = month_names_en.get(month_en, month_en)
                        schedule_by_day[day_key] = {
                            "day_name": day_display,
                            "day_num": dt.day,
                            "month": month_fr,
                            "animes": []
                        }
                    
                    schedule_by_day[day_key]["animes"].append({
                        "id": media["id"],
                        "title": media["title"].get("romaji") or media["title"].get("english", "Unknown"),
                        "episode": next_ep.get("episode", 0),
                        "airing_at": airing_ts,
                        "airing_time": dt.strftime("%H:%M"),
                        "airing_date": dt.strftime("%d/%m/%Y"),
                        "cover": media["coverImage"]["large"],
                        "status": entry_status
                    })
        
        result = []
        for day_key in sorted(schedule_by_day.keys()):
            day_data = schedule_by_day[day_key]
            day_data["animes"].sort(key=lambda x: x["airing_at"])
            result.append(day_data)
        
        return result
    except (KeyError, TypeError) as e:
        logger.error(f"Failed to parse schedule: {e}")
        return []


def scan_cleanup(watching_folders=None, planning_folders=None, completed_folders=None):
    watching_nom_dossiers = set(watching_folders or [])
    planning_nom_dossiers = set(planning_folders or [])
    completed_nom_dossiers = set(completed_folders or [])
    
    empty_folders = []
    empty_on_list = []
    orphaned_folders = []
    
    if not os.path.exists(ANIME_DIR):
        return {"empty": [], "empty_on_list": [], "orphaned": []}
    
    for folder in os.listdir(ANIME_DIR):
        folder_path = os.path.join(ANIME_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        
        has_videos = any(f.endswith(".mp4") or f.endswith(".mkv") for f in os.listdir(folder_path))
        
        cover_jpg = os.path.join(folder_path, "cover.jpg")
        cover_png = os.path.join(folder_path, "cover.png")
        local_cover = cover_jpg if os.path.exists(cover_jpg) else (cover_png if os.path.exists(cover_png) else None)
        
        base_folder = folder.replace("_FR", "")
        
        folder_status = "Orphelin"
        if base_folder in watching_nom_dossiers:
            folder_status = "Watching"
        elif base_folder in planning_nom_dossiers:
            folder_status = "Planning"
        elif base_folder in completed_nom_dossiers:
            folder_status = "Completed"
        
        folder_info = {
            "name": folder,
            "type": "empty" if not has_videos else "orphaned",
            "cover": local_cover,
            "status": folder_status
        }
        
        if not has_videos:
            if folder_status != "Orphelin":
                folder_info["type"] = "empty_on_list"
                empty_on_list.append(folder_info)
            else:
                empty_folders.append(folder_info)
        else:
            if folder_status != "Orphelin":
                continue
            orphaned_folders.append(folder_info)
    
    return {"empty": empty_folders, "empty_on_list": empty_on_list, "orphaned": orphaned_folders}
