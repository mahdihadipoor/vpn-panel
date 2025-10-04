# app/models.py
from sqlalchemy import Column, Integer, String, Boolean, BigInteger, ForeignKey, Float
from .database import Base
from sqlalchemy.orm import relationship

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    session_token = Column(String, unique=True, nullable=True)

class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    listen_port = Column(Integer, default=443)
    domain_name = Column(String, nullable=True, default="")
    public_key_path = Column(String, nullable=True, default="")
    private_key_path = Column(String, nullable=True, default="")
    language = Column(String, default="en")
    time_zone = Column(String, default="Local")
    calendar_type = Column(String, default="Gregorian")
    notifications_enabled = Column(Boolean, default=False)
    external_traffic_enabled = Column(Boolean, default=False)
    external_traffic_uri = Column(String, nullable=True, default="")

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    remark = Column(String, unique=True, index=True, nullable=False)
    total_gb = Column(Float, default=0)
    expiry_time = Column(BigInteger, default=0)
    sub_token = Column(String, unique=True, index=True, nullable=False)
    enabled = Column(Boolean, default=True) # Enabled status is here
    
    clients = relationship("Client", back_populates="subscription", cascade="all, delete-orphan")

class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    inbound_id = Column(Integer, ForeignKey("inbounds.id"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    uuid = Column(String, unique=True, nullable=False)
    remark = Column(String) # This is the client's specific name/email
    up_traffic = Column(BigInteger, default=0)
    down_traffic = Column(BigInteger, default=0)
    
    inbound = relationship("Inbound", back_populates="clients")
    subscription = relationship("Subscription", back_populates="clients")

class Inbound(Base):
    __tablename__ = "inbounds"
    id = Column(Integer, primary_key=True, index=True)
    remark = Column(String, unique=True, nullable=False)
    enabled = Column(Boolean, default=True)
    port = Column(Integer, unique=True, nullable=False)
    protocol = Column(String, nullable=False)
    
    settings = Column(String, default='{}')
    stream_settings = Column(String, default='{}')
    sniffing_settings = Column(String, default='{}')
    
    clients = relationship("Client", back_populates="inbound", cascade="all, delete-orphan")