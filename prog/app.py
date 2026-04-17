import os
import sys
import time
import logging
from flask import Flask, render_template, request, redirect, url_for, jsonify, Response, stream_with_context, send_file
import mimetypes
import threading
import requests

from dotenv import load_dotenv

load_dotenv()

import logic
import logic_fr
from download_manager import get_download_manager, DownloadTask, DownloadSource
from src.var import (
    setup_logging,
    get_anime_dir,
    get_flask_host,
    get_flask_port,
    get_flask_debug,
)
from models import db, Anime, ScheduleCache, init_db

logger = setup_logging()
app_logger = logging.getLogger("werkzeug")
app_logger.setLevel(logging.ERROR)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///anime_manager.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

init_db(app)

download_manager = get_download_manager()


def get_animes_from_db(status=None):
    if status:
        return [a.to_dict() for a in Anime.get_by_status(status)]
    return [a.to_dict() for a in Anime.query.all()]


def sync_anilist_to_db():
    logger.info("[SYNC] Starting AniList sync to database...")
    
    anime_sync_success = False
    try:
        for status in ["CURRENT", "PLANNING", "COMPLETED"]:
            data = logic.get_anilist_data(status=status)
            for anime_data in data:
                with app.app_context():
                    anime = Anime.upsert_from_anilist(anime_data)
                    anime.status = status
                    
                    nom_dossier = anime_data.get('nom_dossier')
                    if nom_dossier:
                        anime_dir = os.path.join(get_anime_dir(), nom_dossier)
                        if os.path.exists(anime_dir):
                            cover_jpg = os.path.join(anime_dir, "cover.jpg")
                            cover_png = os.path.join(anime_dir, "cover.png")
                            if os.path.exists(cover_jpg):
                                anime.cover_local = f"/api/cleanup/cover?path={nom_dossier}"
                            elif os.path.exists(cover_png):
                                anime.cover_local = f"/api/cleanup/cover?path={nom_dossier}"
                    db.session.commit()
                    logic.cache_cover(anime_data)
        anime_sync_success = True
        logger.info("[SYNC] Anime sync completed")
    except requests.exceptions.ConnectionError as e:
        logger.error(f"[SYNC] No internet connection during anime sync: {e}")
    except Exception as e:
        logger.error(f"[SYNC] Failed to sync animes: {e}")
    
    try:
        logger.info("[SYNC] Fetching airing schedule...")
        schedule_data = logic.get_airing_schedule()
        logger.info(f"[SYNC] Fetched {len(schedule_data) if schedule_data else 0} days of schedule from AniList")
        if schedule_data:
            ScheduleCache.save_schedule(schedule_data)
            logger.info("[SYNC] Airing schedule cached successfully.")
        else:
            logger.warning("[SYNC] No schedule data returned from AniList")
    except Exception as e:
        logger.error(f"[SYNC] Failed to cache schedule: {e}")
    
    if anime_sync_success:
        logger.info("[SYNC] Full sync completed")
        return True
    return False


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/api/health")
def health_check():
    return jsonify({
        "status": "ok",
        "db_counts": {
            "watching": Anime.query.filter_by(status='CURRENT').count(),
            "planning": Anime.query.filter_by(status='PLANNING').count(),
            "completed": Anime.query.filter_by(status='COMPLETED').count(),
        },
        "downloads": download_manager.get_status()
    })


@app.route("/en")
def index_en():
    animes = get_animes_from_db("CURRENT")
    return render_template("index.html", animes=animes, view_mode="watching")


@app.route("/en/planning")
def planning_en():
    animes = get_animes_from_db("PLANNING")
    return render_template("index.html", animes=animes, view_mode="planning")


@app.route("/en/suggestions")
def suggestions_en():
    animes = get_animes_from_db("COMPLETED")
    return render_template("index.html", animes=animes, view_mode="suggestions")


@app.route("/fr")
def index_fr():
    animes = get_animes_from_db("CURRENT")
    return render_template("fr_index.html", animes=animes, view_mode="watching")


