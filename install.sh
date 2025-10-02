#!/bin/bash

# --- Configuration ---
GIT_REPO_URL="https://github.com/mahdihadipoor/vpn-panel.git" # آدرس ریپازیتوری شما
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

    admin_user=${admin_user:-admin}
    admin_pass=${admin_pass:-admin}
    panel_port=${panel_port:-2053}

    print_info "Setting initial admin user..."
    source "$INSTALL_DIR/venv/bin/activate"
    python3 "$INSTALL_DIR/cli.py" set-admin "$admin_user" "$admin_pass"
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
# FIX: Use the python from the virtual environment
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
    
    # This script will provide a menu for managing the panel
    cat > /usr/local/bin/${SERVICE_NAME} <<'EOF'
#!/bin/bash

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

show_menu() {
    clear
    echo -e "╔══════════════════════════════════════════════════╗"
    echo -e "║             ${BLUE}V-UI Panel Management Script${NC}            ║"
    echo -e "╟──────────────────────────────────────────────────╢"
    echo -e "║  ${GREEN}1.${NC}  Check Status                                 ║"
    echo -e "║  ${GREEN}2.${NC}  Start Panel & Xray                         ║"
    echo -e "║  ${GREEN}3.${NC}  Stop Panel & Xray                          ║"
    echo -e "║  ${GREEN}4.${NC}  Restart Panel & Xray                       ║"
    echo -e "║  ${GREEN}5.${NC}  View Panel Logs                            ║"
    echo -e "║  ${GREEN}6.${NC}  View Xray Logs                             ║"
    echo -e "╟──────────────────────────────────────────────────╢"
    echo -e "║  ${GREEN}7.${NC}  Reset Username & Password                  ║"
    echo -e "║  ${GREEN}8.${NC}  Change Panel Port                          ║"
    echo -e "╟──────────────────────────────────────────────────╢"
    echo -e "║  ${GREEN}9.${NC}  Update Panel                               ║"
    echo -e "║  ${GREEN}10.${NC} Uninstall Panel                            ║"
    echo -e "╟──────────────────────────────────────────────────╢"
    echo -e "║  ${GREEN}0.${NC}  Exit                                       ║"
    echo -e "╚══════════════════════════════════════════════════╝"
}

check_status() {
    PANEL_STATUS=$(systemctl is-active v-ui)
    XRAY_STATUS=$(systemctl is-active xray)
    echo -e "\n--- Status ---"
    if [ "$PANEL_STATUS" == "active" ]; then echo -e "Panel Status: ${GREEN}Running${NC}"; else echo -e "Panel Status: ${RED}Not Running${NC}"; fi
    if [ "$XRAY_STATUS" == "active" ]; then echo -e "Xray Status:  ${GREEN}Running${NC}"; else echo -e "Xray Status:  ${RED}Not Running${NC}"; fi
    echo "----------------"
    read -p "Press [Enter] to return to the menu..."
}

run_action() {
    systemctl $1 v-ui
    systemctl $1 xray
    echo -e "\nServices have been ${1}ed."
    sleep 2
}

view_logs() {
    journalctl -u $1 -f
    read -p "Press [Enter] to return to the menu..."
}

reset_admin() {
    read -p "Enter new username: " username
    read -sp "Enter new password: " password
    echo
    cd /root/v-ui
    source venv/bin/activate
    python3 cli.py set-admin "$username" "$password"
    deactivate
    read -p "Press [Enter] to return to the menu..."
}

change_port() {
    read -p "Enter new port: " port
    cd /root/v-ui
    source venv/bin/activate
    python3 cli.py change-port "$port"
    deactivate
    read -p "Press [Enter] to return to the menu..."
}

update_panel() {
    echo "This will re-download the installation script and run it."
    read -p "Are you sure you want to update? (y/n): " confirm
    if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
        curl -O https://raw.githubusercontent.com/mahdihadipoor/vpn-panel/main/install.sh
        bash install.sh
        exit 0
    fi
}

uninstall_panel() {
    read -p "This will stop services and remove all panel files. Are you sure? (y/n): " confirm
     if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
        systemctl stop v-ui
        systemctl disable v-ui
        rm /etc/systemd/system/v-ui.service
        systemctl daemon-reload
        rm -rf /root/v-ui
        rm /usr/local/bin/v-ui
        echo "Panel uninstalled."
    fi
     read -p "Press [Enter] to exit..."
}


while true; do
    show_menu
    read -p "Please enter your selection [0-10]: " choice
    case $choice in
        1) check_status ;;
        2) run_action "start" ;;
        3) run_action "stop" ;;
        4) run_action "restart" ;;
        5) view_logs "v-ui" ;;
        6) view_logs "xray" ;;
        7) reset_admin ;;
        8) change_port ;;
        9) update_panel ;;
        10) uninstall_panel ;;
        0) exit 0 ;;
        *) echo -e "${RED}Invalid option. Please try again.${NC}" && sleep 2 ;;
    esac
done
EOF
    chmod +x /usr/local/bin/${SERVICE_NAME}
    print_success "Management script created. You can now use '${SERVICE_NAME}' command."
}

start_services() {
    print_info "Enabling and starting services..."
    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}
    systemctl start ${SERVICE_NAME}
    systemctl enable xray
    systemctl restart xray
}

display_final_info() {
    SERVER_IP=$(curl -s4 icanhazip.com || curl -s6 icanhazip.com)
    
    sleep 3

    PANEL_STATUS=$(systemctl is-active ${SERVICE_NAME})
    XRAY_STATUS=$(systemctl is-active xray)

    if [ "$PANEL_STATUS" == "active" ]; then PANEL_STATUS_COLOR="${GREEN}Running${NC}"; else PANEL_STATUS_COLOR="${RED}Not Running${NC}"; fi
    if [ "$XRAY_STATUS" == "active" ]; then XRAY_STATUS_COLOR="${GREEN}Running${NC}"; else XRAY_STATUS_COLOR="${RED}Not Running${NC}"; fi

    echo -e "\n╔══════════════════════════════════════════════════╗"
    echo -e "║              ${GREEN}V-UI Panel Installation Complete${NC}            ║"
    echo -e "╠══════════════════════════════════════════════════╣"
    echo -e "║                                                  ║"
    echo -e "║   ${BLUE}Access URL:${NC}   http://${SERVER_IP}:${panel_port}                ║"
    echo -e "║   ${BLUE}Username:${NC}     ${admin_user}                                 ║"
    echo -e "║   ${BLUE}Password:${NC}     [your chosen password]                     ║"
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
    if [ "$(id -u)" != "0" ]; then
       print_error "This script must be run as root" 
       exit 1
    fi
    
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