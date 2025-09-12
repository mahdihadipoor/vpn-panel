import uvicorn
import psutil
import datetime
import time
import subprocess
import socket
import os
import sys
import threading
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Body
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pathlib import Path

from app import crud, security
from app.database import SessionLocal, create_db_and_tables

# --- Create DB and Tables on initial import ---
create_db_and_tables()

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent

app.mount(
    "/static",
    StaticFiles(directory=str(Path(BASE_DIR, 'static'))),
    name="static"
)

# --- Global variables for network speed calculation ---
last_net_io = psutil.net_io_counters()
last_time = time.time()
# ----------------------------------------------------

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