@app.route("/fr/planning")
def planning_fr():
    animes = get_animes_from_db("PLANNING")
    return render_template("fr_index.html", animes=animes, view_mode="planning")


@app.route("/fr/suggestions")
def suggestions_fr():
    animes = get_animes_from_db("COMPLETED")
    return render_template("fr_index.html", animes=animes, view_mode="suggestions")


@app.route("/anilist")
def anilist_index():
    animes = get_animes_from_db("CURRENT")
    return render_template("anilist_index.html", animes=animes, view_mode="watching")


@app.route("/anilist/planning")
def anilist_planning():
    animes = get_animes_from_db("PLANNING")
    return render_template("anilist_index.html", animes=animes, view_mode="planning")


@app.route("/anilist/completed")
def anilist_completed():
    animes = get_animes_from_db("COMPLETED")
    return render_template("anilist_index.html", animes=animes, view_mode="completed")


@app.route("/anilist/season")
def anilist_season():
    animes = get_animes_from_db("COMPLETED")
    return render_template("anilist_index.html", animes=animes, view_mode="season")


@app.route("/anilist/search")
def anilist_search():
    return render_template("anilist_index.html", animes=[], view_mode="search")


@app.route("/api/anilist/search_db", methods=["POST"])
def api_anilist_search_db():
    query = request.json.get("query")
    return jsonify(logic.search_anilist(query))


@app.route("/refresh")
def refresh():
    referrer = request.referrer or "/"
    threading.Thread(target=sync_anilist_to_db, daemon=True).start()
    return redirect(referrer)


@app.route("/api/details/<nom_dossier>")
def get_details(nom_dossier):
    logger.info(f"[API] /api/details/{nom_dossier}")
    
    anime = Anime.get_by_dossier(nom_dossier)
    if not anime:
        return jsonify({"error": "Anime introuvable"}), 404
    
    anime_dict = anime.to_dict()
    
    try:
        details = logic.get_anime_details(anime_dict)
    except Exception as e:
        logger.error(f"[API] Error getting anime details: {e}")
        return jsonify({"error": str(e)}), 500
    
    active_downloads = download_manager.get_active_downloads()
    active_keys = {ad["key"] for ad in active_downloads}
    for d in details:
        key = f"{nom_dossier}_{d['ep']}"
        if key in active_keys:
            d["status"] = "downloading"
    
    return jsonify({
        "id": anime.anilist_id,
        "nom_complet": anime.nom_complet,
        "nom_dossier": anime.nom_dossier,
        "total": anime.total_episodes,
        "lien": anime.lien,
        "episodes": details,
        "progress": anime.progress,
    })


@app.route("/api/bulk_download", methods=["POST"])
def bulk_download():
    data = request.json
    nom_dossier = data.get("nom_dossier")
    anime = Anime.get_by_dossier(nom_dossier)
    
    if anime:
        anime_dict = anime.to_dict()
        task = DownloadTask(
            anime_data=anime_dict,
            episodes=data.get("episodes"),
            source=DownloadSource.ENGLISH,
        )
        download_manager.add_task(task)
        return jsonify({"status": "started", "count": len(data.get("episodes"))})
    return jsonify({"error": "Anime introuvable"}), 404


@app.route("/api/bulk_delete", methods=["POST"])
def bulk_delete():
    count = logic.delete_episodes(request.json.get("nom_dossier"), request.json.get("episodes"))
    return jsonify({"status": "deleted", "count": count})


@app.route("/api/downloads/status")
def downloads_status():
    status = download_manager.get_status()
    return jsonify(status)


