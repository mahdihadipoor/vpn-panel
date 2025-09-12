# main.py
import uvicorn
import psutil
import datetime
import time
import subprocess
import socket
import os
import sys
import threading
import json
import uuid
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Body
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pathlib import Path
from pydantic import BaseModel
from typing import List

from app import crud, security
from app.database import SessionLocal, create_db_and_tables

create_db_and_tables()

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=str(Path(BASE_DIR, 'static'))), name="static")


# --- Global variables for network speed calculation ---
last_net_io = psutil.net_io_counters()
last_time = time.time()
# ----------------------------------------------------

def get_server_public_ip():
    """Finds the first non-local public IPv4 address of the server."""
    try:
        for interface, snicaddrs in psutil.net_if_addrs().items():
            for snicaddr in snicaddrs:
                if snicaddr.family == socket.AF_INET and not snicaddr.address.startswith("127."):
                    # This is a simple check, for more complex networks you might need a more robust solution
                    return snicaddr.address
    except Exception as e:
        print(f"Could not determine server IP: {e}")
    return None

# --- Helper functions for system interaction ---
def run_shell_command(command):
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            capture_output=True,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e.stderr.strip()}")
        return None

def get_xray_status():
    status = run_shell_command("systemctl is-active xray.service")
    return status if status else "unknown"

def get_xray_version():
    output = run_shell_command("/usr/local/bin/xray --version")
    if output:
        return output.splitlines()[0]
    return "Not Found"

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Page and Auth Routes ---
@app.get("/", response_class=HTMLResponse)
async def read_root():
    return FileResponse(str(Path(BASE_DIR, 'templates', 'login.html')))

@app.post("/login")
async def login(
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...)
):
    user = crud.get_user_by_username(db, username=username)
    if not user or not security.verify_password(password, user.hashed_password):
        return JSONResponse(status_code=401, content={"message": "نام کاربری یا رمز عبور اشتباه است"})
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    return FileResponse(str(Path(BASE_DIR, 'templates', 'dashboard.html')))

@app.get("/panel-settings", response_class=HTMLResponse)
async def get_panel_settings_page():
    return FileResponse(str(Path(BASE_DIR, 'templates', 'panel_settings.html')))

@app.get("/inbounds", response_class=HTMLResponse)
async def get_inbounds_page():
    return FileResponse(str(Path(BASE_DIR, 'templates', 'inbounds.html')))

@app.get("/inbounds/{inbound_id}", response_class=HTMLResponse)
async def get_clients_page(inbound_id: int):
    # This route will serve the new clients.html page
    return FileResponse(str(Path(BASE_DIR, 'templates', 'clients.html')))

# --- XRAY CONFIG MANAGER (REWRITTEN) ---
class XrayManager:
    def __init__(self, config_path="/usr/local/etc/xray/config.json"):
        self.config_path = config_path

    def generate_config(self, db: Session):
        all_inbounds = crud.get_inbounds(db)
        xray_inbounds = []
        
        for inbound in all_inbounds:
            if not inbound.enabled:
                continue

            clients_for_this_inbound = crud.get_clients_for_inbound(db, inbound.id)
            xray_clients = [{"id": client.uuid, "email": client.remark} for client in clients_for_this_inbound if client.enabled]

            if not xray_clients:
                continue

            # This structure is for a standard VLESS + TCP inbound
            new_inbound = {
                "listen": "0.0.0.0",
                "port": inbound.port,
                "protocol": inbound.protocol,
                "settings": {
                    "clients": xray_clients,
                    "decryption": "none"
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "none"
                },
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            }
            xray_inbounds.append(new_inbound)

        config = {
            "log": {"loglevel": "warning"},
            "inbounds": xray_inbounds,
            "outbounds": [{"protocol": "freedom", "tag": "direct"}, {"protocol": "blackhole", "tag": "block"}]
        }
        
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=4)
            return True
        except Exception as e:
            print(f"Error writing Xray config: {e}")
            return False

    def apply_config(self):
        print("Applying new Xray config and restarting service...")
        return run_shell_command("sudo systemctl restart xray.service")

xray_manager = XrayManager()

