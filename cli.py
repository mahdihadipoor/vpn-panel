# cli.py

import typer
from sqlalchemy.orm import Session
from app.database import SessionLocal, create_db_and_tables
from app import crud

# Ensure tables are created before running any command
create_db_and_tables()

app = typer.Typer(
    help="ابزار مدیریت پنل V-UI",
    add_completion=False,
    no_args_is_help=True
)

# --- START OF NEW CODE ---
# By adding a second command, we force typer to expect a command name.
@app.command()
def version():
    """
    نمایش نسخه پنل مدیریتی.
    """
    print("V-UI Panel Manager v0.1.0")
# --- END OF NEW CODE ---


@app.command()
def set_admin(
    username: str = typer.Argument(..., help="نام کاربری ادمین"),
    password: str = typer.Argument(..., help="رمز عبور جدید برای ادمین")
):
    """
    ایجاد یا به‌روزرسانی کاربر ادمین.
    """
    db: Session = SessionLocal()
    
    user = crud.get_user_by_username(db, username)
    
    if user:
        crud.update_user_password(db, username, password)
        print(f"✅ رمز عبور کاربر '{username}' با موفقیت به‌روزرسانی شد.")
    else:
        crud.create_user(db, username, password)
        print(f"✅ کاربر '{username}' با موفقیت ایجاد شد.")
        
    db.close()

if __name__ == "__main__":
    app()