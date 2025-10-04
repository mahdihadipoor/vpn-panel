// static/js/inbounds.js
document.addEventListener('DOMContentLoaded', () => {
    // --- STATE & CACHE ---
    let statsInterval = null;
    const clientDataCache = new Map();

    // --- DOM ELEMENTS ---
    const inboundsTbody = document.getElementById('inbounds-table-body');
    const addInboundModal = document.getElementById('add-inbound-modal');
    const addClientModal = document.getElementById('add-client-modal');
    const editClientModal = document.getElementById('edit-client-modal');
    const qrCodeModal = document.getElementById('qr-code-modal');
    const addInboundForm = document.getElementById('add-inbound-form');
    const addClientForm = document.getElementById('add-client-form');
    const editClientForm = document.getElementById('edit-client-form');
    const qrUseIpToggle = document.getElementById('qr-use-ip-toggle');

    // --- MODAL HANDLING ---
    const setupModal = (modal, openBtnId) => {
        if (!modal) return { show: () => {}, hide: () => {} };
        const openBtn = document.getElementById(openBtnId);
        const closeBtns = modal.querySelectorAll('.close-modal-btn');
        const show = () => modal.style.display = 'flex';
        const hide = () => modal.style.display = 'none';
        
        if (openBtn) openBtn.addEventListener('click', show);
        closeBtns.forEach(btn => btn.addEventListener('click', hide));
        modal.addEventListener('click', (e) => { if (e.target === modal) hide(); });
        return { show, hide };
    };
    const inboundModal = setupModal(addInboundModal, 'add-inbound-btn');
    const clientModal = setupModal(addClientModal, null);
    const editModal = setupModal(editClientModal, null);
    const qrModal = setupModal(qrCodeModal, null);

    // --- HELPERS ---
    const apiCall = async (url, options = {}) => {
        try {
            const response = await fetch(url, options);
            if (response.status === 401) {
                window.location.href = '/';
                return;
            }
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Failed to parse error response.' }));
                throw new Error(errorData.detail);
            }
            if (response.status === 204) return null;
            return response.json();
        } catch (error) {
            console.error('API Call Failed:', error);
            alert(`API Error: ${error.message}`);
            throw error;
        }
    };

    const generateQrCode = (containerEl, text) => {
        containerEl.innerHTML = '';
        if (text) {
            new QRCode(containerEl, { text, width: 200, height: 200, correctLevel: QRCode.CorrectLevel.L });
        }
    };
    
    const formatBytes = (bytes) => {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    const formatDate = (timestamp) => {
        if (!timestamp || timestamp === 0) return '∞';
        const date = new Date(timestamp * 1000);
        return date.toLocaleDateString('en-CA');
    }

    // --- RENDER FUNCTIONS ---
    const renderInbounds = (inbounds) => {
        inboundsTbody.innerHTML = '';
        if (inbounds.length === 0) {
            inboundsTbody.innerHTML = '<tr><td colspan="8" class="text-center">No inbounds found.</td></tr>';
            return;
        }
        inbounds.forEach(ib => {
            inboundsTbody.innerHTML += `
                <tr class="inbound-row" data-id="${ib.id}">
                    <td><button class="expand-btn" data-action="expand">+</button></td>
                    <td>${ib.id}</td>
                    <td>${ib.remark}</td>
                    <td><label class="switch"><input type="checkbox" ${ib.enabled ? 'checked' : ''} data-action="toggle-inbound"><span class="slider"></span></label></td>
                    <td>${ib.port}</td>
                    <td><span class="protocol-tag">${ib.protocol}</span></td>
                    <td><span class="client-count">${ib.client_count}</span></td>
                    <td><button class="btn-danger btn-sm" data-action="delete-inbound">Delete</button></td>
                </tr>
                <tr class="clients-row" id="clients-row-${ib.id}"><td colspan="8" class="clients-container"></td></tr>
            `;
        });
    };

    const renderClients = (inboundId, clients) => {
        const container = document.querySelector(`#clients-row-${inboundId} .clients-container`);
        if (!container) return; 

        clientDataCache.set(inboundId, clients);

        let clientsHtml = `
            <div class="clients-sub-table-wrapper">
                <div class="sub-table-header">
                    <h4>Clients</h4>
                    <button class="btn btn-primary btn-sm" data-action="add-client"><i class="fas fa-plus"></i> Add Client</button>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th style="width: 15%;">Menu</th>
                            <th style="width: 10%;">Enabled</th>
                            <th style="width: 10%;">Online</th>
                            <th>Client</th>
                            <th style="width: 25%;">Traffic</th>
                            <th style="width: 10%;">Duration</th>
                            <th style="width: 10%;">Actions</th>
                        </tr>
                    </thead>
                    <tbody>`;
        if (clients.length > 0) {
            clients.forEach(c => {
                const totalBytes = c.total_gb * 1024 * 1024 * 1024;
                const usedBytes = c.used_traffic_bytes;
                const percentage = totalBytes > 0 ? (usedBytes / totalBytes) * 100 : 0;
                const trafficLimitText = c.total_gb > 0 ? `/ ${c.total_gb.toFixed(2)} GB` : '/ ∞';
                const onlineStatus = c.online ? 'online' : 'offline';
                const onlineText = c.online ? 'Online' : 'Offline';

                clientsHtml += `
                    <tr class="client-row" data-id="${c.id}">
                        <td>
                            <div class="client-menu-icons">
                                <i class="fas fa-qrcode" title="Show QR Code" data-action="show-qr"></i>
                                <i class="fas fa-copy" title="Copy Link" data-action="copy-link"></i>
                                <i class="fas fa-edit" title="Edit Client" data-action="edit-client"></i>
                            </div>
                        </td>
                        <td><label class="switch"><input type="checkbox" ${c.enabled ? 'checked' : ''} data-action="toggle-client"><span class="slider"></span></label></td>
                        <td>
                            <div class="online-status ${onlineStatus}">
                                <span class="dot"></span>
                                <span>${onlineText}</span>
                            </div>
                        </td>
                        <td>${c.remark}</td>
                        <td>
                            <div class="traffic-bar"><div class="traffic-bar-fill" style="width: ${Math.min(percentage, 100)}%;"></div></div>
                            <div class="traffic-text">${formatBytes(usedBytes)} ${trafficLimitText}</div>
                        </td>
                        <td>${formatDate(c.expiry_time)}</td>
                        <td><button class="btn-danger btn-sm" data-action="delete-client">Delete</button></td>
                    </tr>
                `;
            });
        } else {
            clientsHtml += '<tr><td colspan="7" class="text-center">No clients for this inbound.</td></tr>';
        }
        clientsHtml += '</tbody></table></div>';
        container.innerHTML = clientsHtml;
    };

    const updateStats = async (inboundId) => {
        try {
            const clients = await apiCall(`/api/v1/inbounds/${inboundId}/stats`);
            renderClients(inboundId, clients);
        } catch (error) {
            console.error("Failed to update stats:", error);
            if (statsInterval) clearInterval(statsInterval);
        }
    };

    // --- EVENT HANDLER ---
    inboundsTbody.addEventListener('click', async (e) => {
        const target = e.target;
        const action = target.dataset.action;
        if (!action) return;

        const inboundRow = target.closest('.inbound-row');
        const inboundId = inboundRow?.dataset.id || target.closest('.clients-sub-table-wrapper')?.parentElement.parentElement.previousElementSibling.dataset.id;
        
        const clientRow = target.closest('.client-row');
        const clientId = clientRow?.dataset.id;

        const getClientData = (id) => {
            const allClients = Array.from(clientDataCache.values()).flat();
            return allClients.find(c => c.id == id);
        }

        switch (action) {
            case 'expand':
                const clientsRow = document.getElementById(`clients-row-${inboundId}`);
                const isOpening = !clientsRow.classList.contains('active');
                
                if (statsInterval) clearInterval(statsInterval);

                document.querySelectorAll('.clients-row.active').forEach(row => row.classList.remove('active'));
                document.querySelectorAll('.expand-btn').forEach(btn => btn.textContent = '+');

                if (isOpening) {
                    clientsRow.classList.add('active');
                    target.textContent = '−';
                    clientsRow.querySelector('.clients-container').innerHTML = '<div class="loader">Loading...</div>';
                    await updateStats(inboundId); 
                    statsInterval = setInterval(() => updateStats(inboundId), 5000);
                }
                break;
            
            case 'show-qr': {
                const client = getClientData(clientId);
                if (!client) return;
            
                const qrSubContainer = document.getElementById('qr-sub-container');
                const qrClientContainer = document.getElementById('qr-client-container');
                const subLinkText = document.getElementById('sub-link-text');
                const copySubLinkBtn = document.getElementById('copy-sub-link-btn');
                const qrClientRemark = document.getElementById('qr-client-remark');
            
                const subUrl = `${window.location.origin}/sub/${encodeURIComponent(client.sub_remark)}`;
                generateQrCode(qrSubContainer, subUrl);
                subLinkText.value = subUrl;
                
                const newCopyBtn = copySubLinkBtn.cloneNode(true);
                copySubLinkBtn.parentNode.replaceChild(newCopyBtn, copySubLinkBtn);
                newCopyBtn.addEventListener('click', () => {
                    navigator.clipboard.writeText(subUrl).then(() => alert('Subscription link copied!'));
                });
            
                qrClientRemark.textContent = `Client: ${client.remark}`;
                qrClientContainer.dataset.linkDomain = client.config_link_domain || '';
                qrClientContainer.dataset.linkIp = client.config_link_ip || '';
                
                const defaultLink = client.config_link_domain || client.config_link_ip;
                generateQrCode(qrClientContainer, defaultLink);
                
                qrUseIpToggle.checked = !client.config_link_domain;
                
                qrModal.show();
                break;
            }

            case 'toggle-client': {
                const client = getClientData(clientId);
                if (!client) return;
                const newStatus = target.checked;
                try {
                    await apiCall(`/api/v1/clients/${client.id}`, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ enabled: newStatus })
                    });
                    const allClients = Array.from(clientDataCache.values()).flat();
                    allClients.forEach(c => {
                        if (c.sub_remark === client.sub_remark) c.enabled = newStatus;
                    });
                    renderClients(inboundId, clientDataCache.get(inboundId));
                } catch(e) {
                    target.checked = !newStatus;
                }
                break;
            }

            case 'delete-inbound': {
                if (confirm(`Delete inbound #${inboundId}?`)) {
                    await apiCall(`/api/v1/inbounds/${inboundId}`, { method: 'DELETE' });
                    if (statsInterval) clearInterval(statsInterval);
                    main();
                }
                break;
            }
            case 'add-client': {
                document.getElementById('client-inbound-id').value = inboundId;
                clientModal.show();
                break;
            }
            case 'delete-client': {
                 if (confirm(`Delete client #${clientId}?`)) {
                    await apiCall(`/api/v1/clients/${clientId}`, { method: 'DELETE' });
                    await updateStats(inboundId);
                    await main(true);
                }
                break;
            }
            case 'copy-link': {
                const client = getClientData(clientId);
                if (!client) return;
                const link = client.config_link_domain || client.config_link_ip;
                navigator.clipboard.writeText(link).then(() => alert('Config link copied!'));
                break;
            }
            case 'edit-client': {
                const client = getClientData(clientId);
                if (!client) return;
                document.getElementById('edit-client-id').value = client.id;
                document.getElementById('edit-client-enabled').checked = client.enabled;
                document.getElementById('edit-client-total-mb').value = client.total_gb * 1024;
                document.getElementById('edit-client-expiry-days').value = '';
                document.getElementById('edit-client-reset-traffic').checked = false;
                editModal.show();
                break;
            }
            case 'toggle-inbound': {
                const newStatus = target.checked;
                try {
                    await apiCall(`/api/v1/inbounds/${inboundId}`, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ enabled: newStatus })
                    });
                } catch(e) {
                    target.checked = !newStatus;
                }
                break;
            }
        }
    });

    qrUseIpToggle.addEventListener('change', (e) => {
        const useIp = e.target.checked;
        const qrClientContainer = document.getElementById('qr-client-container');
        const linkDomain = qrClientContainer.dataset.linkDomain;
        const linkIp = qrClientContainer.dataset.linkIp;
        generateQrCode(qrClientContainer, useIp ? linkIp : (linkDomain || linkIp));
    });

    // --- FORM SUBMISSIONS ---
    addInboundForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const network = document.getElementById('inbound-network').value;
        let stream_settings = { network: network, security: 'none' };
        if (network === 'ws') stream_settings.wsSettings = { path: '/' };
        if (network === 'grpc') stream_settings.grpcSettings = { serviceName: 'grpc-service' };

        const data = {
            remark: document.getElementById('inbound-remark').value,
            port: parseInt(document.getElementById('inbound-port').value),
            protocol: document.getElementById('inbound-protocol').value,
            stream_settings: stream_settings,
        };
        try {
            await apiCall('/api/v1/inbounds', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
            inboundModal.hide();
            addInboundForm.reset();
            main();
        } catch (error) { /* apiCall already alerts */ }
    });

    addClientForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const inboundId = document.getElementById('client-inbound-id').value;
        const data = { 
            remark: document.getElementById('client-remark').value,
            subscription_remark: document.getElementById('client-subscription').value,
            total_mb: parseInt(document.getElementById('client-total-mb').value) || 0,
            expiry_days: parseInt(document.getElementById('client-expiry-days').value) || 0
        };

        try {
            await apiCall(`/api/v1/inbounds/${inboundId}/clients`, { 
                method: 'POST', 
                headers: {'Content-Type': 'application/json'}, 
                body: JSON.stringify(data) 
            });
            clientModal.hide();
            addClientForm.reset();
            const activeRow = document.querySelector('.clients-row.active');
            if (activeRow) {
                const openInboundId = activeRow.id.replace('clients-row-', '');
                await updateStats(openInboundId);
            }
            main(true);
        } catch (error) { /* apiCall already alerts */ }
    });
    
    editClientForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const clientId = document.getElementById('edit-client-id').value;
        const days = parseInt(document.getElementById('edit-client-expiry-days').value);
        
        let expiry_time = null;
        if (!isNaN(days) && days >= 0) {
            expiry_time = days > 0 ? Math.floor(Date.now() / 1000) + (days * 24 * 60 * 60) : 0;
        }

        const data = {
            enabled: document.getElementById('edit-client-enabled').checked,
            total_mb: parseInt(document.getElementById('edit-client-total-mb').value) || 0,
            expiry_time: expiry_time,
            reset_traffic: document.getElementById('edit-client-reset-traffic').checked
        };
        
        try {
            await apiCall(`/api/v1/clients/${clientId}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
            editModal.hide();
            const activeRow = document.querySelector('.clients-row.active');
            if (activeRow) {
                const openInboundId = activeRow.id.replace('clients-row-', '');
                await updateStats(openInboundId);
            }
        } catch(error) { /* apiCall already alerts */ }
    });

    // --- MAIN EXECUTION ---
    const main = async (keepExpanded = false) => {
        let expandedId = null;
        if (keepExpanded) {
            const activeRow = document.querySelector('.clients-row.active');
            if (activeRow) expandedId = activeRow.id.replace('clients-row-', '');
        }
        try {
            const inbounds = await apiCall('/api/v1/inbounds');
            renderInbounds(inbounds);
            if (expandedId) {
                const expandBtn = document.querySelector(`.inbound-row[data-id='${expandedId}'] .expand-btn`);
                if (expandBtn) expandBtn.click();
            }
        } catch (error) {
            inboundsTbody.innerHTML = `<tr><td colspan="8" class="text-center">Error: ${error.message}</td></tr>`;
        }
    };
    main();
});