# --- Pydantic Models for API Validation ---
class InboundClient(BaseModel):
    id: str # UUID

class InboundSettings(BaseModel):
    clients: List[InboundClient]

class CreateInbound(BaseModel):
    remark: str
    port: int
    protocol: str = "vless"

class CreateClient(BaseModel):
    remark: str

@app.get("/api/v1/inbounds")
async def read_inbounds(db: Session = Depends(get_db)):
    inbounds = crud.get_inbounds(db)
    for ib in inbounds:
        ib.client_count = len(ib.clients)
    return inbounds

@app.post("/api/v1/inbounds")
async def add_inbound(inbound_data: CreateInbound, db: Session = Depends(get_db)):
    if crud.get_inbound_by_port(db, inbound_data.port) or crud.get_inbound_by_remark(db, inbound_data.remark):
        raise HTTPException(status_code=400, detail="Port or Remark already in use.")
    
    new_inbound = crud.create_inbound(db, inbound_data.dict())
    
    # After creating an inbound, you might want to add a default client or just let the user add them manually
    # For now, we will let user add them manually.
    
    if xray_manager.generate_config(db):
        xray_manager.apply_config()
        
    return new_inbound

@app.delete("/api/v1/inbounds/{inbound_id}")
async def remove_inbound(inbound_id: int, db: Session = Depends(get_db)):
    if crud.delete_inbound(db, inbound_id):
        if xray_manager.generate_config(db):
            xray_manager.apply_config()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Inbound not found.")

# --- NEW CLIENT APIs ---
@app.get("/api/v1/inbounds/{inbound_id}/clients")
async def read_clients_for_inbound(inbound_id: int, db: Session = Depends(get_db)):
    clients = crud.get_clients_for_inbound(db, inbound_id)
    inbound = db.query(crud.models.Inbound).filter(crud.models.Inbound.id == inbound_id).first()
    if not inbound:
        raise HTTPException(status_code=404, detail="Inbound not found.")

    # --- DYNAMIC IP DETECTION ---
    server_ip = get_server_public_ip() or "127.0.0.1" # Fallback to localhost if not found

    for client in clients:
        # Generate config link with the detected server IP
        client.config_link = f"vless://{client.uuid}@{server_ip}:{inbound.port}?security=none&type=tcp#{client.remark}"
    
    return clients

@app.post("/api/v1/inbounds/{inbound_id}/clients")
async def add_client_for_inbound(inbound_id: int, client_data: CreateClient, db: Session = Depends(get_db)):
    new_client = crud.create_client(db, inbound_id=inbound_id, remark=client_data.remark)
    
    if xray_manager.generate_config(db):
        xray_manager.apply_config()
        
    return new_client


# --- API Routes ---