@app.route("/api/downloads/stream")
def downloads_stream():
    def event_stream():
        event = download_manager.subscribe()
        try:
            while True:
                event.wait(timeout=60)
                if event.is_set():
                    event.clear()
                    status = download_manager.get_status()
                    yield f"data: {status}\n\n"
        except GeneratorExit:
            download_manager.unsubscribe(event)
        except Exception as e:
            logger.error(f"[SSE] Error: {e}")
            download_manager.unsubscribe(event)

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/watch/<nom_dossier>/<int:episode>")
def watch_page(nom_dossier, episode):
    anime = Anime.get_by_dossier(nom_dossier)
    if not anime:
        return redirect(url_for("index_en"))
    
    total = anime.total_episodes
    sortie = anime.released_episodes
    
    has_prev = episode > 1
    has_next = episode < sortie
    is_last = episode == sortie
    
    prev_episode = episode - 1 if has_prev else None
    next_episode = episode + 1 if has_next else None
    
    anime_title = anime.title_romaji or anime.nom_dossier
    
    return render_template(
        "watch.html",
        nom_dossier=nom_dossier,
        episode=episode,
        anime_title=anime_title,
        current_progress=anime.progress,
        total_episodes=total,
        has_prev=has_prev,
        has_next=has_next,
        is_last=is_last,
        prev_episode=prev_episode,
        next_episode=next_episode,
    )


