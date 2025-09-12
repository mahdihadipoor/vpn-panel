# config.py

# ================== Server Settings ==================
# IP address for the server to listen on.
# Use "0.0.0.0" to make it accessible from the network.
HOST = "0.0.0.0"

# Port for the server to listen on.
# Port 443 requires root privileges (sudo).
PORT = 443

# Enable auto-reload for development.
# Set this to False in a production environment.
RELOAD = True


# ============ Initial Admin User Settings ============
# This is only used on the very first run to create the initial admin user.
# After the first run, you must use the CLI tool to change the password.
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"