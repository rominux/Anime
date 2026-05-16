import os
import threading
import logging
import traceback
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify, send_file
from dotenv import load_dotenv

load_dotenv()

logging.getLogger('werkzeug').setLevel(logging.ERROR)

import logic
from models import db, Anime, ScheduleCache, SuggestionsCache, init_db

app = Flask(__name__)
instance_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance')
os.makedirs(instance_dir, exist_ok=True)
db_path = os.path.join(instance_dir, 'anime_manager.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

init_db(app)

ANILIST_USERNAME = os.getenv('ANILIST_USERNAME', '')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/animes')
def api_animes():
    status = request.args.get('status', 'CURRENT')
    animes = Anime.query.filter_by(status=status).order_by(Anime.updated_at.desc()).all()
    result = []
    for a in animes:
        d = a.to_dict()
        anime_dir = os.path.join(logic.ANIME_DIR, a.nom_dossier) if a.nom_dossier else None
        has_downloads = False
        downloaded_set = set()
        if anime_dir and os.path.exists(anime_dir):
            for f in os.listdir(anime_dir):
                if f.endswith('.mp4'):
                    has_downloads = True
                    try:
                        downloaded_set.add(int(f.removesuffix('.mp4')))
                    except ValueError:
                        pass
        d['has_downloads'] = has_downloads
        rel = a.released_episodes or 0
        prog = a.progress or 0
        d['can_download'] = rel > prog and any(i not in downloaded_set for i in range(prog + 1, rel + 1))
        result.append(d)
    return jsonify(result)

@app.route('/api/animes_suggestions')
def api_animes_suggestions():
    suggestions = SuggestionsCache.get_suggestions()
    if suggestions is None:
        suggestions = logic.get_seasonal_suggestions()
        if suggestions:
            SuggestionsCache.save_suggestions(suggestions)
    return jsonify(suggestions or [])

@app.route('/api/details_suggestions/<nom_dossier>')
def details_suggestions(nom_dossier):
    suggestions = SuggestionsCache.get_suggestions()
    if suggestions is None:
        suggestions = logic.get_seasonal_suggestions()
        if suggestions:
            SuggestionsCache.save_suggestions(suggestions)
    anime = next((a for a in (suggestions or []) if a['nom_dossier'] == nom_dossier), None)
    if not anime:
        return jsonify({"error": "Anime introuvable"}), 404
    details = logic.get_anime_details(anime)
    return jsonify({
        "id": anime['id'],
        "nom_complet": anime['nom_complet'],
        "nom_dossier": anime['nom_dossier'],
        "total": anime['total'],
        "lien": anime['lien'],
        "episodes": details,
        "progress": anime['progress']
    })

@app.route('/api/schedule')
def api_schedule():
    schedule_data = ScheduleCache.get_schedule()
    if schedule_data:
        return jsonify({"success": True, "schedule": schedule_data})
    return jsonify({"success": False, "schedule": []})

@app.route('/api/details/<nom_dossier>')
def get_details(nom_dossier):
    anime = Anime.query.filter_by(nom_dossier=nom_dossier).first()
    if not anime:
        return jsonify({"error": "Anime introuvable"}), 404

    details = logic.get_anime_details(anime.to_dict())
    return jsonify({
        "id": anime.anilist_id,
        "nom_complet": anime.nom_complet,
        "nom_dossier": anime.nom_dossier,
        "total": anime.total_episodes,
        "lien": anime.lien,
        "episodes": details,
        "progress": anime.progress,
        "status": anime.status
    })

@app.route('/api/bulk_download', methods=['POST'])
def bulk_download():
    data = request.json
    nom_dossier = data.get('nom_dossier')
    episodes = data.get('episodes')

    anime = Anime.query.filter_by(nom_dossier=nom_dossier).first()
    if anime:
        logic.add_to_queue(anime.to_dict(), episodes)
        return jsonify({"status": "started", "count": len(episodes)})
    return jsonify({"error": "Anime introuvable"}), 404

@app.route('/api/bulk_delete', methods=['POST'])
def bulk_delete():
    data = request.json
    nom_dossier = data.get('nom_dossier')
    episodes = data.get('episodes')
    count = logic.delete_episodes(nom_dossier, episodes)
    return jsonify({"status": "deleted", "count": count})

@app.route('/api/watch/<nom_dossier>/<int:episode>')
def watch_api(nom_dossier, episode):
    success = logic.open_local_file(nom_dossier, episode)
    return jsonify({"success": success})

@app.route('/api/sync_anilist', methods=['POST'])
def sync_anilist():
    data = request.json
    nom_dossier = data.get('nom_dossier')
    episode = data.get('episode')

    anime = Anime.query.filter_by(nom_dossier=nom_dossier).first()
    if anime and episode:
        anime.update_progress(episode)
        return jsonify({"success": True})
    return jsonify({"error": "Anime introuvable"}), 404

@app.route('/api/change_status', methods=['POST'])
def change_status():
    data = request.json
    nom_dossier = data.get('nom_dossier')
    new_status = data.get('status', 'CURRENT')

    anime = Anime.query.filter_by(nom_dossier=nom_dossier).first()
    if anime:
        anime.status = new_status
        anime.pending_sync = True
        anime.touch()
        return jsonify({"success": True})
    return jsonify({"error": "Anime introuvable"}), 404

@app.route('/api/update_progress', methods=['POST'])
def update_progress():
    data = request.json
    nom_dossier = data.get('nom_dossier')
    episode = data.get('episode')

    anime = Anime.query.filter_by(nom_dossier=nom_dossier).first()
    if anime and episode:
        anime.update_progress(episode)
        return jsonify({"success": True})
    return jsonify({"error": "Anime introuvable"}), 404

@app.route('/api/pull_anilist', methods=['POST'])
def pull_anilist():
    def pull_task():
        with app.app_context():
            try:
                logger = logging.getLogger(__name__)
                logger.info("Pull started")
                all_animes = logic.pull_all_user_data(username=ANILIST_USERNAME)
                logger.info(f"Fetched {len(all_animes)} items from AniList")
                for item in all_animes:
                    anime = Anime.query.filter_by(anilist_id=item['id']).first()
                    if not anime:
                        anime = Anime(anilist_id=item['id'])
                        db.session.add(anime)

                    is_dirty = anime.pending_sync

                    anime.title_romaji = item.get('titres', {}).get('romaji')
                    anime.title_english = item.get('titres', {}).get('english')
                    anime.nom_dossier = item.get('nom_dossier')
                    anime.total_episodes = item.get('total', 0)
                    anime.released_episodes = item.get('sortie', 0)
                    anime.cover_image = item.get('img')
                    anime.lien = item.get('lien')

                    if not is_dirty:
                        anime.progress = item.get('progress', 0)
                        anime.status = item.get('list_status', 'CURRENT')
                        updated_at_ts = item.get('updatedAt', 0)
                        if updated_at_ts:
                            anime.updated_at = datetime.fromtimestamp(updated_at_ts, tz=timezone.utc).replace(tzinfo=None)
                db.session.commit()
                logger.info("DB updated successfully")

                schedule_data = logic.get_airing_schedule()
                if schedule_data:
                    ScheduleCache.save_schedule(schedule_data)
                    logger.info("Schedule cached")

                suggestions = logic.get_seasonal_suggestions()
                if suggestions:
                    SuggestionsCache.save_suggestions(suggestions)
                    logger.info("Suggestions cached")

                logger.info("Pull completed")
            except Exception as e:
                logging.getLogger(__name__).error(f"Pull failed: {e}\n{traceback.format_exc()}")

    threading.Thread(target=pull_task, daemon=True).start()
    return jsonify({"status": "started"})

@app.route('/api/push_anilist', methods=['POST'])
def push_anilist():
    def push_task():
        with app.app_context():
            try:
                animes = Anime.query.all()
                for anime in animes:
                    if anime.pending_sync and anime.progress > 0:
                        ok = logic.push_entry_to_anilist(anime.anilist_id, anime.progress, anime.total_episodes, anime.status)
                        if ok:
                            anime.mark_synced()
                logging.getLogger(__name__).info("Push completed successfully")
            except Exception as e:
                logging.getLogger(__name__).error(f"Push failed: {e}")

    threading.Thread(target=push_task, daemon=True).start()
    return jsonify({"status": "started"})

@app.route('/watch/<nom_dossier>/<int:episode>')
def watch_page(nom_dossier, episode):
    anime = Anime.query.filter_by(nom_dossier=nom_dossier).first()
    if not anime:
        return "Anime not found", 404

    return render_template('watch.html',
        nom_dossier=nom_dossier,
        episode=episode,
        total_episodes=anime.total_episodes or 0,
        anime_title=anime.title_romaji or nom_dossier,
        cover_image=anime.cover_image or '',
        has_prev=episode > 1,
        prev_episode=episode - 1,
        has_next=episode < (anime.total_episodes or 0),
        next_episode=episode + 1
    )

@app.route('/stream/<nom_dossier>/<int:episode>')
def stream_video(nom_dossier, episode):
    video_path = os.path.join(logic.ANIME_DIR, nom_dossier, f"{episode}.mp4")
    if not os.path.exists(video_path):
        return "File not found", 404
    return send_file(video_path, mimetype='video/mp4')

if __name__ == '__main__':
    logic.print_status("Initialisation du Serveur Web (127.0.0.1:5000)...")
    with app.app_context():
        if Anime.query.count() == 0:
            logging.getLogger(__name__).info("Database empty. Click 'Anilist Pull' to sync.")
    app.run(debug=False, host='0.0.0.0', port=5000)
