# app/crud.py

from sqlalchemy.orm import Session
from . import models, security

# ... User functions (get_user_by_username, create_user, etc.) remain unchanged ...
def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def create_user(db: Session, username: str, password: str):
    hashed_password = security.get_password_hash(password)
    db_user = models.User(username=username, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def update_user_password(db: Session, username: str, new_password: str):
    db_user = get_user_by_username(db, username)
    if db_user:
        db_user.hashed_password = security.get_password_hash(new_password)
        db.commit()
        db.refresh(db_user)
        return db_user
    return None

# --- NEW SETTINGS FUNCTIONS ---
def get_settings(db: Session):
    settings = db.query(models.Settings).filter(models.Settings.id == 1).first()
    if not settings:
        # Create default settings if they don't exist
        default_settings = models.Settings(id=1)
        db.add(default_settings)
        db.commit()
        db.refresh(default_settings)
        return default_settings
    return settings

def update_settings(db: Session, new_settings: dict):
    settings_obj = db.query(models.Settings).filter(models.Settings.id == 1).first()
    if settings_obj:
        for key, value in new_settings.items():
            setattr(settings_obj, key, value)
        db.commit()
        db.refresh(settings_obj)
        return settings_obj
    return None