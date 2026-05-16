import os
import json
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Anime(db.Model):
    __tablename__ = 'animes'

    id = db.Column(db.Integer, primary_key=True)
    anilist_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    title_romaji = db.Column(db.String(500))
    title_english = db.Column(db.String(500))
    nom_dossier = db.Column(db.String(200), index=True)
    total_episodes = db.Column(db.Integer, default=0)
    released_episodes = db.Column(db.Integer, default=0)
    progress = db.Column(db.Integer, default=0)
    cover_image = db.Column(db.String(500))
    status = db.Column(db.String(50), default='CURRENT')
    lien = db.Column(db.String(500))
    pending_sync = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    @property
    def nom_complet(self):
        if self.title_english:
            return f"{self.title_romaji} ;;; {self.title_english}"
        return self.title_romaji or "Unknown"

    def to_dict(self):
        return {
            'id': self.anilist_id,
            'nom_complet': self.nom_complet,
            'nom_dossier': self.nom_dossier,
            'titres': {'romaji': self.title_romaji, 'english': self.title_english},
            'progress': self.progress,
            'sortie': self.released_episodes,
            'total': self.total_episodes,
            'lien': self.lien,
            'img': self.cover_image,
            'status': self.status
        }

    def update_progress(self, episode):
        if episode > self.progress:
            self.progress = episode
            self.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            self.pending_sync = True
        if self.total_episodes and episode >= self.total_episodes:
            self.status = 'COMPLETED'
            self.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            self.pending_sync = True
        db.session.commit()

    def touch(self):
        self.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self.pending_sync = True
        db.session.commit()

    def mark_synced(self):
        self.pending_sync = False
        db.session.commit()


class SuggestionsCache(db.Model):
    __tablename__ = 'suggestions_cache'

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text)
    season = db.Column(db.String(20))
    year = db.Column(db.Integer)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    @staticmethod
    def get_suggestions():
        try:
            cache = SuggestionsCache.query.first()
            if cache and cache.data:
                return json.loads(cache.data)
        except Exception:
            pass
        return None

    @staticmethod
    def save_suggestions(data):
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            season_map = {1: "WINTER", 2: "WINTER", 3: "WINTER", 4: "SPRING", 5: "SPRING", 6: "SPRING",
                          7: "SUMMER", 8: "SUMMER", 9: "SUMMER", 10: "FALL", 11: "FALL", 12: "FALL"}
            season = season_map[now.month]
            cache = SuggestionsCache.query.first()
            if not cache:
                cache = SuggestionsCache()
                db.session.add(cache)
            cache.data = json.dumps(data)
            cache.season = season
            cache.year = now.year
            cache.updated_at = now
            db.session.commit()
        except Exception:
            pass


class ScheduleCache(db.Model):
    __tablename__ = 'schedule_cache'

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    @staticmethod
    def get_schedule():
        try:
            cache = ScheduleCache.query.first()
            if cache and cache.data:
                return json.loads(cache.data)
        except Exception:
            pass
        return None

    @staticmethod
    def save_schedule(schedule_data):
        try:
            cache = ScheduleCache.query.first()
            if not cache:
                cache = ScheduleCache()
                db.session.add(cache)
            cache.data = json.dumps(schedule_data)
            cache.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.commit()
        except Exception:
            pass


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _add_pending_sync_column()

def _add_pending_sync_column():
    import sqlalchemy as sa
    inspector = sa.inspect(db.engine)
    columns = [c['name'] for c in inspector.get_columns('animes')]
    if 'pending_sync' not in columns:
        db.session.execute(sa.text('ALTER TABLE animes ADD COLUMN pending_sync BOOLEAN DEFAULT 0'))
        db.session.commit()
