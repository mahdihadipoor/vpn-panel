# app/models.py

from sqlalchemy import Column, Integer, String, Boolean
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    listen_port = Column(Integer, default=443)
    language = Column(String, default="en")
    
    # Certificates
    public_key_path = Column(String, nullable=True, default="")
    private_key_path = Column(String, nullable=True, default="")
    
    # Date and Time
    time_zone = Column(String, default="Local")
    calendar_type = Column(String, default="Gregorian")

    # NEW Fields for future sections
    notifications_enabled = Column(Boolean, default=False)
    external_traffic_enabled = Column(Boolean, default=False)
    external_traffic_uri = Column(String, nullable=True, default="")