@app.get("/api/v1/system/stats")
async def get_system_stats():
    global last_net_io, last_time

    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_count = psutil.cpu_count(logical=True)
    mem = psutil.virtual_memory()
    mem_percent = mem.percent
    mem_total_gb = round(mem.total / (1024**3), 2)
    mem_used_gb = round(mem.used / (1024**3), 2)
    swap = psutil.swap_memory()
    swap_percent = swap.percent
    swap_total_gb = round(swap.total / (1024**3), 2)
    swap_used_gb = round(swap.used / (1024**3), 2)
    disk = psutil.disk_usage('/')
    disk_percent = disk.percent
    disk_total_gb = round(disk.total / (1024**3), 2)
    disk_used_gb = round(disk.used / (1024**3), 2)
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.datetime.now() - boot_time
    net_io = psutil.net_io_counters()
    total_sent_gb = round(net_io.bytes_sent / (1024**3), 2)
    total_received_gb = round(net_io.bytes_recv / (1024**3), 2)
    current_time = time.time()
    time_diff = current_time - last_time
    current_net_io = psutil.net_io_counters()
    upload_speed = (current_net_io.bytes_sent - last_net_io.bytes_sent) / time_diff if time_diff > 0 else 0
    download_speed = (current_net_io.bytes_recv - last_net_io.bytes_recv) / time_diff if time_diff > 0 else 0
    last_net_io = current_net_io
    last_time = current_time
    connections = psutil.net_connections()
    tcp_count = len([c for c in connections if c.status == 'ESTABLISHED' and c.type == 1])
    udp_count = len([c for c in connections if c.type == 2])
    xray_status = get_xray_status()
    xray_version = get_xray_version()
    
    ipv4_addrs, ipv6_addrs = [], []
    for interface, snicaddrs in psutil.net_if_addrs().items():
        for snicaddr in snicaddrs:
            if snicaddr.family == socket.AF_INET and not snicaddr.address.startswith("127."):
                ipv4_addrs.append(snicaddr.address)
            elif snicaddr.family == socket.AF_INET6 and not snicaddr.address.startswith("::1") and not snicaddr.address.startswith("fe80"):
                ipv6_addrs.append(snicaddr.address)

    return {
        "cpu": {"percent": cpu_percent, "count": cpu_count},
        "ram": {"percent": mem_percent, "used": mem_used_gb, "total": mem_total_gb},
        "swap": {"percent": swap_percent, "used": swap_used_gb, "total": swap_total_gb},
        "storage": {"percent": disk_percent, "used": disk_used_gb, "total": disk_total_gb},
        "uptime": str(uptime).split('.')[0],
        "total_data": {"sent": total_sent_gb, "received": total_received_gb},
        "speed": {"upload": upload_speed, "download": download_speed},
        "connections": {"tcp": tcp_count, "udp": udp_count},
        "xray": {"status": xray_status, "version": xray_version},
        "ip_addresses": {"ipv4": sorted(list(set(ipv4_addrs))), "ipv6": sorted(list(set(ipv6_addrs)))}
    }

@app.get("/api/v1/panel/settings")
async def read_settings(db: Session = Depends(get_db)):
    settings = crud.get_settings(db)
    return settings

@app.post("/api/v1/panel/settings")
async def write_settings(settings_data: dict = Body(...), db: Session = Depends(get_db)):
    updated_settings = crud.update_settings(db, settings_data)
    if not updated_settings:
        raise HTTPException(status_code=404, detail="Settings not found.")
    return {"status": "success", "message": "Settings saved successfully."}

@app.post("/api/v1/panel/restart")
async def restart_panel():
    def restart_script():
        time.sleep(1)
        os.execv(sys.executable, ['python3'] + sys.argv)
    threading.Thread(target=restart_script).start()
    return {"status": "success", "message": "Panel is restarting..."}

@app.post("/api/v1/xray/start")
async def start_xray():
    run_shell_command("sudo systemctl start xray.service")
    if get_xray_status() == "active":
        return {"status": "success", "message": "Xray started successfully."}
    raise HTTPException(status_code=500, detail="Failed to start Xray.")

@app.post("/api/v1/xray/stop")
async def stop_xray():
    run_shell_command("sudo systemctl stop xray.service")
    if get_xray_status() != "active":
        return {"status": "success", "message": "Xray stopped successfully."}
    raise HTTPException(status_code=500, detail="Failed to stop Xray.")

@app.post("/api/v1/xray/restart")
async def restart_xray():
    run_shell_command("sudo systemctl restart xray.service")
    time.sleep(1)
    if get_xray_status() == "active":
        return {"status": "success", "message": "Xray restarted successfully."}
    raise HTTPException(status_code=500, detail="Failed to restart Xray.")


if __name__ == "__main__":
    db = SessionLocal()
    settings = crud.get_settings(db)
    
    listen_port = settings.listen_port
    public_key = settings.public_key_path
    private_key = settings.private_key_path
    
    db.close()
    
    print("--- PANEL SETTINGS ---")
    print(f"Port: {listen_port}")
    print(f"SSL Cert: {public_key or 'Not Set'}")
    print(f"SSL Key: {private_key or 'Not Set'}")
    print("----------------------")

    uvicorn_args = {
        "host": "0.0.0.0",
        "port": listen_port,
        # "reload": True, # <-- THIS LINE IS REMOVED TO FIX THE RESTART ISSUE
    }

    if public_key and private_key:
        uvicorn_args["ssl_keyfile"] = private_key
        uvicorn_args["ssl_certfile"] = public_key

    uvicorn.run("main:app", **uvicorn_args)