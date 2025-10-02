#!/bin/bash

# --- Configuration ---
# Replace with your actual GitHub repository URL
GIT_REPO_URL="https://github.com/mahdihadipoor/vpn-panel.git" 
INSTALL_DIR="/root/v-ui"
SERVICE_NAME="v-ui"

# --- Colors and Helpers ---
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_success() { echo -e "${GREEN}$1${NC}"; }
print_error() { echo -e "${RED}$1${NC}"; }
print_info() { echo -e "${BLUE}$1${NC}"; }

# --- Functions ---

install_dependencies() {
    print_info "Updating system and installing dependencies..."
    apt-get update
    apt-get install -y python3 python3-pip python3-venv git curl socat
    print_success "Dependencies installed."
}

install_xray() {
    print_info "Installing/Updating Xray-core..."
    bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
    if [ $? -ne 0 ]; then
        print_error "Xray installation failed."
        exit 1
    fi
    print_success "Xray-core installed successfully."
}

download_source() {
    print_info "Cloning panel source code from GitHub..."
    if [ -d "$INSTALL_DIR" ]; then
        print_info "Existing installation found. Creating a backup."
        mv "$INSTALL_DIR" "$INSTALL_DIR.bak_$(date +%F-%T)"
    fi
    git clone "$GIT_REPO_URL" "$INSTALL_DIR"
    if [ $? -ne 0 ]; then
        print_error "Failed to clone repository. Please check the URL in the script."
        exit 1
    fi
    cd "$INSTALL_DIR"
    print_success "Source code downloaded to $INSTALL_DIR"
}

setup_python_env() {
    print_info "Setting up Python virtual environment..."
    cd "$INSTALL_DIR"
    python3 -m venv venv
    source venv/bin/activate
    
    print_info "Installing required Python packages..."
    pip install --upgrade pip
    pip install -r requirements.txt
    deactivate
    print_success "Python environment is ready."
}

get_user_config() {
    print_info "\n--- Panel Configuration ---"
    read -p "Enter a username for the panel admin [default: admin]: " admin_user
    read -sp "Enter a password for the panel admin [default: admin]: " admin_pass
    echo
    read -p "Enter the port for the panel to listen on [default: 2053]: " panel_port

    # Set defaults if empty
    admin_user=${admin_user:-admin}
    admin_pass=${admin_pass:-admin}
    panel_port=${panel_port:-2053}

    print_info "Setting initial admin and port..."
    # Activate venv to run the commands
    source "$INSTALL_DIR/venv/bin/activate"
    python3 "$INSTALL_DIR/cli.py" set-admin "$admin_user" "$admin_pass"
    # The panel will read the port from an environment variable in the service file
    deactivate
}

create_service() {
    print_info "Creating systemd service file..."
    
    cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=V-UI Panel Service
After=network.target

[Service]
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 main.py
Environment="VUI_PORT=$panel_port"
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

    print_success "Service file created."
}

create_management_script() {
    print_info "Creating management script 'v-ui'..."
    cat > /usr/local/bin/${SERVICE_NAME} <<EOF
#!/bin/bash
cd "$INSTALL_DIR" || exit
source venv/bin/activate
python3 cli.py "\$@"
deactivate
EOF
    chmod +x /usr/local/bin/${SERVICE_NAME}
    print_success "Management script created. You can now use 'v-ui' command."
}

start_services() {
    print_info "Enabling and starting services..."
    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}
    systemctl start ${SERVICE_NAME}
    # Ensure Xray is also running
    systemctl enable xray
    systemctl restart xray
}

display_final_info() {
    # Get server IP
    SERVER_IP=$(curl -s http://ip.sb)
    
    # Check services status
    PANEL_STATUS=$(systemctl is-active ${SERVICE_NAME})
    XRAY_STATUS=$(systemctl is-active xray)

    if [ "$PANEL_STATUS" == "active" ]; then
        PANEL_STATUS_COLOR="${GREEN}Running${NC}"
    else
        PANEL_STATUS_COLOR="${RED}Not Running${NC}"
    fi

    if [ "$XRAY_STATUS" == "active" ]; then
        XRAY_STATUS_COLOR="${GREEN}Running${NC}"
    else
        XRAY_STATUS_COLOR="${RED}Not Running${NC}"
    fi

    echo -e "\n╔══════════════════════════════════════════════════╗"
    echo -e "║              ${GREEN}V-UI Panel Installation Complete${NC}            ║"
    echo -e "╠══════════════════════════════════════════════════╣"
    echo -e "║                                                  ║"
    echo -e "║   ${BLUE}Access URL:${NC}   http://${SERVER_IP}:${panel_port}                ║"
    echo -e "║   ${BLUE}Username:${NC}     ${admin_user}                                 ║"
    echo -e "║   ${BLUE}Password:${NC}     ${admin_pass}                                 ║"
    echo -e "║                                                  ║"
    echo -e "║   ${BLUE}Panel Status:${NC} ${PANEL_STATUS_COLOR}                             ║"
    echo -e "║   ${BLUE}Xray Status:${NC}  ${XRAY_STATUS_COLOR}                              ║"
    echo -e "║                                                  ║"
    echo -e "║   Use '${GREEN}v-ui${NC}' command for management.             ║"
    echo -e "║                                                  ║"
    echo -e "╚══════════════════════════════════════════════════╝"
}

# --- Main Execution ---
main() {
    install_dependencies
    install_xray
    download_source
    setup_python_env
    get_user_config
    create_service
    create_management_script
    start_services
    display_final_info
}

main