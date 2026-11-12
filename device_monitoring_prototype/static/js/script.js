/* Database-backed interactions for DevMonitor. */

const ITEMS_PER_PAGE = 10;
let devices = [];
let users = [];
let selectedDeviceId = null;
let selectedUserId = null;
let devicePage = 1;
let userPage = 1;
let deviceDetailsRequestId = 0;
let deviceSearch = '';
let userSearch = '';
let deviceSort = 'name-asc';
let userSort = 'name-asc';
const deviceAddresses = new Map();
const deviceAddressRequests = new Map();

function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

async function api(url, options = {}) {
    const headers = { 'X-CSRF-Token': csrfToken(), ...(options.headers || {}) };
    if (options.body) headers['Content-Type'] = 'application/json';
    const response = await fetch(url, { credentials: 'same-origin', ...options, headers });
    if (response.status === 401) {
        window.location.assign('/');
        throw new Error('Your session has expired.');
    }
    if (response.status === 204) return null;
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
    return result;
}

function escapeHTML(value) {
    const element = document.createElement('span');
    element.textContent = value == null ? '' : String(value);
    return element.innerHTML;
}

function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-bg-${type} border-0`;
    toast.setAttribute('role', 'status');
    toast.innerHTML = `<div class="d-flex"><div class="toast-body">${escapeHTML(message)}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto"
                data-bs-dismiss="toast"></button></div>`;
    container.appendChild(toast);
    const instance = new bootstrap.Toast(toast, { delay: 3500 });
    toast.addEventListener('hidden.bs.toast', () => toast.remove());
    instance.show();
}

function initSidebar() {
    const toggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    if (!toggle || !sidebar || !overlay) return;
    const close = () => {
        sidebar.classList.remove('show');
        overlay.classList.remove('show');
    };
    toggle.addEventListener('click', () => {
        sidebar.classList.toggle('show');
        overlay.classList.toggle('show');
    });
    overlay.addEventListener('click', close);
}

function getCurrentPage() {
    const path = window.location.pathname;
    if (path.includes('dashboard')) return 'dashboard';
    if (path.includes('devices')) return 'devices';
    if (path.includes('admin')) return 'admin';
    return 'login';
}

function renderPagination(containerId, total, current, onPage) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const pages = Math.ceil(total / ITEMS_PER_PAGE);
    if (pages <= 1) {
        container.innerHTML = '';
        return;
    }
    container.innerHTML = Array.from({ length: pages }, (_, index) => {
        const page = index + 1;
        return `<li class="page-item ${page === current ? 'active' : ''}">
            <button class="page-link" data-page="${page}">${page}</button></li>`;
    }).join('');
    container.querySelectorAll('[data-page]').forEach(button => {
        button.addEventListener('click', () => onPage(Number(button.dataset.page)));
    });
}

function sortRows(rows, key, nameKey, statusKey = 'status') {
    return [...rows].sort((a, b) => {
        if (key === 'name-desc') return b[nameKey].localeCompare(a[nameKey]);
        if (key === 'status-asc') return a[statusKey].localeCompare(b[statusKey]);
        if (key === 'status-desc') return b[statusKey].localeCompare(a[statusKey]);
        if (key === 'role-asc') return a.role.localeCompare(b.role);
        if (key === 'date-desc') return b.registered.localeCompare(a.registered);
        if (key === 'date-asc') return a.registered.localeCompare(b.registered);
        if (key === 'type-asc') return a.type.localeCompare(b.type);
        return a[nameKey].localeCompare(b[nameKey]);
    });
}

async function refreshDevices() {
    devices = await api('/api/devices');
    deviceAddresses.clear();
    renderDevicesCards();
}

function renderDevicesCards() {
    const grid = document.getElementById('devicesCardGrid');
    if (!grid) return;
    let rows = devices.filter(device => device.name.toLowerCase().includes(deviceSearch));
    rows = sortRows(rows, deviceSort, 'name');
    const start = (devicePage - 1) * ITEMS_PER_PAGE;
    const pageRows = rows.slice(start, start + ITEMS_PER_PAGE);
    grid.innerHTML = pageRows.length ? pageRows.map(device => `
        <article class="device-card">
            <div class="device-card-header">
                <div class="device-card-icon" aria-hidden="true"><i class="bi bi-laptop"></i></div>
                <span class="${device.status === 'Online' ? 'badge-online' : 'badge-offline'}">
                    ${escapeHTML(device.status)}
                </span>
            </div>
            <h3 class="device-card-title">${escapeHTML(device.name)}</h3>
            <p class="device-card-subtitle">${escapeHTML(device.type)}</p>
            <div class="device-card-details">
                <div class="device-card-detail">
                    <span class="device-card-label">IP Address</span>
                    <span class="device-card-value" data-device-address="${device.id}">
                        ${escapeHTML(deviceAddresses.get(device.id) || 'Loading...')}
                    </span>
                </div>
                <div class="device-card-detail">
                    <span class="device-card-label">Operating System</span>
                    <span class="device-card-value">${escapeHTML(device.os || 'Not reported')}</span>
                </div>
                <div class="device-card-detail">
                    <span class="device-card-label">Processor</span>
                    <span class="device-card-value">${escapeHTML(device.cpu || 'Not reported')}</span>
                </div>
                <div class="device-card-detail">
                    <span class="device-card-label">RAM</span>
                    <span class="device-card-value">${escapeHTML(device.ram || 'Not reported')}</span>
                </div>
                <div class="device-card-detail">
                    <span class="device-card-label">Storage</span>
                    <span class="device-card-value">${escapeHTML(device.storage || 'Not reported')}</span>
                </div>
                <div class="device-card-detail">
                    <span class="device-card-label">Last Updated</span>
                    <span class="device-card-value">
                        ${escapeHTML(device.lastUpdated ? new Date(device.lastUpdated).toLocaleDateString() : 'Not available')}
                    </span>
                </div>
            </div>
            <div class="device-card-actions">
                <button class="btn btn-sm btn-outline-info" title="View" aria-label="View device"
                    onclick="openDeviceModal('view', ${device.id})"><i class="bi bi-eye"></i></button>
                <button class="btn btn-sm btn-outline-primary" title="Edit" aria-label="Edit device"
                    onclick="openDeviceModal('edit', ${device.id})"><i class="bi bi-pencil"></i></button>
                <button class="btn btn-sm btn-outline-success" title="Record diagnostic entry"
                    aria-label="Record diagnostic entry"
                    onclick="scanDevice(${device.id})"><i class="bi bi-search"></i></button>
                <button class="btn btn-sm btn-outline-danger" title="Archive" aria-label="Archive device"
                    onclick="confirmDeleteDevice(${device.id})"><i class="bi bi-archive"></i></button>
            </div>
        </article>`).join('') : '<div class="device-card-empty">No devices found.</div>';
    renderPagination('devicesPagination', rows.length, devicePage, page => {
        devicePage = page;
        renderDevicesCards();
    });

    pageRows.forEach(device => loadDeviceAddress(device));
}

function loadDeviceAddress(device) {
    if (deviceAddresses.has(device.id) || deviceAddressRequests.has(device.id)) return;
    const request = api(`/api/devices/${device.id}/history`)
        .then(history => {
            const latestAddress = history.network?.find(record => record.ip_address)?.ip_address;
            deviceAddresses.set(device.id, latestAddress || 'Not reported');
        })
        .catch(error => {
            deviceAddresses.set(device.id, 'Unavailable');
            showToast(`Could not load the IP address for ${device.name}: ${error.message}`, 'danger');
        })
        .finally(() => {
            deviceAddressRequests.delete(device.id);
            renderDevicesCards();
        });
    deviceAddressRequests.set(device.id, request);
}

function initDevicesPage() {
    refreshDevices().catch(error => showToast(error.message, 'danger'));
    document.getElementById('deviceSearchInput')?.addEventListener('input', event => {
        deviceSearch = event.target.value.trim().toLowerCase();
        devicePage = 1;
        renderDevicesCards();
    });
    document.getElementById('deviceSortSelect')?.addEventListener('change', event => {
        deviceSort = event.target.value;
        renderDevicesCards();
    });
}

async function openDeviceModal(mode, deviceId) {
    const device = devices.find(item => item.id === deviceId);
    const requestId = ++deviceDetailsRequestId;
    selectedDeviceId = deviceId || null;
    const form = document.getElementById('deviceForm');
    form.reset();
    const detailsView = document.getElementById('deviceDetailsView');
    detailsView.classList.toggle('d-none', mode !== 'view');
    detailsView.innerHTML = mode === 'view'
        ? '<div class="device-information-empty">Loading device information...</div>'
        : '';
    form.classList.toggle('d-none', mode === 'view');
    document.getElementById('deviceFormMode').value = mode;
    document.getElementById('deviceFormId').value = deviceId || '';
    document.getElementById('deviceFormOwner').value =
        document.getElementById('currentUserDisplay')?.textContent || '';
    document.getElementById('deviceModalTitle').textContent =
        mode === 'add' ? 'Register Device' : mode === 'view' ? 'Device Details' : 'Edit Device';
    if (device) {
        document.getElementById('deviceFormName').value = device.name;
        document.getElementById('deviceFormHostname').value = device.hostname;
        document.getElementById('deviceFormType').value = device.type;
        document.getElementById('deviceFormOS').value = device.os;
        document.getElementById('deviceFormCPU').value = device.cpu;
        document.getElementById('deviceFormRAM').value = device.ram;
        document.getElementById('deviceFormStorage').value = device.storage;
        document.getElementById('deviceFormOwner').value = device.owner;
        document.getElementById('deviceFormStatus').value = device.status.toLowerCase();
    }
    const readOnly = mode === 'view';
    ['deviceFormName', 'deviceFormHostname', 'deviceFormType', 'deviceFormOS',
        'deviceFormStatus', 'deviceFormOwner'].forEach(id => {
        document.getElementById(id).disabled = readOnly || id === 'deviceFormOwner';
    });
    document.getElementById('saveDeviceBtn').classList.toggle('d-none', readOnly);
    document.getElementById('deviceModalFooter').querySelector('.btn-secondary').textContent =
        readOnly ? 'Close' : 'Cancel';
    const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('deviceModal'));
    modal.show();
    if (mode === 'view') {
        try {
            const details = await api(`/api/devices/${deviceId}`);
            if (requestId !== deviceDetailsRequestId || selectedDeviceId !== deviceId) return;
            detailsView.innerHTML = renderDeviceDetails(details);
        } catch (error) {
            if (requestId !== deviceDetailsRequestId) return;
            detailsView.innerHTML = `<div class="alert alert-danger mb-0" role="alert">
                ${escapeHTML(error.message)}
            </div>`;
        }
    }
}

function renderDeviceDetails(device) {
    const value = item => item == null || item === '' ? 'Not available' : String(item);
    const card = (label, item) => `
        <div class="device-information-card">
            <span class="device-information-label">${escapeHTML(label)}</span>
            <span class="device-information-value">${escapeHTML(value(item))}</span>
        </div>`;
    const section = (title, items) => `
        <section class="device-information-section">
            <h6 class="device-information-heading">${escapeHTML(title)}</h6>
            <div class="device-information-grid">${items.map(([label, item]) => card(label, item)).join('')}</div>
        </section>`;
    const owner = device.owner || {};
    const registrant = device.registered_by || {};
    const specification = device.specification || {};
    const sections = [
        section('Device', [
            ['Device ID', device.id], ['Asset Tag', device.asset_tag],
            ['Device Name', device.device_name], ['Hostname', device.hostname],
            ['Type', device.device_type], ['Status', device.status],
            ['Serial Number', device.serial_number], ['Manufacturer', device.manufacturer],
            ['Model', device.model], ['Operating System', device.operating_system],
            ['OS Version', device.operating_system_version],
        ]),
        section('Ownership and Dates', [
            ['Owner', owner.full_name], ['Owner Username', owner.username],
            ['Owner Email', owner.email], ['Registered By', registrant.full_name],
            ['Registered By Username', registrant.username],
            ['Registered At', device.registered_at], ['Updated At', device.updated_at],
            ['Last Seen At', device.last_seen_at],
        ]),
        section('Hardware Specification', [
            ['CPU', specification.cpu_model], ['CPU Cores', specification.cpu_cores],
            ['CPU Threads', specification.cpu_threads], ['Memory (bytes)', specification.memory_bytes],
            ['Storage (bytes)', specification.storage_bytes], ['GPU', specification.gpu_model],
            ['BIOS Version', specification.bios_version],
            ['Motherboard', specification.motherboard_model],
            ['Specification OS Version', specification.operating_system_version],
            ['Collected At', specification.collected_at],
        ]),
        section('Network Records', (device.network_records || []).flatMap(record => [
            ['IP Address', record.ip_address], ['Subnet Mask', record.subnet_mask],
            ['Default Gateway', record.default_gateway], ['DNS Server', record.dns_server],
            ['Connectivity', record.connectivity_status], ['Recorded At', record.recorded_at],
        ])),
        section('Network Interfaces', (device.network_interfaces || []).flatMap(networkInterface => [
            ['Interface', networkInterface.interface_name], ['MAC Address', networkInterface.mac_address],
            ['Interface Type', networkInterface.interface_type],
            ['Primary', networkInterface.is_primary ? 'Yes' : 'No'],
            ...networkInterface.observations.flatMap(observation => [
                ['Observed IP Address', observation.ip_address],
                ['Subnet Prefix', observation.subnet_prefix], ['Gateway', observation.gateway],
                ['DNS Servers', JSON.stringify(observation.dns_servers)],
                ['SSID', observation.ssid], ['Connection Type', observation.connection_type],
                ['Observed At', observation.observed_at],
            ]),
        ])),
        section('Diagnostic History', (device.diagnostics || []).flatMap(run => [
            ['Diagnostic Status', run.status], ['Summary', run.summary],
            ['Detected Problem', run.detected_problem], ['Recommendation', run.recommendation],
            ['Started At', run.started_at], ['Finished At', run.finished_at],
            ...run.checks.flatMap(check => [
                ['Check', check.check_name], ['Category', check.category],
                ['Check Status', check.status], ['Result', check.result_summary],
                ['Details', JSON.stringify(check.details)], ['Measured At', check.measured_at],
            ]),
        ])),
        section('Monitoring Metrics', (device.metrics || []).flatMap(metric => [
            ['CPU Usage (%)', metric.cpu_percent], ['Memory Usage (%)', metric.memory_percent],
            ['Storage Usage (%)', metric.storage_percent],
            ['Memory Used (bytes)', metric.memory_used_bytes],
            ['Storage Used (bytes)', metric.storage_used_bytes],
            ['Network Received (bytes)', metric.network_rx_bytes],
            ['Network Sent (bytes)', metric.network_tx_bytes],
            ['Collected At', metric.collected_at],
        ])),
        section('System Logs', (device.logs || []).flatMap(log => [
            ['Event', log.event], ['Timestamp', log.timestamp],
        ])),
    ];
    return sections.map((content, index) => {
        const hasData = [
            device.network_records, device.network_interfaces, device.diagnostics,
            device.metrics, device.logs,
        ][index - 3];
        if (index >= 3 && (!hasData || !hasData.length)) {
            const headings = [
                'Network Records', 'Network Interfaces', 'Diagnostic History',
                'Monitoring Metrics', 'System Logs',
            ];
            return section(headings[index - 3], [['Information', 'No records available']]);
        }
        return content;
    }).join('');
}

async function saveDevice() {
    const mode = document.getElementById('deviceFormMode').value;
    const data = {
        name: document.getElementById('deviceFormName').value.trim(),
        hostname: document.getElementById('deviceFormHostname').value.trim(),
        type: document.getElementById('deviceFormType').value,
        os: document.getElementById('deviceFormOS').value,
        status: document.getElementById('deviceFormStatus').value
    };
    if (!data.name || !data.type || !data.os) {
        showToast('Device name, type, and operating system are required.', 'danger');
        return;
    }
    try {
        await api(mode === 'add' ? '/api/devices' : `/api/devices/${selectedDeviceId}`, {
            method: mode === 'add' ? 'POST' : 'PATCH',
            body: JSON.stringify(data)
        });
        bootstrap.Modal.getInstance(document.getElementById('deviceModal')).hide();
        await refreshDevices();
        showToast(mode === 'add' ? 'Device registered.' : 'Device updated.');
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

function confirmDeleteDevice(deviceId) {
    selectedDeviceId = deviceId;
    const device = devices.find(item => item.id === deviceId);
    document.getElementById('deleteDeviceName').textContent = device?.name || '';
    bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteDeviceModal')).show();
}

async function archiveSelectedDevice() {
    try {
        await api(`/api/devices/${selectedDeviceId}`, { method: 'DELETE' });
        bootstrap.Modal.getInstance(document.getElementById('deleteDeviceModal')).hide();
        await refreshDevices();
        showToast('Device archived; its history was retained.');
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

async function scanDevice(deviceId) {
    const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('scanModal'));
    document.getElementById('scanProgress').classList.remove('d-none');
    document.getElementById('scanResults').classList.add('d-none');
    modal.show();
    try {
        const result = await api(`/api/devices/${deviceId}/diagnostics`, { method: 'POST' });
        document.getElementById('scanProgress').classList.add('d-none');
        document.getElementById('scanResultsBody').innerHTML = `
            <tr><th>Result</th><td>${escapeHTML(result.result)}</td></tr>
            <tr><th>Detected Problem</th><td>${escapeHTML(result.detected_problem || 'Not assessed')}</td></tr>
            <tr><th>Recommendation</th><td>${escapeHTML(result.recommendation)}</td></tr>
            <tr><th>Recorded</th><td>${escapeHTML(new Date(result.scanned_at).toLocaleString())}</td></tr>`;
        document.getElementById('scanResults').classList.remove('d-none');
    } catch (error) {
        modal.hide();
        showToast(error.message, 'danger');
    }
}

async function refreshUsers() {
    users = await api('/api/users');
    renderUsersTable();
}

function renderUsersTable() {
    const body = document.getElementById('usersTableBody');
    if (!body) return;
    let rows = users.filter(user =>
        `${user.fullName} ${user.username} ${user.email}`.toLowerCase().includes(userSearch)
    );
    rows = sortRows(rows, userSort, 'fullName');
    const start = (userPage - 1) * ITEMS_PER_PAGE;
    const pageRows = rows.slice(start, start + ITEMS_PER_PAGE);
    body.innerHTML = pageRows.length ? pageRows.map(user => `
        <tr>
            <td>${user.id}</td><td>${escapeHTML(user.fullName)}</td>
            <td>${escapeHTML(user.username)}</td><td>${escapeHTML(user.email)}</td>
            <td>${escapeHTML(user.role)}</td><td>${escapeHTML(user.status)}</td>
            <td class="text-center"><div class="action-btn-group justify-content-center">
                <button class="btn btn-sm btn-outline-primary" title="Edit"
                    onclick="openUserModal('edit', ${user.id})"><i class="bi bi-pencil"></i></button>
                <button class="btn btn-sm btn-outline-danger" title="Deactivate"
                    onclick="confirmDeleteUser(${user.id})"><i class="bi bi-person-x"></i></button>
            </div></td>
        </tr>`).join('') : '<tr><td colspan="7" class="text-center text-muted py-4">No users found.</td></tr>';
    renderPagination('usersPagination', rows.length, userPage, page => {
        userPage = page;
        renderUsersTable();
    });
}

function initAdminPage() {
    refreshUsers().catch(error => showToast(error.message, 'danger'));
    document.getElementById('userSearchInput')?.addEventListener('input', event => {
        userSearch = event.target.value.trim().toLowerCase();
        userPage = 1;
        renderUsersTable();
    });
    document.getElementById('userSortSelect')?.addEventListener('change', event => {
        userSort = event.target.value;
        renderUsersTable();
    });
    document.getElementById('confirmDeleteUserBtn')?.addEventListener('click', deactivateSelectedUser);
}

function openUserModal(mode, userId) {
    const user = users.find(item => item.id === userId);
    selectedUserId = userId || null;
    document.getElementById('userForm').reset();
    document.getElementById('userFormMode').value = mode;
    document.getElementById('userFormId').value = userId || '';
    document.getElementById('userModalTitle').textContent =
        mode === 'add' ? 'Add User' : 'Edit User';
    document.getElementById('userPasswordGroup').classList.toggle('d-none', mode !== 'add');
    document.getElementById('userFormUsername').disabled = mode !== 'add';
    if (user) {
        document.getElementById('userFormFullName').value = user.fullName;
        document.getElementById('userFormUsername').value = user.username;
        document.getElementById('userFormEmail').value = user.email;
        document.getElementById('userFormRole').value = user.role;
        document.getElementById('userFormStatus').value = user.status;
    }
    bootstrap.Modal.getOrCreateInstance(document.getElementById('userModal')).show();
}

async function saveUser() {
    const mode = document.getElementById('userFormMode').value;
    const data = {
        full_name: document.getElementById('userFormFullName').value.trim(),
        username: document.getElementById('userFormUsername').value.trim(),
        email: document.getElementById('userFormEmail').value.trim(),
        role: document.getElementById('userFormRole').value,
        status: document.getElementById('userFormStatus').value.toLowerCase()
    };
    if (mode === 'add') data.password = document.getElementById('userFormPassword').value;
    try {
        await api(mode === 'add' ? '/api/users' : `/api/users/${selectedUserId}`, {
            method: mode === 'add' ? 'POST' : 'PATCH',
            body: JSON.stringify(data)
        });
        bootstrap.Modal.getInstance(document.getElementById('userModal')).hide();
        await refreshUsers();
        showToast(mode === 'add' ? 'User account created.' : 'User account updated.');
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

function confirmDeleteUser(userId) {
    selectedUserId = userId;
    const user = users.find(item => item.id === userId);
    document.getElementById('deleteUserName').textContent = user?.fullName || user?.username || '';
    bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteUserModal')).show();
}

async function deactivateSelectedUser() {
    try {
        await api(`/api/users/${selectedUserId}`, { method: 'DELETE' });
        bootstrap.Modal.getInstance(document.getElementById('deleteUserModal')).hide();
        await refreshUsers();
        showToast('User deactivated; associated records were retained.');
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

async function initDashboard() {
    try {
        const result = await api('/api/dashboard');
        document.getElementById('totalDevices').textContent = result.total;
        document.getElementById('onlineDevices').textContent = result.online;
        document.getElementById('offlineDevices').textContent = result.offline;
        const latestUpdate = result.devices
            .map(device => device.lastUpdated)
            .filter(Boolean)
            .sort()
            .at(-1);
        document.getElementById('lastUpdate').textContent =
            latestUpdate ? new Date(latestUpdate).toLocaleString() : '--';
        const body = document.getElementById('dashboardDeviceTableBody');
        body.innerHTML = result.devices.length ? result.devices.map(device => `
            <tr><td class="fw-semibold">${escapeHTML(device.name)}</td>
                <td>${escapeHTML(device.owner)}</td><td>${escapeHTML(device.os)}</td>
                <td>${escapeHTML(device.cpu)}</td><td>${escapeHTML(device.ram)}</td>
                <td>${escapeHTML(device.status)}</td></tr>`).join('') :
            '<tr><td colspan="6" class="text-center text-muted py-4">No registered devices yet.</td></tr>';
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initSidebar();
    document.getElementById('confirmDeleteDeviceBtn')?.addEventListener('click', archiveSelectedDevice);
    const page = getCurrentPage();
    if (page === 'login') {
        const toggle = document.getElementById('togglePassword');
        const input = document.getElementById('passwordInput');
        toggle?.addEventListener('click', () => {
            const showPassword = input.type === 'password';
            input.type = showPassword ? 'text' : 'password';
            toggle.querySelector('i').className = showPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
        });
    }
    if (page === 'dashboard') initDashboard();
    if (page === 'devices') initDevicesPage();
    if (page === 'admin') initAdminPage();
});
