# main.py
import uvicorn, psutil, datetime, time, subprocess, socket, os, sys, threading, json, uuid, grpc, secrets, base64
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Body, Response, status, Header
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
from urllib.parse import quote # THIS IS THE FIX

from app import crud, models, security
from app.database import SessionLocal, create_db_and_tables
from app.xray_api import stats_pb2, stats_pb2_grpc

create_db_and_tables()
app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(Path(BASE_DIR, 'static'))), name="static")

templates = Jinja2Templates(directory=str(Path(BASE_DIR, "templates")))

# --- Error Logging ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"\n--- Validation Error ---\nURL: {request.url}\nDetails: {exc.errors()}\n--- End Validation Error ---\n")
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": exc.errors()})


# --- Helper functions & Auth ---
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

async def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("session_token")
    if not token: return None
    return crud.get_user_by_session_token(db, token=token)

async def require_auth(user: models.User = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/"})
    return user
    

# --- Global variables for network speed calculation ---
last_net_io = psutil.net_io_counters()
last_time = time.time()
# ----------------------------------------------------



# --- Xray API Client ---
# --- Other Helper Functions ---
def get_xray_stats(emails: List[str]):
    try:
        channel = grpc.insecure_channel('127.0.0.1:62789')
        stub = stats_pb2_grpc.StatsServiceStub(channel)
        traffic_data = {}
        req = stats_pb2.QueryStatsRequest(pattern="user>>>", reset=True)
        res = stub.QueryStats(req)
        for stat in res.stat:
            parts = stat.name.split('>>>')
            if len(parts) == 4 and parts[0] == 'user':
                email, direction = parts[1], parts[3]
                if email not in traffic_data:
                    traffic_data[email] = {'up': 0, 'down': 0}
                if direction == 'uplink':
                    traffic_data[email]['up'] += stat.value
                elif direction == 'downlink':
                    traffic_data[email]['down'] += stat.value
        return traffic_data
    except Exception as e:
        print(f"Could not connect to Xray API: {e}")
        return {}

def get_server_public_ip():
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
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
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


class CreateSubscription(BaseModel):
    remark: str
    total_mb: int = Field(0, ge=0)
    expiry_days: int = Field(0, ge=0)

class AddClientToSubscription(BaseModel):
    inbound_id: int

class UpdateSubscription(BaseModel):
    enabled: Optional[bool] = None
    total_mb: Optional[int] = Field(None, ge=0)
    expiry_days: Optional[int] = Field(None)
    reset_traffic: Optional[bool] = False

# --- NEW: Public Subscription Routes ---
@app.get("/sub/{remark}")
async def handle_subscription_request(
    request: Request, 
    remark: str, 
    db: Session = Depends(get_db), 
    user_agent: Optional[str] = Header(None)
):
    sub = crud.get_subscription_by_remark(db, remark)
    if not sub or not sub.enabled:
        raise HTTPException(status_code=404, detail="Subscription not found or has been disabled.")

    vpn_clients_ua = ["v2rayng", "nekoray", "shadowrocket", "clash", "hiddify", "sing-box", "v2box"]
    is_vpn_client = any(keyword in user_agent.lower() for keyword in vpn_clients_ua) if user_agent else False

    total_usage_bytes = crud.get_total_usage_for_subscription(db, sub.id)

    if is_vpn_client:
        settings = crud.get_settings(db)
        address = settings.domain_name or get_server_public_ip()
        
        # --- Create the Fake Info Config ---
        gb_total = sub.total_gb
        gb_used = total_usage_bytes / (1024**3)
        gb_left = gb_total - gb_used
        
        days_left_str = "∞"
        if sub.expiry_time > 0:
            days_left = (sub.expiry_time - time.time()) / (24 * 60 * 60)
            if days_left > 0:
                days_left_str = f"{int(days_left)} روز"
            else:
                days_left_str = "0 روز"

        total_str = f"{gb_total:.2f}GB" if gb_total > 0 else "∞"
        left_str = f"{gb_left:.2f}GB" if gb_total > 0 else "∞"
        
        fake_config_remark = f" ⏳ {days_left_str} | 🔋 {left_str} "
        fake_config = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?type=tcp#{quote(fake_config_remark)}"
        
        all_configs = [fake_config]
        # ---------------------------------

        for client in sub.clients:
            inbound = client.inbound
            stream_settings = json.loads(inbound.stream_settings)
            network = stream_settings.get("network", "tcp")
            config_name = f"{inbound.remark}-{client.remark}"
            link = f"{inbound.protocol}://{client.uuid}@{address}:{inbound.port}"
            params = {"type": network, "security": stream_settings.get("security", "none")}
            if network == "ws":
                ws_opts = stream_settings.get("wsSettings", {})
                params["path"] = ws_opts.get("path", "/")
                params["host"] = ws_opts.get("headers", {}).get("Host", address)
            elif network == "grpc":
                grpc_opts = stream_settings.get("grpcSettings", {})
                params["serviceName"] = grpc_opts.get("serviceName", "")
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            full_link = f"{link}?{query_string}#{quote(config_name)}"
            all_configs.append(full_link)
        
        encoded_configs = base64.b64encode("\n".join(all_configs).encode("utf-8")).decode("utf-8")
        
        response = Response(content=encoded_configs, media_type="text/plain")
        response.headers["Profile-Title"] = sub.remark
        user_info = (
            f"upload={total_usage_bytes}; "
            f"download=0; "
            f"total={sub.total_gb * 1024 * 1024 * 1024}; "
            f"expire={sub.expiry_time}"
        )
        response.headers["Subscription-Userinfo"] = user_info
        return response

    else:
        total_bytes = sub.total_gb * (1024**3)
        percentage = (total_usage_bytes / total_bytes * 100) if total_bytes > 0 else 0
        
        context = {
            "request": request,
            "remark": sub.remark,
            "enabled": sub.enabled,
            "used_gb": f"{(total_usage_bytes / (1024**3)):.2f}",
            "total_gb_text": f"{sub.total_gb:.2f} GB" if sub.total_gb > 0 else "∞",
            "progress_percentage": min(percentage, 100),
            "expiry_text": datetime.datetime.fromtimestamp(sub.expiry_time).strftime('%Y-%m-%d') if sub.expiry_time > 0 else "Never",
            "sub_link": str(request.url)
        }
        return templates.TemplateResponse("subscription.html", context)


# --- NEW: Subscription API Endpoints ---
@app.get("/api/v1/subscriptions", dependencies=[Depends(require_auth)])
async def read_subscriptions(db: Session = Depends(get_db)):
    return crud.get_subscriptions(db)

@app.post("/api/v1/subscriptions", dependencies=[Depends(require_auth)])
async def create_subscription_endpoint(sub_data: CreateSubscription, db: Session = Depends(get_db)):
    total_gb = sub_data.total_mb / 1024 if sub_data.total_mb > 0 else 0
    expiry_time = 0
    if sub_data.expiry_days > 0:
        expiry_time = int(time.time()) + (sub_data.expiry_days * 24 * 60 * 60)
    
    return crud.create_subscription(db, remark=sub_data.remark, total_gb=total_gb, expiry_time=expiry_time)

@app.put("/api/v1/subscriptions/{sub_id}", dependencies=[Depends(require_auth)])
async def update_subscription_endpoint(sub_id: int, sub_data: UpdateSubscription, db: Session = Depends(get_db)):
    update_data = {}
    if sub_data.enabled is not None:
        update_data["enabled"] = sub_data.enabled
    if sub_data.total_mb is not None:
        update_data["total_gb"] = sub_data.total_mb / 1024
    if sub_data.expiry_days is not None:
        if sub_data.expiry_days > 0:
            update_data["expiry_time"] = int(time.time()) + (sub_data.expiry_days * 24 * 60 * 60)
        else:
            update_data["expiry_time"] = 0
    
    updated_sub = crud.update_subscription(db, sub_id, update_data)

    if sub_data.reset_traffic:
        crud.reset_traffic_for_subscription(db, sub_id)

    if not updated_sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
        
    return updated_sub

@app.post("/api/v1/subscriptions/{sub_id}/clients", dependencies=[Depends(require_auth)])
async def add_client_to_subscription_endpoint(sub_id: int, client_data: AddClientToSubscription, db: Session = Depends(get_db)):
    new_client = crud.create_client(db, inbound_id=client_data.inbound_id, subscription_id=sub_id)
    
    if xray_manager.generate_config(db):
        xray_manager.apply_config()
        
    return new_client
   
# --- Page and Auth Routes ---
@app.get("/", response_class=HTMLResponse)
async def read_root(user: models.User = Depends(get_current_user)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return FileResponse(str(Path(BASE_DIR, 'templates', 'login.html')))

@app.post("/login")
async def login(response: Response, db: Session = Depends(get_db), username: str = Form(...), password: str = Form(...)):
    user = crud.get_user_by_username(db, username=username)
    if not user or not security.verify_password(password, user.hashed_password):
        return JSONResponse(
            status_code=401, 
            content={"success": False, "message": "نام کاربری یا رمز عبور اشتباه است"}
        )
    
    # Create session token
    token = secrets.token_hex(16)
    crud.update_user_session(db, user_id=user.id, token=token)

    # Create a JSON response first
    json_response = JSONResponse(
        status_code=200,
        content={"success": True, "redirect_url": "/dashboard"}
    )
    
    # Set the cookie on the JSON response before returning it
    json_response.set_cookie(key="session_token", value=token, httponly=True, max_age=86400) # Cookie expires in 1 day
    
    return json_response

@app.get("/logout")
async def logout(response: Response, db: Session = Depends(get_db), user: models.User = Depends(require_auth)):
    crud.update_user_session(db, user_id=user.id, token=None)
    response.delete_cookie("session_token")
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(user: models.User = Depends(require_auth)):
    return FileResponse(str(Path(BASE_DIR, 'templates', 'dashboard.html')))

@app.get("/panel-settings", response_class=HTMLResponse)
async def get_panel_settings_page(user: models.User = Depends(require_auth)):
    return FileResponse(str(Path(BASE_DIR, 'templates', 'panel_settings.html')))

@app.get("/inbounds", response_class=HTMLResponse)
async def get_inbounds_page(user: models.User = Depends(require_auth)):
    return FileResponse(str(Path(BASE_DIR, 'templates', 'inbounds.html')))

@app.get("/inbounds/{inbound_id}", response_class=HTMLResponse)
async def get_clients_page(inbound_id: int):
    return FileResponse(str(Path(BASE_DIR, 'templates', 'clients.html')))

class DomainInfo(BaseModel):
    domain_name: str
        
# --- XRAY CONFIG MANAGER ---   
class XrayManager:
    def __init__(self, config_path="/usr/local/etc/xray/config.json"):
        self.config_path = config_path

    def generate_config(self, db: Session):
        config = { "log": { "loglevel": "warning" } }
        config.update({
            "api": { "tag": "api", "services": ["StatsService"] },
            "stats": {},
            "policy": {
                "levels": { "0": { "statsUserUplink": True, "statsUserDownlink": True } },
                "system": { "statsInboundUplink": True, "statsInboundDownlink": True }
            },
            "inbounds": [{ "tag": "api", "listen": "127.0.0.1", "port": 62789, "protocol": "dokodemo-door", "settings": { "address": "127.0.0.1" } }],
            "outbounds": [{ "protocol": "freedom", "tag": "direct" }, { "protocol": "blackhole", "tag": "api" }],
            "routing": { "domainStrategy": "AsIs", "rules": [ { "type": "field", "inboundTag": ["api"], "outboundTag": "api" } ] }
        })

        all_inbounds = crud.get_inbounds(db)
        for inbound in all_inbounds:
            if not inbound.enabled: continue
            clients_for_this_inbound = crud.get_clients_for_inbound(db, inbound.id)
            
            xray_clients = [{"id": c.uuid, "email": c.remark, "level": 0} for c in clients_for_this_inbound if c.subscription.enabled]
            
            if not xray_clients: continue
            stream_settings = json.loads(inbound.stream_settings)
            xray_inbound = {
                "port": inbound.port, "listen": "0.0.0.0", "protocol": inbound.protocol,
                "settings": { "clients": xray_clients, "decryption": "none" },
                "streamSettings": stream_settings, "tag": f"inbound-{inbound.port}"
            }
            config["inbounds"].append(xray_inbound)
        
        try:
            with open(self.config_path, 'w') as f: json.dump(config, f, indent=4)
            return True
        except Exception as e:
            print(f"FATAL: Error writing Xray config: {e}")
            return False

    def apply_config(self):
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

class UpdateInbound(BaseModel):
    enabled: Optional[bool] = None

class CreateClient(BaseModel):
    remark: str
    subscription_remark: str
    total_mb: int = Field(0, ge=0)
    expiry_days: int = Field(0, ge=0)

class UpdateClient(BaseModel):
    enabled: Optional[bool] = None
    total_mb: Optional[int] = Field(None, ge=0)
    expiry_time: Optional[int] = Field(None, ge=0)
    reset_traffic: Optional[bool] = False

# --- INBOUND APIs (FIXED) ---
@app.get("/api/v1/inbounds", dependencies=[Depends(require_auth)])
async def read_inbounds(db: Session = Depends(get_db)):
    inbounds = crud.get_inbounds(db)
    for ib in inbounds:
        ib.client_count = len(ib.clients)
    return inbounds

@app.post("/api/v1/inbounds", dependencies=[Depends(require_auth)])
async def add_inbound(inbound_data: CreateInbound, db: Session = Depends(get_db)):
    if crud.get_inbound_by_port(db, inbound_data.port) or crud.get_inbound_by_remark(db, inbound_data.remark):
        raise HTTPException(status_code=400, detail="Port or Remark already in use.")
    inbound_dict = inbound_data.dict()
    inbound_dict['stream_settings'] = json.dumps(inbound_data.stream_settings.dict(exclude_none=True))
    new_inbound = crud.create_inbound(db, inbound_dict)
    if xray_manager.generate_config(db):
        xray_manager.apply_config()
    else:
        raise HTTPException(status_code=500, detail="Failed to generate Xray config file.")
    return new_inbound

@app.put("/api/v1/inbounds/{inbound_id}", dependencies=[Depends(require_auth)])
async def update_inbound_data(inbound_id: int, inbound_data: UpdateInbound, db: Session = Depends(get_db)):
    updated_inbound = crud.update_inbound(db, inbound_id, {"enabled": inbound_data.enabled})
    if not updated_inbound:
        raise HTTPException(status_code=404, detail="Inbound not found")
    if xray_manager.generate_config(db):
        xray_manager.apply_config()
    return updated_inbound

@app.delete("/api/v1/inbounds/{inbound_id}", dependencies=[Depends(require_auth)])
async def remove_inbound(inbound_id: int, db: Session = Depends(get_db)):
    if crud.delete_inbound(db, inbound_id):
        if xray_manager.generate_config(db):
            xray_manager.apply_config()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Inbound not found.")

# --- CLIENT APIs ---
@app.get("/api/v1/inbounds/{inbound_id}/stats", dependencies=[Depends(require_auth)])
async def update_and_get_stats(inbound_id: int, db: Session = Depends(get_db)):
    clients = crud.get_clients_for_inbound(db, inbound_id)
    if not clients: return []

    client_remarks = [c.remark for c in clients]
    live_stats = get_xray_stats(client_remarks)
    
    if live_stats:
        crud.update_clients_traffic(db, live_stats)

    needs_reload = False
    now = int(time.time())

    for client in clients:
        if client.subscription.enabled:
            total_usage_bytes = crud.get_total_usage_for_subscription(db, client.subscription_id)
            limit_bytes = client.subscription.total_gb * 1024 * 1024 * 1024
            if (limit_bytes > 0 and total_usage_bytes >= limit_bytes) or \
               (client.subscription.expiry_time > 0 and now >= client.subscription.expiry_time):
                crud.update_subscription(db, client.subscription_id, {"enabled": False})
                needs_reload = True
    
    if needs_reload:
        db.commit() # Commit the session to reflect disabled status before generating config
        if xray_manager.generate_config(db):
            xray_manager.apply_config()
    
    updated_clients = crud.get_clients_for_inbound(db, inbound_id)
    inbound = crud.get_inbound_by_id(db, inbound_id)
    if not inbound: return []

    settings = crud.get_settings(db)
    domain_address = settings.domain_name if settings.domain_name else None
    ip_address = get_server_public_ip()

    # Pre-calculate total usage for each subscription to avoid repeated DB calls
    subscription_usages = {}
    for client in updated_clients:
        if client.subscription_id not in subscription_usages:
            total_usage = crud.get_total_usage_for_subscription(db, client.subscription_id)
            subscription_usages[client.subscription_id] = total_usage

    def generate_link(address, client_uuid, client_remark, inbound_remark):
        if not address: return ""
        stream_settings = json.loads(inbound.stream_settings)
        network = stream_settings.get("network", "tcp")
        config_name = f"{inbound_remark}-{client_remark}"
        link = f"{inbound.protocol}://{client_uuid}@{address}:{inbound.port}"
        params = {"type": network, "security": stream_settings.get("security", "none")}
        if network == "ws":
            ws_opts = stream_settings.get("wsSettings", {})
            params["path"] = ws_opts.get("path", "/")
            params["host"] = ws_opts.get("headers", {}).get("Host", address)
        elif network == "grpc":
            grpc_opts = stream_settings.get("grpcSettings", {})
            params["serviceName"] = grpc_opts.get("serviceName", "")
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{link}?{query_string}#{quote(config_name)}"

    response_data = []
    for client in updated_clients:
        client_stats = live_stats.get(client.remark, {'up': 0, 'down': 0})
        
        # *** THIS IS THE MAIN CHANGE ***
        # Use the pre-calculated total subscription usage for the progress bar
        total_subscription_usage = subscription_usages.get(client.subscription_id, 0)
        
        response_data.append({
            "id": client.id,
            "remark": client.remark,
            "uuid": client.uuid,
            "enabled": client.subscription.enabled,
            "total_gb": client.subscription.total_gb,
            "expiry_time": client.subscription.expiry_time,
            "sub_remark": client.subscription.remark,
            "up_traffic": client.up_traffic,
            "down_traffic": client.down_traffic,
            "used_traffic_bytes": total_subscription_usage, # Use total usage here
            "online": (client_stats['up'] > 0 or client_stats['down'] > 0),
            "config_link_ip": generate_link(ip_address, client.uuid, client.remark, inbound.remark),
            "config_link_domain": generate_link(domain_address, client.uuid, client.remark, inbound.remark)
        })
        
    return response_data

@app.post("/api/v1/inbounds/{inbound_id}/clients", dependencies=[Depends(require_auth)])
async def add_client_to_inbound(inbound_id: int, client_data: CreateClient, db: Session = Depends(get_db)):
    subscription = crud.get_subscription_by_remark(db, client_data.subscription_remark)
    if not subscription:
        total_gb = client_data.total_mb / 1024 if client_data.total_mb > 0 else 0
        expiry_time = 0
        if client_data.expiry_days > 0:
            expiry_time = int(time.time()) + (client_data.expiry_days * 24 * 60 * 60)
        subscription = crud.create_subscription(db, remark=client_data.subscription_remark, total_gb=total_gb, expiry_time=expiry_time)
    
    new_client = crud.create_client(db, inbound_id=inbound_id, subscription_id=subscription.id, remark=client_data.remark)
    
    if xray_manager.generate_config(db):
        xray_manager.apply_config()
    return new_client

@app.delete("/api/v1/clients/{client_id}", dependencies=[Depends(require_auth)])
async def remove_client(client_id: int, db: Session = Depends(get_db)):
    db_client = crud.get_client_by_id(db, client_id)
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found.")
    
    db.delete(db_client)
    db.commit()
    
    if xray_manager.generate_config(db):
        xray_manager.apply_config()
        
    return {"status": "success"}

@app.put("/api/v1/clients/{client_id}", dependencies=[Depends(require_auth)])
async def update_client_data(client_id: int, client_data: UpdateClient, db: Session = Depends(get_db)):
    db_client = crud.get_client_by_id(db, client_id)
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found.")

    sub_update_data = {}
    if client_data.enabled is not None:
        sub_update_data["enabled"] = client_data.enabled
    
    if client_data.total_mb is not None:
        sub_update_data["total_gb"] = client_data.total_mb / 1024 if client_data.total_mb > 0 else 0

    if client_data.expiry_time is not None:
        sub_update_data["expiry_time"] = client_data.expiry_time

    if sub_update_data:
        crud.update_subscription(db, db_client.subscription_id, sub_update_data)

    if client_data.reset_traffic:
        crud.reset_traffic_for_subscription(db, db_client.subscription_id)

    if 'enabled' in sub_update_data:
        if xray_manager.generate_config(db):
            xray_manager.apply_config()
    
    updated_sub = crud.get_subscription_by_id(db, db_client.subscription_id)
    return {"status": "success", "subscription_id": updated_sub.id}

# --- System & Panel API Routes (Unchanged) ---
@app.get("/api/v1/system/stats", dependencies=[Depends(require_auth)])
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

@app.get("/api/v1/panel/settings", dependencies=[Depends(require_auth)])
async def read_settings(db: Session = Depends(get_db)):
    settings = crud.get_settings(db)
    return settings

@app.post("/api/v1/panel/settings", dependencies=[Depends(require_auth)])
async def write_settings(settings_data: dict = Body(...), db: Session = Depends(get_db)):
    updated_settings = crud.update_settings(db, settings_data)
    if not updated_settings:
        raise HTTPException(status_code=404, detail="Settings not found.")
    return {"status": "success", "message": "Settings saved successfully."}

@app.post("/api/v1/panel/get-certificate", dependencies=[Depends(require_auth)])
async def get_certificate(domain_info: DomainInfo, db: Session = Depends(get_db)):
    domain = domain_info.domain_name.strip()
    if not domain:
        raise HTTPException(status_code=400, detail="Domain name cannot be empty.")
    command = f"sudo certbot certonly --standalone -d {domain} --non-interactive --agree-tos --email admin@{domain}"
    try:
        subprocess.run(command, shell=True, check=True, capture_output=True, text=True, timeout=300)
        cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        key_path = f"/etc/letsencrypt/live/{domain}/privkey.pem"
        if os.path.exists(cert_path) and os.path.exists(key_path):
            crud.update_settings(db, {"domain_name": domain, "public_key_path": cert_path, "private_key_path": key_path})
            return {"status": "success", "message": "Certificate obtained successfully! Please restart the panel."}
        else:
            raise HTTPException(status_code=500, detail="Certificate files not found after certbot run.")
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Certbot failed: {e.stderr.strip()}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Certbot command timed out.")

@app.post("/api/v1/panel/restart", dependencies=[Depends(require_auth)])
async def restart_panel():
    def restart_script():
        time.sleep(1)
        os.execv(sys.executable, ['python3'] + sys.argv)
    threading.Thread(target=restart_script).start()
    return {"status": "success", "message": "Panel is restarting..."}

@app.post("/api/v1/xray/start", dependencies=[Depends(require_auth)])
async def start_xray():
    run_shell_command("sudo systemctl start xray.service")
    if get_xray_status() == "active":
        return {"status": "success", "message": "Xray started successfully."}
    raise HTTPException(status_code=500, detail="Failed to start Xray.")

@app.post("/api/v1/xray/stop", dependencies=[Depends(require_auth)])
async def stop_xray():
    run_shell_command("sudo systemctl stop xray.service")
    if get_xray_status() != "active":
        return {"status": "success", "message": "Xray stopped successfully."}
    raise HTTPException(status_code=500, detail="Failed to stop Xray.")

@app.post("/api/v1/xray/restart", dependencies=[Depends(require_auth)])
async def restart_xray():
    run_shell_command("sudo systemctl restart xray.service")
    time.sleep(1)
    if get_xray_status() == "active":
        return {"status": "success", "message": "Xray restarted successfully."}
    raise HTTPException(status_code=500, detail="Failed to restart Xray.")


if __name__ == "__main__":
    db = SessionLocal()
    
    # NEW: Read port from environment variable set by the service file
    default_port = crud.get_settings(db).listen_port if crud.get_settings(db) else 2053
    listen_port = int(os.environ.get("VUI_PORT", default_port))

    settings = crud.get_settings(db)
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