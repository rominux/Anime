import os
import sys
import time
import logging
from flask import Flask, render_template, request, redirect, url_for, jsonify, Response, stream_with_context, send_file
import mimetypes
import threading

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

logger = setup_logging()
app_logger = logging.getLogger("werkzeug")
app_logger.setLevel(logging.ERROR)

app = Flask(__name__, template_folder="templates", static_folder="static")

download_manager = get_download_manager()

CACHE_WATCHING = []
CACHE_PLANNING = []
CACHE_SUGGESTIONS = []
CACHE_COMPLETED = []


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/api/health")
def health_check():
    return jsonify({
        "status": "ok",
        "cache_sizes": {
            "watching": len(CACHE_WATCHING),
            "planning": len(CACHE_PLANNING),
            "suggestions": len(CACHE_SUGGESTIONS),
            "completed": len(CACHE_COMPLETED),
        },
        "downloads": download_manager.get_status()
    })


@app.route("/en")
def index_en():
    global CACHE_WATCHING
    logger.info("[ROUTE] /en - Loading watching list")
    if not CACHE_WATCHING:
        logger.info("[ROUTE] Cache empty, fetching from AniList...")
        try:
            CACHE_WATCHING = logic.get_anilist_data(status="CURRENT")
            logic.cache_all_covers(CACHE_WATCHING)
        except Exception as e:
            logger.error(f"[ROUTE] Failed to fetch from AniList: {e}")
            CACHE_WATCHING = []
        logger.info(f"[ROUTE] Fetched {len(CACHE_WATCHING)} anime from AniList")
    return render_template("index.html", animes=CACHE_WATCHING, view_mode="watching")


@app.route("/en/planning")
def planning_en():
    global CACHE_PLANNING
    logger.info("[ROUTE] /en/planning - Loading planning list")
    if not CACHE_PLANNING:
        try:
            CACHE_PLANNING = logic.get_anilist_data(status="PLANNING")
            logic.cache_all_covers(CACHE_PLANNING)
        except Exception as e:
            logger.error(f"[ROUTE] Failed to fetch planning: {e}")
            CACHE_PLANNING = []
    return render_template("index.html", animes=CACHE_PLANNING, view_mode="planning")


@app.route("/en/suggestions")
def suggestions_en():
    global CACHE_SUGGESTIONS
    logger.info("[ROUTE] /en/suggestions - Loading suggestions")
    if not CACHE_SUGGESTIONS:
        try:
            CACHE_SUGGESTIONS = logic.get_seasonal_suggestions()
            logic.cache_all_covers(CACHE_SUGGESTIONS)
        except Exception as e:
            logger.error(f"[ROUTE] Failed to fetch suggestions: {e}")
            CACHE_SUGGESTIONS = []
    return render_template("index.html", animes=CACHE_SUGGESTIONS, view_mode="suggestions")


@app.route("/fr")
def index_fr():
    global CACHE_WATCHING
    if not CACHE_WATCHING:
        try:
            CACHE_WATCHING = logic.get_anilist_data(status="CURRENT")
            logic.cache_all_covers(CACHE_WATCHING)
        except Exception as e:
            logger.error(f"[ROUTE] Failed to fetch from AniList: {e}")
            CACHE_WATCHING = []
    return render_template("fr_index.html", animes=CACHE_WATCHING, view_mode="watching")


@app.route("/fr/planning")
def planning_fr():
    global CACHE_PLANNING
    if not CACHE_PLANNING:
        try:
            CACHE_PLANNING = logic.get_anilist_data(status="PLANNING")
            logic.cache_all_covers(CACHE_PLANNING)
        except Exception as e:
            logger.error(f"[ROUTE] Failed to fetch planning: {e}")
            CACHE_PLANNING = []
    return render_template("fr_index.html", animes=CACHE_PLANNING, view_mode="planning")


@app.route("/fr/suggestions")
def suggestions_fr():
    global CACHE_SUGGESTIONS
    if not CACHE_SUGGESTIONS:
        try:
            CACHE_SUGGESTIONS = logic.get_seasonal_suggestions()
            logic.cache_all_covers(CACHE_SUGGESTIONS)
        except Exception as e:
            logger.error(f"[ROUTE] Failed to fetch suggestions: {e}")
            CACHE_SUGGESTIONS = []
    return render_template("fr_index.html", animes=CACHE_SUGGESTIONS, view_mode="suggestions")


@app.route("/anilist")
def anilist_index():
    global CACHE_WATCHING
    if not CACHE_WATCHING:
        try:
            CACHE_WATCHING = logic.get_anilist_data(status="CURRENT")
            logic.cache_all_covers(CACHE_WATCHING)
        except Exception as e:
            logger.error(f"[ROUTE] Failed to fetch from AniList: {e}")
            CACHE_WATCHING = []
    return render_template("anilist_index.html", animes=CACHE_WATCHING, view_mode="watching")


