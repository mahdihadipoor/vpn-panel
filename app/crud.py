# app/crud.py
from sqlalchemy.orm import Session
import json
import uuid
import secrets
from sqlalchemy import func
from . import models, security

# --- User and Settings Functions ---
def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def get_user_by_session_token(db: Session, token: str):
    return db.query(models.User).filter(models.User.session_token == token).first()

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
        db_user.session_token = None
        db.commit()
        db.refresh(db_user)
    return db_user

def update_user_session(db: Session, user_id: int, token: str | None):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if db_user:
        db_user.session_token = token
        db.commit()
    return db_user

def get_settings(db: Session):
    settings = db.query(models.Settings).filter(models.Settings.id == 1).first()
    if not settings:
        default_settings = models.Settings(id=1)
        db.add(default_settings)
        db.commit()
        db.refresh(default_settings)
    return settings

def update_settings(db: Session, new_settings: dict):
    settings_obj = db.query(models.Settings).filter(models.Settings.id == 1).first()
    if settings_obj:
        for key, value in new_settings.items():
            setattr(settings_obj, key, value)
        db.commit()
        db.refresh(settings_obj)
    return settings_obj

# --- INBOUND CRUD Functions ---
def get_inbounds(db: Session):
    return db.query(models.Inbound).all()

def get_inbound_by_id(db: Session, inbound_id: int):
    return db.query(models.Inbound).filter(models.Inbound.id == inbound_id).first()

def get_inbound_by_port(db: Session, port: int):
    return db.query(models.Inbound).filter(models.Inbound.port == port).first()

def get_inbound_by_remark(db: Session, remark: str):
    return db.query(models.Inbound).filter(models.Inbound.remark == remark).first()
    
def create_inbound(db: Session, inbound_data: dict):
    db_inbound = models.Inbound(
        remark=inbound_data["remark"],
        port=inbound_data["port"],
        protocol=inbound_data["protocol"],
        settings=inbound_data.get("settings", '{}'),
        stream_settings=inbound_data.get("stream_settings", '{}')
    )
    db.add(db_inbound)
    db.commit()
    db.refresh(db_inbound)
    return db_inbound

def update_inbound(db: Session, inbound_id: int, inbound_data: dict):
    db_inbound = get_inbound_by_id(db, inbound_id)
    if db_inbound:
        for key, value in inbound_data.items():
            if hasattr(db_inbound, key) and value is not None:
                setattr(db_inbound, key, value)
        db.commit()
        db.refresh(db_inbound)
        return db_inbound
    return None

def delete_inbound(db: Session, inbound_id: int):
    db_inbound = get_inbound_by_id(db, inbound_id)
    if db_inbound:
        db.delete(db_inbound)
        db.commit()
        return True
    return False

# --- Subscription and Client Functions ---
def get_subscription_by_id(db: Session, sub_id: int):
    return db.query(models.Subscription).filter(models.Subscription.id == sub_id).first()
def get_subscription_by_remark(db: Session, remark: str):
    return db.query(models.Subscription).filter(models.Subscription.remark == remark).first()
def get_subscriptions(db: Session):
    return db.query(models.Subscription).all()
def create_subscription(db: Session, remark: str, total_gb: float = 0, expiry_time: int = 0):
    sub_token = secrets.token_urlsafe(16)
    db_sub = models.Subscription(remark=remark, total_gb=total_gb, expiry_time=expiry_time, sub_token=sub_token)
    db.add(db_sub)
    db.commit()
    db.refresh(db_sub)
    return db_sub
def update_subscription(db: Session, sub_id: int, sub_data: dict):
    db_sub = get_subscription_by_id(db, sub_id)
    if db_sub:
        for key, value in sub_data.items():
            if value is not None:
                setattr(db_sub, key, value)
        db.commit()
        db.refresh(db_sub)
    return db_sub

def create_client(db: Session, inbound_id: int, subscription_id: int, remark: str):
    new_uuid = str(uuid.uuid4())
    db_client = models.Client(inbound_id=inbound_id, subscription_id=subscription_id, uuid=new_uuid, remark=remark)
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client

def get_client_by_id(db: Session, client_id: int):
    return db.query(models.Client).filter(models.Client.id == client_id).first()

def get_clients_for_inbound(db: Session, inbound_id: int):
    return db.query(models.Client).filter(models.Client.inbound_id == inbound_id).all()
    
def get_total_usage_for_subscription(db: Session, subscription_id: int):
    total_usage = db.query(func.sum(models.Client.up_traffic + models.Client.down_traffic)).filter(models.Client.subscription_id == subscription_id).scalar()
    return total_usage or 0

def update_client(db: Session, client_id: int, client_data: dict):
    db_client = get_client_by_id(db, client_id)
    if db_client:
        for key, value in client_data.items():
            if value is not None:
                setattr(db_client, key, value)
        db.commit()
        db.refresh(db_client)
        return db_client
    return None
    
def update_clients_traffic(db: Session, traffic_data: dict):
    client_remarks = traffic_data.keys()
    clients = db.query(models.Client).filter(models.Client.remark.in_(client_remarks)).all()
    for client in clients:
        stats = traffic_data.get(client.remark)
        if stats:
            client.up_traffic += stats['up']
            client.down_traffic += stats['down']
    db.commit()