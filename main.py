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
import grpc

from fastapi import FastAPI, Request, Depends, Form, HTTPException, Body
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional

from app import crud, security
from app.database import SessionLocal, create_db_and_tables
# Ensure you have regenerated these files as per the previous instructions
from app.xray_api import stats_pb2, stats_pb2_grpc

create_db_and_tables()

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=str(Path(BASE_DIR, 'static'))), name="static")


# --- Global variables for network speed calculation ---
last_net_io = psutil.net_io_counters()
last_time = time.time()
# ----------------------------------------------------

# --- Xray API Client ---
def get_xray_stats(emails: List[str]):
    try:
        # The API inbound is now on port 62789 as per the working config
        channel = grpc.insecure_channel('127.0.0.1:62789')
        stub = stats_pb2_grpc.StatsServiceStub(channel)
        
        traffic_data = {}
        
        req = stats_pb2.QueryStatsRequest(pattern="user>>>", reset=True)
        res = stub.QueryStats(req)
        
        for stat in res.stat:
            parts = stat.name.split('>>>')
            if len(parts) == 4 and parts[0] == 'user':
                email = parts[1]
                direction = parts[3]
                value = stat.value

                if email not in traffic_data:
                    traffic_data[email] = {'up': 0, 'down': 0}
                
                if direction == 'uplink':
                    traffic_data[email]['up'] += value
                elif direction == 'downlink':
                    traffic_data[email]['down'] += value
        
        return traffic_data
    except Exception as e:
        print(f"Could not connect to Xray API: {e}")
        return {}

