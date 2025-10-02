# cli.py
import typer
from sqlalchemy.orm import Session
import os
from app.database import SessionLocal, create_db_and_tables
from app import crud, models

# Ensure tables are created before running any command
create_db_and_tables()

app = typer.Typer(
    help="ابزار مدیریت پنل V-UI",
    add_completion=False,
    no_args_is_help=True
)

@app.command()
def version():
    """نمایش نسخه پنل مدیریتی."""
    print("V-UI Panel Manager v1.0.0")

@app.command()
def set_admin(
    username: str = typer.Argument(..., help="نام کاربری ادمین"),
    password: str = typer.Argument(..., help="رمز عبور جدید برای ادمین")
):
    """ایجاد یا به‌روزرسانی کاربر ادمین."""
    db: Session = SessionLocal()
    user = crud.get_user_by_username(db, username)
    if user:
        crud.update_user_password(db, username, password)
        print(f"✅ رمز عبور کاربر '{username}' با موفقیت به‌روزرسانی شد.")
    else:
        crud.create_user(db, username, password)
        print(f"✅ کاربر '{username}' با موفقیت ایجاد شد.")
    db.close()

@app.command()
def change_port(
    port: int = typer.Argument(..., help="پورت جدید برای پنل")
):
    """تغییر پورت پنل."""
    # This command will update the environment variable in the service file.
    # The management script will handle the file editing.
    if port < 1 or port > 65535:
        print("❌ پورت نامعتبر است. لطفاً عددی بین 1 تا 65535 وارد کنید.")
        raise typer.Exit(code=1)
        
    service_file = "/etc/systemd/system/v-ui.service"
    if os.path.exists(service_file):
        # Use sed to replace the port number in the Environment line
        os.system(f"sed -i 's/VUI_PORT=.*/VUI_PORT={port}/' {service_file}")
        os.system("systemctl daemon-reload")
        print(f"✅ پورت پنل به {port} تغییر یافت. برای اعمال تغییرات، پنل را ری‌استارت کنید: systemctl restart v-ui")
    else:
        print("❌ فایل سرویس پنل یافت نشد. آیا پنل به درستی نصب شده است؟")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()