# app/crud.py
from sqlalchemy.orm import Session
import json
import uuid
from . import models, security

# ... (User and Settings functions remain unchanged) ...
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

def get_settings(db: Session):
    settings = db.query(models.Settings).filter(models.Settings.id == 1).first()
    if not settings:
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


# --- INBOUND CRUD FUNCTIONS ---
def get_inbounds(db: Session):
    return db.query(models.Inbound).all()

def get_inbound_by_port(db: Session, port: int):
    return db.query(models.Inbound).filter(models.Inbound.port == port).first()

def get_inbound_by_remark(db: Session, remark: str):
    return db.query(models.Inbound).filter(models.Inbound.remark == remark).first()
    
def create_inbound(db: Session, inbound_data: dict):
    settings_str = json.dumps(inbound_data.get("settings", {}))
    stream_settings_str = json.dumps(inbound_data.get("stream_settings", {}))
    
    db_inbound = models.Inbound(
        remark=inbound_data["remark"],
        port=inbound_data["port"],
        protocol=inbound_data["protocol"],
        settings=settings_str,
        stream_settings=stream_settings_str
    )
    db.add(db_inbound)
    db.commit()
    db.refresh(db_inbound)
    return db_inbound

def delete_inbound(db: Session, inbound_id: int):
    db_inbound = db.query(models.Inbound).filter(models.Inbound.id == inbound_id).first()
    if db_inbound:
        db.delete(db_inbound)
        db.commit()
        return True
    return False

def get_clients_for_inbound(db: Session, inbound_id: int):
    return db.query(models.Client).filter(models.Client.inbound_id == inbound_id).all()

def create_client(db: Session, inbound_id: int, remark: str):
    new_uuid = str(uuid.uuid4())
    db_client = models.Client(
        inbound_id=inbound_id,
        remark=remark,
        uuid=new_uuid
    )
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client