@app.route("/api/watch/stream/<nom_dossier>/<int:episode>")
def stream_video(nom_dossier, episode):
    anime_dir = get_anime_dir()
    path = os.path.join(anime_dir, nom_dossier, f"{episode}.mp4")
    
    if not os.path.exists(path):
        return "Fichier non trouvé", 404
    
    file_size = os.path.getsize(path)
    mime_type = mimetypes.guess_type(path)[0] or "video/mp4"
    
    range_header = request.headers.get("Range")
    
    if range_header:
        try:
            range_match = range_header.replace("bytes=", "").split("-")
            byte_start = int(range_match[0]) if range_match[0] else 0
            byte_end = int(range_match[1]) if range_match[1] else min(byte_start + (1024 * 1024 * 10), file_size - 1)
        except (ValueError, IndexError):
            byte_start = 0
            byte_end = min(file_size - 1, 1024 * 1024 * 10)
        
        length = byte_end - byte_start + 1
        
        def generate():
            try:
                with open(path, "rb") as f:
                    f.seek(byte_start)
                    remaining = length
                    while remaining > 0:
                        chunk_size = min(65536, remaining)
                        data = f.read(chunk_size)
                        if not data:
                            break
                        remaining -= len(data)
                        yield data
            except IOError as e:
                logging.error(f"Error streaming video: {e}")
        
        response = Response(generate(), 206)
        response.headers["Content-Range"] = f"bytes {byte_start}-{byte_end}/{file_size}"
        response.headers["Accept-Ranges"] = "bytes"
        response.headers["Content-Length"] = length
        response.headers["Content-Type"] = mime_type
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response
    else:
        def generate():
            try:
                with open(path, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        yield chunk
            except IOError as e:
                logging.error(f"Error streaming video: {e}")
        
        response = Response(generate(), 200)
        response.headers["Content-Length"] = file_size
        response.headers["Content-Type"] = mime_type
        response.headers["Accept-Ranges"] = "bytes"
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response


@app.route("/api/watch/<nom_dossier>/<int:episode>")
def watch_api(nom_dossier, episode):
    return jsonify({"success": logic.open_local_file(nom_dossier, episode)})


@app.route("/api/delete_anime", methods=["POST"])
def delete_anime():
    nom_dossier = request.json.get("nom_dossier")
    logic.delete_all_episodes(nom_dossier)
    return jsonify({"success": True})


@app.route("/api/complete_season", methods=["POST"])
def api_complete_season():
    nom_dossier = request.json.get("nom_dossier")
    anime = Anime.get_by_dossier(nom_dossier)
    
    if anime:
        anime.status = 'COMPLETED'
        anime.progress = anime.total_episodes
        anime.touch()
        
        threading.Thread(
            target=logic.update_anilist_entry,
            args=(anime.anilist_id, anime.total_episodes, anime.total_episodes),
        ).start()
        
        logic.delete_all_episodes(nom_dossier)
    
    return jsonify({"success": True})


@app.route("/api/update_progress", methods=["POST"])
def api_update_progress():
    data = request.json
    nom_dossier = data.get("nom_dossier")
    current_episode = data.get("current_episode")
    media_id = data.get("media_id")
    total_episodes = data.get("total_episodes")
    
    anime = Anime.get_by_dossier(nom_dossier) if nom_dossier else None
    
    if anime and current_episode:
        anime.update_progress(current_episode)
    
    if media_id and current_episode:
        threading.Thread(
            target=logic.update_anilist_entry,
            args=(media_id, current_episode, total_episodes),
        ).start()
    
    return jsonify({"success": True})


@app.route("/api/sync_anilist", methods=["POST"])
def sync_anilist():
    d = request.json
    media_id = d.get("media_id")
    last_episode = d.get("last_episode")
    total_episodes = d.get("total_episodes")
    
    if media_id:
        anime = Anime.query.filter_by(anilist_id=media_id).first()
        if anime:
            anime.update_progress(last_episode)
    
    threading.Thread(
        target=logic.update_anilist_entry,
        args=(media_id, last_episode, total_episodes),
    ).start()
    
    return jsonify({"status": "sync_started"})


@app.route("/api/change_status", methods=["POST"])
def change_status():
    media_id = request.json.get("media_id")
    new_status = request.json.get("status", "CURRENT")
    
    anime = Anime.query.filter_by(anilist_id=media_id).first() if media_id else None
    if anime:
        anime.status = new_status
        anime.touch()
    
    logic.update_anilist_status(media_id, new_status)
    return jsonify({"success": True})


@app.route("/api/fr/local_details/<nom_dossier_base>")
def fr_local_details(nom_dossier_base):
    anime = Anime.get_by_dossier(nom_dossier_base)
    
    nom_dossier_fr = f"{nom_dossier_base}_FR"
    anime_dir = get_anime_dir()
    path = os.path.join(anime_dir, nom_dossier_fr)
    
    episodes = []
    if os.path.exists(path):
        for f in os.listdir(path):
            if f.endswith(".mp4"):
                try:
                    episodes.append(int(f.replace(".mp4", "")))
                except ValueError:
                    pass
    
    progress = anime.progress if anime else 0
    detail_list = [{"ep": ep, "status": "watched_kept" if ep <= progress else "downloaded"} for ep in episodes]
    
    return jsonify({
        "nom_dossier_fr": nom_dossier_fr,
        "progress": progress,
        "id": anime.anilist_id if anime else None,
        "total": anime.total_episodes if anime else None,
        "episodes": detail_list,
    })


@app.route("/api/fr/search", methods=["POST"])
def fr_search():
    return jsonify(logic_fr.search_anime_sama(request.json.get("query")))


@app.route("/api/fr/details", methods=["POST"])
def fr_details():
    return jsonify(logic_fr.get_anime_sama_details(request.json.get("url")))


@app.route("/api/fr/bulk_download", methods=["POST"])
def fr_bulk_download():
    data = request.json
    task = DownloadTask(
        anime_data={"nom_dossier": data.get("nom_dossier"), "nom_complet": data.get("nom_dossier")},
        episodes=list(data.get("episodes_urls", {}).keys()),
        source=DownloadSource.FRENCH,
    )
    logic_fr.add_to_queue_fr(data.get("nom_dossier"), data.get("episodes_urls"))
    return jsonify({"status": "started"})


@app.route("/downloads")
def downloads_page():
    return render_template("downloads.html")


@app.route("/api/downloads/dashboard")
def downloads_dashboard():
    animes = [a.to_dict() for a in Anime.query.filter(Anime.status.in_(['CURRENT', 'PLANNING'])).all()]
    
    active_downloads = download_manager.get_active_downloads()
    available_by_anime = {}
    
    anime_dir = get_anime_dir()
    for anime in animes:
        nom_dossier = anime["nom_dossier"]
        progress = anime.get("progress", 0)
        sortie = anime.get("sortie", 0)
        path = os.path.join(anime_dir, nom_dossier)
        
        existing_eps = set()
        local_cover = anime.get("img")
        if os.path.exists(path):
            existing_eps = {int(f.replace(".mp4", "")) for f in os.listdir(path) if f.endswith(".mp4")}
        
        available_eps = [ep for ep in range(1, sortie + 1) if ep not in existing_eps and ep > progress]
        
        if available_eps:
            available_by_anime[nom_dossier] = {
                "nom_dossier": nom_dossier,
                "nom_complet": anime["nom_complet"],
                "episodes": sorted(available_eps),
                "img": anime["img"],
                "local_cover": local_cover
            }
    
    return jsonify({
        "active": active_downloads,
        "available": list(available_by_anime.values())
    })


@app.route("/schedule")
def schedule_page():
    return render_template("schedule.html")


@app.route("/api/schedule")
def api_schedule():
    try:
        schedule_data = ScheduleCache.get_schedule()
        if not schedule_data:
            logger.warning("[SCHEDULE] No cache found, returning empty list")
            return jsonify({"success": True, "schedule": []})
        return jsonify({"success": True, "schedule": schedule_data})
    except Exception as e:
        logger.error(f"Failed to fetch schedule: {e}")
        return jsonify({"success": True, "schedule": []})


@app.route("/cleanup")
def cleanup_page():
    return render_template("cleanup.html")


@app.route("/api/cleanup/scan")
def cleanup_scan():
    try:
        watching_folders = [a.nom_dossier for a in Anime.query.filter_by(status='CURRENT').all() if a.nom_dossier]
        planning_folders = [a.nom_dossier for a in Anime.query.filter_by(status='PLANNING').all() if a.nom_dossier]
        completed_folders = [a.nom_dossier for a in Anime.query.filter_by(status='COMPLETED').all() if a.nom_dossier]
        
        result = logic.scan_cleanup(watching_folders, planning_folders, completed_folders)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        logger.error(f"Cleanup scan failed: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/cleanup/delete", methods=["POST"])
def cleanup_delete():
    folders = request.json.get("folders", [])
    deleted = []
    anime_dir = get_anime_dir()
    for folder in folders:
        try:
            path = os.path.join(anime_dir, folder)
            if os.path.exists(path):
                import shutil
                shutil.rmtree(path)
                deleted.append(folder)
        except Exception as e:
            logger.error(f"Failed to delete {folder}: {e}")
    return jsonify({"success": True, "deleted": deleted})


@app.route("/api/cleanup/cover")
def cleanup_cover():
    folder_name = request.args.get("path", "")
    anime_dir = get_anime_dir()
    folder_path = os.path.join(anime_dir, folder_name)
    
    cover_jpg = os.path.join(folder_path, "cover.jpg")
    cover_png = os.path.join(folder_path, "cover.png")
    
    if os.path.exists(cover_jpg):
        return send_file(cover_jpg)
    elif os.path.exists(cover_png):
        return send_file(cover_png)
    
    anime = Anime.get_by_dossier(folder_name)
    if anime and anime.cover_image:
        return redirect(anime.cover_image)
    
    return "", 404


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Anime Manager Pro - Web Server Starting")
    logger.info("=" * 50)
    logger.info(f"Anime directory: {get_anime_dir()}")
    logger.info(f"Database: sqlite:///anime_manager.db")
    logger.info(f"Flask server: http://{get_flask_host()}:{get_flask_port()}")
    logger.info("=" * 50)
    
    with app.app_context():
        if Anime.query.count() == 0:
            logger.info("Database empty, running initial sync...")
            sync_anilist_to_db()
        else:
            logger.info("Database already populated, running schedule sync...")
            try:
                schedule_data = logic.get_airing_schedule()
                if schedule_data:
                    logger.info(f"[STARTUP] Fetched {len(schedule_data)} days of schedule from AniList")
                    ScheduleCache.save_schedule(schedule_data)
                    logger.info("[STARTUP] Schedule cached successfully")
                else:
                    logger.warning("[STARTUP] No schedule data returned from AniList")
            except Exception as e:
                logger.error(f"[STARTUP] Failed to cache schedule on startup: {e}")
    
    app.run(
        debug=get_flask_debug(),
        host=get_flask_host(),
        port=get_flask_port(),
        threaded=True,
    )