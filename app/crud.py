# app/crud.py

from sqlalchemy.orm import Session
from . import models, security

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