@app.route("/anilist/planning")
def anilist_planning():
    global CACHE_PLANNING
    if not CACHE_PLANNING:
        try:
            CACHE_PLANNING = logic.get_anilist_data(status="PLANNING")
            logic.cache_all_covers(CACHE_PLANNING)
        except Exception as e:
            logger.error(f"[ROUTE] Failed to fetch planning: {e}")
            CACHE_PLANNING = []
    return render_template("anilist_index.html", animes=CACHE_PLANNING, view_mode="planning")


@app.route("/anilist/completed")
def anilist_completed():
    global CACHE_COMPLETED
    if not CACHE_COMPLETED:
        try:
            CACHE_COMPLETED = logic.get_anilist_data(status="COMPLETED")
            logic.cache_all_covers(CACHE_COMPLETED)
        except Exception as e:
            logger.error(f"[ROUTE] Failed to fetch completed: {e}")
            CACHE_COMPLETED = []
    return render_template("anilist_index.html", animes=CACHE_COMPLETED, view_mode="completed")


@app.route("/anilist/season")
def anilist_season():
    global CACHE_SUGGESTIONS
    if not CACHE_SUGGESTIONS:
        try:
            CACHE_SUGGESTIONS = logic.get_seasonal_suggestions()
            logic.cache_all_covers(CACHE_SUGGESTIONS)
        except Exception as e:
            logger.error(f"[ROUTE] Failed to fetch seasonal: {e}")
            CACHE_SUGGESTIONS = []
    return render_template("anilist_index.html", animes=CACHE_SUGGESTIONS, view_mode="season")


@app.route("/anilist/search")
def anilist_search():
    return render_template("anilist_index.html", animes=[], view_mode="search")


@app.route("/api/anilist/search_db", methods=["POST"])
def api_anilist_search_db():
    query = request.json.get("query")
    return jsonify(logic.search_anilist(query))


@app.route("/refresh")
def refresh():
    global CACHE_WATCHING, CACHE_PLANNING, CACHE_SUGGESTIONS, CACHE_COMPLETED
    referrer = request.referrer or "/"

    if "planning" in referrer:
        try:
            CACHE_PLANNING = logic.get_anilist_data(status="PLANNING")
            logic.cache_all_covers(CACHE_PLANNING)
        except Exception:
            pass
    elif "suggestions" in referrer or "season" in referrer:
        try:
            CACHE_SUGGESTIONS = logic.get_seasonal_suggestions()
            logic.cache_all_covers(CACHE_SUGGESTIONS)
        except Exception:
            pass
    elif "completed" in referrer:
        try:
            CACHE_COMPLETED = logic.get_anilist_data(status="COMPLETED")
            logic.cache_all_covers(CACHE_COMPLETED)
        except Exception:
            pass
    else:
        try:
            CACHE_WATCHING = logic.get_anilist_data(status="CURRENT")
            logic.cache_all_covers(CACHE_WATCHING)
        except Exception:
            pass

    return redirect(referrer)


@app.route("/api/details/<nom_dossier>")
def get_details(nom_dossier):
    global CACHE_WATCHING, CACHE_PLANNING, CACHE_SUGGESTIONS, CACHE_COMPLETED
    
    logger.info(f"[API] /api/details/{nom_dossier} - Looking up anime details")
    
    if not CACHE_WATCHING:
        try:
            CACHE_WATCHING = logic.get_anilist_data(status="CURRENT")
            logger.info(f"[API] Fetched {len(CACHE_WATCHING)} from CURRENT")
        except Exception as e:
            logger.error(f"[API] Failed to fetch CURRENT: {e}")
    
    if not CACHE_PLANNING:
        try:
            CACHE_PLANNING = logic.get_anilist_data(status="PLANNING")
            logger.info(f"[API] Fetched {len(CACHE_PLANNING)} from PLANNING")
        except Exception as e:
            logger.error(f"[API] Failed to fetch PLANNING: {e}")
    
    logger.info(f"[API] Cache sizes - WATCHING: {len(CACHE_WATCHING)}, PLANNING: {len(CACHE_PLANNING)}, SUGGESTIONS: {len(CACHE_SUGGESTIONS)}, COMPLETED: {len(CACHE_COMPLETED)}")

    all_animes = CACHE_WATCHING + CACHE_PLANNING + CACHE_SUGGESTIONS + CACHE_COMPLETED
    anime = next((a for a in all_animes if a["nom_dossier"] == nom_dossier), None)

    if not anime:
        logger.warning(f"[API] Anime not found in cache: {nom_dossier}")
        return jsonify({"error": "Anime introuvable"}), 404

    logger.info(f"[API] Found anime: {anime['nom_complet'][:50]}")

    try:
        details = logic.get_anime_details(anime)
        logger.info(f"[API] Got episode details: {len(details)} episodes")
    except Exception as e:
        logger.error(f"[API] Error getting anime details: {e}")
        return jsonify({"error": str(e)}), 500

    active_downloads = download_manager.get_active_downloads()
    active_keys = {ad["key"] for ad in active_downloads}
    for d in details:
        key = f"{nom_dossier}_{d['ep']}"
        if key in active_keys:
            d["status"] = "downloading"

    result = {
        "id": anime["id"],
        "nom_complet": anime["nom_complet"],
        "nom_dossier": anime["nom_dossier"],
        "total": anime["total"],
        "lien": anime["lien"],
        "episodes": details,
        "progress": anime["progress"],
    }
    import json
    result_str = json.dumps(result)
    logger.info(f"[API] Returning details for {nom_dossier} - {len(result_str)} bytes")
    return jsonify(result)


