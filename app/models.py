# app/models.py

from sqlalchemy import Column, Integer, String, Boolean, BigInteger
from .database import Base
from sqlalchemy import Column, Integer, String, Boolean, BigInteger, ForeignKey
from sqlalchemy.orm import relationship

# ... (User and Settings models remain unchanged) ...
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

class Settings(Base):
    __tablename__ = "settings"
    # ... (all settings fields remain unchanged) ...
    id = Column(Integer, primary_key=True)
    listen_port = Column(Integer, default=443)
    language = Column(String, default="en")
    public_key_path = Column(String, nullable=True, default="")
    private_key_path = Column(String, nullable=True, default="")
    time_zone = Column(String, default="Local")
    calendar_type = Column(String, default="Gregorian")
    notifications_enabled = Column(Boolean, default=False)
    external_traffic_enabled = Column(Boolean, default=False)
    external_traffic_uri = Column(String, nullable=True, default="")

class Client(Base):
    __tablename__ = "clients"
    
    id = Column(Integer, primary_key=True, index=True)
    inbound_id = Column(Integer, ForeignKey("inbounds.id"))
    
    remark = Column(String, default="client")
    uuid = Column(String, unique=True, nullable=False)
    enabled = Column(Boolean, default=True)
    
    total_gb = Column(BigInteger, default=0)
    expiry_time = Column(BigInteger, default=0)
    
    up_traffic = Column(BigInteger, default=0)
    down_traffic = Column(BigInteger, default=0)
    
    inbound = relationship("Inbound", back_populates="clients")

# --- NEW INBOUND TABLE ---
class Inbound(Base):
    __tablename__ = "inbounds"

    id = Column(Integer, primary_key=True, index=True)
    remark = Column(String, unique=True, nullable=False)
    enabled = Column(Boolean, default=True)
    port = Column(Integer, unique=True, nullable=False)
    protocol = Column(String, nullable=False)
    
    # This will now store inbound-specific settings (not clients)
    settings = Column(String, default='{}')
    stream_settings = Column(String, default='{}')
    sniffing_settings = Column(String, default='{}')
    
    # Relationship to clients
    clients = relationship("Client", back_populates="inbound", cascade="all, delete-orphan")