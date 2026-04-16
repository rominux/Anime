import os
import json
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Anime(db.Model):
    __tablename__ = 'animes'
    
    id = db.Column(db.Integer, primary_key=True)
    anilist_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    title_romaji = db.Column(db.String(500))
    title_english = db.Column(db.String(500))
    title_full = db.Column(db.String(1000))
    nom_dossier = db.Column(db.String(200), index=True)
    total_episodes = db.Column(db.Integer, default=0)
    released_episodes = db.Column(db.Integer, default=0)
    progress = db.Column(db.Integer, default=0)
    cover_image = db.Column(db.String(500))
    cover_local = db.Column(db.String(500))
    status = db.Column(db.String(50), default='CURRENT')
    lien = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
            'titres': {
                'romaji': self.title_romaji,
                'english': self.title_english
            },
            'progress': self.progress,
            'sortie': self.released_episodes,
            'total': self.total_episodes,
            'lien': self.lien,
            'img': self.cover_local or self.cover_image,
            'status': self.status
        }
    
    @staticmethod
    def get_by_status(status):
        return Anime.query.filter_by(status=status).order_by(Anime.updated_at.desc()).all()
    
    @staticmethod
    def get_all_ordered():
        return Anime.query.order_by(Anime.updated_at.desc()).all()
    
    @staticmethod
    def get_by_dossier(nom_dossier):
        return Anime.query.filter_by(nom_dossier=nom_dossier).first()
    
    @staticmethod
    def upsert_from_anilist(data):
        anime = Anime.query.filter_by(anilist_id=data['id']).first()
        
        if not anime:
            anime = Anime(anilist_id=data['id'])
            db.session.add(anime)
        
        anime.title_romaji = data.get('titres', {}).get('romaji')
        anime.title_english = data.get('titres', {}).get('english')
        anime.title_full = data.get('nom_complet')
        anime.nom_dossier = data.get('nom_dossier')
        anime.total_episodes = data.get('total', 0)
        anime.released_episodes = data.get('sortie', 0)
        anime.progress = data.get('progress', 0)
        anime.cover_image = data.get('img')
        anime.lien = data.get('lien')
        
        updated_at_ts = data.get('updatedAt', 0)
        if updated_at_ts:
            anime.updated_at = datetime.utcfromtimestamp(updated_at_ts)
        
        return anime
    
    def update_progress(self, episode):
        if episode > self.progress:
            self.progress = episode
            self.updated_at = datetime.utcnow()
        if self.total_episodes and episode >= self.total_episodes:
            self.status = 'COMPLETED'
            self.updated_at = datetime.utcnow()
        db.session.commit()
    
    def touch(self):
        self.updated_at = datetime.utcnow()
        db.session.commit()
    
    def delete(self):
        db.session.delete(self)
        db.session.commit()


class ScheduleCache(db.Model):
    __tablename__ = 'schedule_cache'
    
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @staticmethod
    def get_schedule():
        cache = ScheduleCache.query.first()
        if cache and cache.data:
            try:
                return json.loads(cache.data)
            except:
                return []
        return []
    
    @staticmethod
    def save_schedule(schedule_data):
        cache = ScheduleCache.query.first()
        if not cache:
            cache = ScheduleCache()
            db.session.add(cache)
        cache.data = json.dumps(schedule_data)
        cache.updated_at = datetime.utcnow()
        db.session.commit()


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()