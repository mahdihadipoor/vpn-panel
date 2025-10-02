#!/bin/bash

# Define the GitHub repository URL
GIT_REPO_URL="https://github.com/mahdihadipoor/vpn-panel.git"
INSTALL_DIR="/usr/local/v-ui"

# --- Helper Functions ---
print_success() {
    echo -e "\e[32m$1\e[0m"
}
print_error() {
    echo -e "\e[31m$1\e[0m"
}
print_info() {
    echo -e "\e[34m$1\e[0m"
}

# 1. System Update and Dependency Installation
install_dependencies() {
    print_info "Updating system and installing dependencies (python, pip, git)..."
    apt-get update
    apt-get install -y python3 python3-pip python3-venv git
    print_success "Dependencies installed successfully."
}

# 2. Download Source Code
download_source() {
    print_info "Cloning panel source code from GitHub..."
    if [ -d "$INSTALL_DIR" ]; then
        print_info "Existing installation found. Backing up..."
        mv "$INSTALL_DIR" "$INSTALL_DIR.bak_$(date +%s)"
    fi
    git clone "$GIT_REPO_URL" "$INSTALL_DIR"
    if [ $? -ne 0 ]; then
        print_error "Failed to clone repository. Please check the URL."
        exit 1
    fi
    cd "$INSTALL_DIR"
    print_success "Source code downloaded successfully."
}

# 3. Setup Python Environment and Install Packages
setup_python_env() {
    print_info "Setting up Python virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    
    print_info "Installing required Python packages..."
    pip install -r requirements.txt
    
    deactivate
    print_success "Python environment is ready."
}

# 4. Get User Input
get_user_config() {
    print_info "Please provide the initial configuration:"
    read -p "Enter a username for the panel admin: " admin_user
    read -sp "Enter a password for the panel admin: " admin_pass
    echo
    read -p "Enter the port for the panel to listen on (e.g., 443): " panel_port

    # Set defaults if empty
    if [ -z "$admin_user" ]; then admin_user="admin"; fi
    if [ -z "$admin_pass" ]; then admin_pass="admin"; fi
    if [ -z "$panel_port" ]; then panel_port=443; fi

    print_info "Setting initial admin and port..."
    # Activate venv to run the commands
    source "$INSTALL_DIR/venv/bin/activate"
    python3 "$INSTALL_DIR/cli.py" set-admin "$admin_user" "$admin_pass"
    # Note: We need a cli command to set the port. For now, we'll create the service file with it.
    deactivate
}

# 5. Create systemd Service File
create_service() {
    print_info "Creating systemd service file for the panel..."
    
    # We will pass the port as an environment variable to the panel
    cat > /etc/systemd/system/v-ui.service <<EOF
[Unit]
Description=V-UI Panel Service
After=network.target

[Service]
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 main.py
Environment="VUI_PORT=$panel_port"
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

    print_success "Service file created."
}

# 6. Start the Service
start_service() {
    print_info "Enabling and starting the panel service..."
    systemctl daemon-reload
    systemctl enable v-ui.service
    systemctl start v-ui.service
    print_success "Panel service started."
}

# --- Main Execution ---
main() {
    install_dependencies
    download_source
    setup_python_env
    get_user_config
    create_service
    start_service

    print_success "\n--- Installation Complete! ---"
    echo "Your panel is now running."
    echo "You can access it at: http://<your-server-ip>:$panel_port"
    echo "Admin Username: $admin_user"
    echo "Admin Password: [your_chosen_password]"
    echo "To view logs, run: journalctl -u v-ui -f"
    echo "To stop the panel, run: systemctl stop v-ui"
}

main