def get_server_public_ip():
    """Finds the first non-local public IPv4 address of the server."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        print(f"Could not determine server IP: {e}")
    return "127.0.0.1"

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

# --- XRAY CONFIG MANAGER (BASED ON WORKING CONFIG) ---
class XrayManager:
    def __init__(self, config_path="/usr/local/etc/xray/config.json"):
        self.config_path = config_path

    def generate_config(self, db: Session):
        config = {
            "log": { "loglevel": "warning" },
            "api": {
                "tag": "api",
                "services": ["StatsService"]
            },
            "stats": {},
            "policy": {
                "levels": {
                    "0": { "statsUserUplink": True, "statsUserDownlink": True }
                },
                "system": { "statsInboundUplink": True, "statsInboundDownlink": True }
            },
            "inbounds": [
                # Dedicated inbound for the API
                {
                    "tag": "api",
                    "listen": "127.0.0.1",
                    "port": 62789,
                    "protocol": "dokodemo-door",
                    "settings": { "address": "127.0.0.1" }
                }
            ],
            "outbounds": [
                { "protocol": "freedom", "tag": "direct" },
                # Dedicated outbound for the API
                { "protocol": "blackhole", "tag": "api" }
            ],
            "routing": {
                "domainStrategy": "AsIs",
                "rules": [
                    {
                        "type": "field",
                        "inboundTag": ["api"],
                        "outboundTag": "api"
                    }
                ]
            }
        }
        
        all_inbounds = crud.get_inbounds(db)

        for inbound in all_inbounds:
            if not inbound.enabled: continue

            clients_for_this_inbound = crud.get_clients_for_inbound(db, inbound.id)
            
            xray_clients = []
            if inbound.protocol == "vless":
                xray_clients = [{"id": c.uuid, "email": c.remark, "level": 0} for c in clients_for_this_inbound if c.enabled]
            elif inbound.protocol == "vmess":
                xray_clients = [{"id": c.uuid, "alterId": 0, "email": c.remark, "level": 0} for c in clients_for_this_inbound if c.enabled]
            
            if not xray_clients: continue

            stream_settings = json.loads(inbound.stream_settings)

            xray_inbound = {
                "port": inbound.port,
                "listen": "0.0.0.0",
                "protocol": inbound.protocol,
                "settings": {
                    "clients": xray_clients,
                    "decryption": "none"
                },
                "streamSettings": stream_settings,
                "tag": f"inbound-{inbound.port}"
            }
            config["inbounds"].append(xray_inbound)
        
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=4)
            print("Successfully generated config based on working example.")
            return True
        except Exception as e:
            print(f"FATAL: Error writing Xray config: {e}")
            return False

    def apply_config(self):
        print("Applying new Xray config and restarting service...")
        return run_shell_command("sudo systemctl restart xray.service")

xray_manager = XrayManager()

# --- Pydantic Models for API Validation ---
class StreamSettings(BaseModel):
    network: str = "tcp"
    security: str = "none"
    wsSettings: Optional[dict] = None
    grpcSettings: Optional[dict] = None
    httpSettings: Optional[dict] = None

class CreateInbound(BaseModel):
    remark: str
    port: int
    protocol: str = "vless"
    stream_settings: StreamSettings
    total_gb: int = Field(0, ge=0)
    expiry_time: int = Field(0, ge=0)


class CreateClient(BaseModel):
    remark: str
    total_gb: int = Field(0, ge=0)
    expiry_time: int = Field(0, ge=0)

# --- INBOUND APIs ---
@app.get("/api/v1/inbounds")
async def read_inbounds(db: Session = Depends(get_db)):
    inbounds = crud.get_inbounds(db)
    for ib in inbounds:
        ib.client_count = len(ib.clients)
        if ib.expiry_time > 0:
            ib.expiry_date = datetime.datetime.fromtimestamp(ib.expiry_time).strftime('%Y-%m-%d')
        else:
            ib.expiry_date = "Unlimited"
    return inbounds

@app.post("/api/v1/inbounds")
async def add_inbound(inbound_data: CreateInbound, db: Session = Depends(get_db)):
    if crud.get_inbound_by_port(db, inbound_data.port) or crud.get_inbound_by_remark(db, inbound_data.remark):
        raise HTTPException(status_code=400, detail="Port or Remark already in use.")
    
    inbound_dict = inbound_data.dict()
    inbound_dict['stream_settings'] = json.dumps(inbound_data.stream_settings.dict(exclude_none=True))
    
    new_inbound = crud.create_inbound(db, inbound_dict)
    
    if xray_manager.generate_config(db):
        xray_manager.apply_config()
    else:
        # If config generation fails, report an error
        raise HTTPException(status_code=500, detail="Failed to generate Xray config file.")
        
    return new_inbound

@app.delete("/api/v1/inbounds/{inbound_id}")
async def remove_inbound(inbound_id: int, db: Session = Depends(get_db)):
    if crud.delete_inbound(db, inbound_id):
        if xray_manager.generate_config(db):
            xray_manager.apply_config()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Inbound not found.")

# --- CLIENT APIs ---
@app.get("/api/v1/inbounds/{inbound_id}/stats")
async def update_and_get_stats(inbound_id: int, db: Session = Depends(get_db)):
    clients = crud.get_clients_for_inbound(db, inbound_id)
    if not clients: return []
        
    client_emails = [c.remark for c in clients]
    live_stats = get_xray_stats(client_emails)
    
    traffic_to_update = {}
    for client in clients:
        stats = live_stats.get(client.remark)
        if stats:
            client.up_traffic += stats['up']
            client.down_traffic += stats['down']
            traffic_to_update[str(client.id)] = {'up': client.up_traffic, 'down': client.down_traffic}
            client.online = (stats['up'] > 0 or stats['down'] > 0)
        else:
            client.online = False
    
    if traffic_to_update:
        crud.update_clients_traffic(db, traffic_to_update)

    updated_clients = crud.get_clients_for_inbound(db, inbound_id)
    server_ip = get_server_public_ip()
    inbound = updated_clients[0].inbound if updated_clients else None
    if not inbound: return []

    for client in updated_clients:
        client.used_traffic_bytes = client.up_traffic + client.down_traffic
        stream_settings = json.loads(inbound.stream_settings)
        network = stream_settings.get("network", "tcp")
        link = f"{inbound.protocol}://{client.uuid}@{server_ip}:{inbound.port}"
        params = {"type": network, "security": stream_settings.get("security", "none")}
        if network == "ws":
            ws_opts = stream_settings.get("wsSettings", {})
            params["path"] = ws_opts.get("path", "/")
            params["host"] = ws_opts.get("headers", {}).get("Host", server_ip)
        elif network == "grpc":
            grpc_opts = stream_settings.get("grpcSettings", {})
            params["serviceName"] = grpc_opts.get("serviceName", "")
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        client.config_link = f"{link}?{query_string}#{client.remark}"
        
    return updated_clients


@app.post("/api/v1/inbounds/{inbound_id}/clients")
async def add_client_for_inbound(inbound_id: int, client_data: CreateClient, db: Session = Depends(get_db)):
    new_client = crud.create_client(
        db, 
        inbound_id=inbound_id, 
        remark=client_data.remark,
        total_gb=client_data.total_gb,
        expiry_time=client_data.expiry_time
    )
    
    if xray_manager.generate_config(db):
        xray_manager.apply_config()
        
    return new_client

@app.delete("/api/v1/clients/{client_id}")
async def remove_client(client_id: int, db: Session = Depends(get_db)):
    db_client = db.query(crud.models.Client).filter(crud.models.Client.id == client_id).first()
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found.")
    
    inbound_id = db_client.inbound_id
    db.delete(db_client)
    db.commit()
    
    if xray_manager.generate_config(db):
        xray_manager.apply_config()
        
    return {"status": "success", "inbound_id": inbound_id}

# --- System & Panel API Routes (Unchanged) ---
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
    }

    if public_key and private_key:
        uvicorn_args["ssl_keyfile"] = private_key
        uvicorn_args["ssl_certfile"] = public_key

    uvicorn.run("main:app", **uvicorn_args)