@app.route("/api/bulk_download", methods=["POST"])
def bulk_download():
    data = request.json
    all_animes = CACHE_WATCHING + CACHE_PLANNING + CACHE_SUGGESTIONS
    anime_obj = next((a for a in all_animes if a["nom_dossier"] == data.get("nom_dossier")), None)
    if anime_obj:
        task = DownloadTask(
            anime_data=anime_obj,
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
    logger.info("[SSE] New SSE connection opened")
    sub_count = len(download_manager._subscribers)
    logger.info(f"[SSE] Current subscribers: {sub_count}")

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
            logger.info("[SSE] SSE connection closed by client")
            download_manager.unsubscribe(event)
        except Exception as e:
            logger.error(f"[SSE] Error in SSE stream: {e}")
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
    all_animes = CACHE_WATCHING + CACHE_PLANNING + CACHE_SUGGESTIONS + CACHE_COMPLETED
    anime = next((a for a in all_animes if a["nom_dossier"] == nom_dossier), None)
    if not anime:
        return redirect(url_for("index_en"))

    total = anime["total"]
    sortie = anime["sortie"]

    has_prev = episode > 1
    has_next = episode < sortie

    is_last = episode == sortie

    prev_episode = episode - 1 if has_prev else None
    next_episode = episode + 1 if has_next else None

    anime_title = anime["nom_complet"].split(" ;;; ")[0]

    return render_template(
        "watch.html",
        nom_dossier=nom_dossier,
        episode=episode,
        anime_title=anime_title,
        current_progress=anime["progress"],
        total_episodes=anime["total"],
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

            if range_match[1]:
                byte_end = int(range_match[1])
            else:
                byte_end = min(byte_start + (1024 * 1024 * 10), file_size - 1)
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
        response.headers["Access-Control-Expose-Headers"] = "Content-Range"
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


@app.route("/api/anime_list")
def anime_list():
    global CACHE_WATCHING, CACHE_PLANNING
    all_animes = CACHE_WATCHING + CACHE_PLANNING
    result = []
    seen_folders = set()
    anime_dir = get_anime_dir()

    if os.path.exists(anime_dir):
        for folder in os.listdir(anime_dir):
            folder_path = os.path.join(anime_dir, folder)
            if not os.path.isdir(folder_path):
                continue
            if not any(f.endswith(".mp4") for f in os.listdir(folder_path)):
                continue
            if folder in seen_folders:
                continue
            seen_folders.add(folder)

            base_nom_dossier = folder.replace("_FR", "")
            anime = next(
                (
                    a
                    for a in all_animes
                    if a["nom_dossier"] == base_nom_dossier or a["nom_dossier"] == folder
                ),
                None,
            )

            if anime:
                result.append(
                    {
                        "id": anime["id"],
                        "nom_complet": anime["nom_complet"],
                        "nom_dossier": anime["nom_dossier"],
                        "progress": anime["progress"],
                        "total": anime["total"],
                        "sortie": anime["sortie"],
                        "img": anime["img"],
                    }
                )

    return jsonify(result)


@app.route("/api/delete_anime", methods=["POST"])
def delete_anime():
    nom_dossier = request.json.get("nom_dossier")
    logic.delete_all_episodes(nom_dossier)
    return jsonify({"success": True})


@app.route("/api/complete_season", methods=["POST"])
def api_complete_season():
    global CACHE_WATCHING, CACHE_PLANNING, CACHE_COMPLETED
    nom_dossier = request.json.get("nom_dossier")
    all_animes = CACHE_WATCHING + CACHE_PLANNING
    anime = next((a for a in all_animes if a["nom_dossier"] == nom_dossier), None)

    if anime:
        logic.update_anilist_entry(anime["id"], anime["total"], anime["total"])
        logic.delete_all_episodes(nom_dossier)

    CACHE_WATCHING, CACHE_PLANNING, CACHE_COMPLETED = [], [], []

    return jsonify({"success": True})


@app.route("/api/update_progress", methods=["POST"])
def api_update_progress():
    data = request.json
    nom_dossier = data.get("nom_dossier")
    current_episode = data.get("current_episode")
    media_id = data.get("media_id")
    total_episodes = data.get("total_episodes")

    if nom_dossier and current_episode:
        logic.delete_episodes_before(nom_dossier, current_episode)

    if media_id and current_episode:
        threading.Thread(
            target=logic.update_anilist_entry,
            args=(media_id, current_episode, total_episodes),
        ).start()

    return jsonify({"success": True})


@app.route("/api/sync_anilist", methods=["POST"])
def sync_anilist():
    d = request.json
    threading.Thread(
        target=logic.update_anilist_entry,
        args=(d.get("media_id"), d.get("last_episode"), d.get("total_episodes")),
    ).start()
    return jsonify({"status": "sync_started"})


@app.route("/api/change_status", methods=["POST"])
def change_status():
    logic.update_anilist_status(request.json.get("media_id"), request.json.get("status", "CURRENT"))
    global CACHE_WATCHING, CACHE_PLANNING, CACHE_COMPLETED
    CACHE_WATCHING, CACHE_PLANNING, CACHE_COMPLETED = [], [], []
    return jsonify({"success": True})


@app.route("/api/fr/local_details/<nom_dossier_base>")
def fr_local_details(nom_dossier_base):
    global CACHE_WATCHING, CACHE_PLANNING, CACHE_SUGGESTIONS, CACHE_COMPLETED
    all_animes = CACHE_WATCHING + CACHE_PLANNING + CACHE_SUGGESTIONS + CACHE_COMPLETED
    anime = next((a for a in all_animes if a["nom_dossier"] == nom_dossier_base), None)

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

    progress = anime["progress"] if anime else 0
    detail_list = []
    for ep in episodes:
        status = "watched_kept" if ep <= progress else "downloaded"
        detail_list.append({"ep": ep, "status": status})

    return jsonify({
        "nom_dossier_fr": nom_dossier_fr,
        "progress": progress,
        "id": anime["id"] if anime else None,
        "total": anime["total"] if anime else None,
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
    global CACHE_WATCHING, CACHE_PLANNING
    
    if not CACHE_WATCHING:
        try:
            CACHE_WATCHING = logic.get_anilist_data(status="CURRENT")
        except:
            pass
    
    if not CACHE_PLANNING:
        try:
            CACHE_PLANNING = logic.get_anilist_data(status="PLANNING")
        except:
            pass
    
    active_downloads = download_manager.get_active_downloads()
    
    all_animes = CACHE_WATCHING + CACHE_PLANNING
    available_by_anime = {}
    
    anime_dir = get_anime_dir()
    for anime in all_animes:
        nom_dossier = anime["nom_dossier"]
        progress = anime.get("progress", 0)
        sortie = anime.get("sortie", 0)
        path = os.path.join(anime_dir, nom_dossier)
        
        existing_eps = set()
        local_cover = None
        if os.path.exists(path):
            existing_eps = {int(f.replace(".mp4", "")) for f in os.listdir(path) if f.endswith(".mp4")}
            cover_jpg = os.path.join(path, "cover.jpg")
            cover_png = os.path.join(path, "cover.png")
            if os.path.exists(cover_jpg):
                local_cover = f"/api/cleanup/cover?path={nom_dossier}"
            elif os.path.exists(cover_png):
                local_cover = f"/api/cleanup/cover?path={nom_dossier}"
        
        available_eps = []
        for ep in range(1, sortie + 1):
            if ep in existing_eps:
                continue
            if ep <= progress:
                continue
            available_eps.append(ep)
        
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
        schedule_data = logic.get_airing_schedule()
        return jsonify({"success": True, "schedule": schedule_data})
    except Exception as e:
        logger.error(f"Failed to fetch schedule: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route("/cleanup")
def cleanup_page():
    return render_template("cleanup.html")


@app.route("/api/cleanup/scan")
def cleanup_scan():
    try:
        result = logic.scan_cleanup()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        logger.error(f"Cleanup scan failed: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/cleanup/delete", methods=["POST"])
def cleanup_delete():
    folders = request.json.get("folders", [])
    deleted = []
    for folder in folders:
        try:
            anime_dir = get_anime_dir()
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
    logger.info(f"Flask server: http://{get_flask_host()}:{get_flask_port()}")
    logger.info("=" * 50)

    app.run(
        debug=get_flask_debug(),
        host=get_flask_host(),
        port=get_flask_port(),
        threaded=True,
    )