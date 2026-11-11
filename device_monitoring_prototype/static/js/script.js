/* DevMonitor — Centralized End-User Device Monitoring & Diagnostic System */

const ITEMS_PER_PAGE = 10;
let devices = [];
let users = [];
let selectedDeviceId = null;
let selectedUserId = null;
let devicePage = 1;
let userPage = 1;
let deviceSearch = '';
let userSearch = '';
let deviceSort = 'name-asc';
let userSort = 'name-asc';

let telemetryChartInstance = null;
let deviceChartInstance = null;
let eventSource = null;

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
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    container.appendChild(toast);
    const instance = new bootstrap.Toast(toast, { delay: 4000 });
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
        if (key === 'role-asc') return (a.role || '').localeCompare(b.role || '');
        if (key === 'date-desc') return (b.registered || '').localeCompare(a.registered || '');
        if (key === 'date-asc') return (a.registered || '').localeCompare(b.registered || '');
        if (key === 'type-asc') return (a.type || '').localeCompare(b.type || '');
        return a[nameKey].localeCompare(b[nameKey]);
    });
}

/* ==============================================================
   REAL-TIME NOTIFICATIONS & ALERTS
   ============================================================== */

async function initAlerts() {
    try {
        const alerts = await api('/api/alerts');
        renderAlerts(alerts);
    } catch {
        // Suppress on unauthenticated routes
    }
}

function renderAlerts(alerts) {
    const countBadge = document.getElementById('notificationCount');
    const container = document.getElementById('alertsContainer');
    if (!container || !countBadge) return;

    const unread = alerts.filter(a => !a.is_read);
    if (unread.length > 0) {
        countBadge.textContent = unread.length;
        countBadge.classList.remove('d-none');
    } else {
        countBadge.classList.add('d-none');
    }

    if (!alerts.length) {
        container.innerHTML = '<li class="text-center text-muted py-3 small">No active alerts.</li>';
        return;
    }

    container.innerHTML = alerts.slice(0, 8).map(a => `
        <li class="alert-item p-2 mb-1 rounded ${a.is_read ? 'opacity-50' : ''}" style="background: rgba(255, 255, 255, 0.04); font-size: 0.82rem;">
            <div class="d-flex justify-content-between align-items-start">
                <span class="fw-semibold text-${a.severity === 'critical' ? 'danger' : a.severity === 'warning' ? 'warning' : 'info'}">
                    <i class="bi bi-${a.severity === 'critical' ? 'exclamation-diamond-fill' : 'exclamation-triangle-fill'} me-1"></i>${escapeHTML(a.title)}
                </span>
                <small class="text-muted">${escapeHTML(new Date(a.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))}</small>
            </div>
            <div class="text-muted small mt-1">${escapeHTML(a.message)}</div>
        </li>
    `).join('');
}

async function clearAllAlerts() {
    try {
        await api('/api/alerts/clear-all', { method: 'POST' });
        const countBadge = document.getElementById('notificationCount');
        if (countBadge) countBadge.classList.add('d-none');
        const container = document.getElementById('alertsContainer');
        if (container) container.innerHTML = '<li class="text-center text-muted py-3 small">All alerts dismissed.</li>';
        showToast('All alerts dismissed.');
    } catch (err) {
        showToast(err.message, 'danger');
    }
}

/* ==============================================================
   SERVER-SENT EVENTS (SSE) STREAM
   ============================================================== */

function initEventStream() {
    if (eventSource) return;
    try {
        eventSource = new EventSource('/api/events');
        eventSource.onmessage = event => {
            try {
                const payload = JSON.parse(event.data);
                if (payload.event === 'fleet.updated') {
                    if (getCurrentPage() === 'dashboard') initDashboard();
                    if (getCurrentPage() === 'devices') refreshDevices();
                } else if (payload.event === 'device.metrics') {
                    handleIncomingTelemetry(payload.data);
                } else if (payload.event === 'alert.created') {
                    showToast(`${payload.data.title}: ${payload.data.message}`, payload.data.severity === 'critical' ? 'danger' : 'warning');
                    initAlerts();
                }
            } catch {
                // Ignore ping / format errors
            }
        };
        eventSource.onerror = () => {
            const badge = document.getElementById('sseLiveBadge');
            if (badge) {
                badge.className = 'badge bg-warning-subtle text-warning small';
                badge.innerHTML = '<i class="bi bi-arrow-repeat me-1"></i>Reconnecting...';
            }
        };
        eventSource.onopen = () => {
            const badge = document.getElementById('sseLiveBadge');
            if (badge) {
                badge.className = 'badge bg-success-subtle text-success small';
                badge.innerHTML = '<i class="bi bi-broadcast me-1"></i>Live Stream Active';
            }
        };
    } catch (err) {
        console.warn('SSE event stream unavailable:', err);
    }
}

function handleIncomingTelemetry(data) {
    if (getCurrentPage() === 'dashboard') {
        if (data.cpu != null) updateGauge('cpu', data.cpu, 80, 92);
        if (data.ram != null) updateGauge('ram', data.ram, 85, 95);
        if (data.storage != null) updateGauge('storage', data.storage, 90, 95);
        appendChartPoint(data.cpu, data.ram, data.storage);

        // Update row if present
        const row = document.querySelector(`tr[data-device-id="${data.device_id}"]`);
        if (row) {
            const statusCell = row.querySelector('.status-cell');
            if (statusCell) statusCell.innerHTML = '<span class="badge-online">Online</span>';
            const loadCell = row.querySelector('.load-cell');
            if (loadCell && data.cpu != null) loadCell.innerHTML = `<code>${data.cpu.toFixed(1)}%</code>`;
        }
    }
}

/* ==============================================================
   DASHBOARD RESOURCE GAUGES & CHARTS
   ============================================================== */

function updateGauge(type, percent, warnThresh, critThresh) {
    const val = Math.max(0, Math.min(100, Number(percent) || 0));
    const bar = document.getElementById(`${type}ProgressBar`);
    const badge = document.getElementById(`${type}Badge`);
    const txt = document.getElementById(`${type}ValueText`);

    if (!bar || !badge || !txt) return;

    bar.style.width = `${val}%`;
    txt.textContent = `${val.toFixed(1)}%`;
    badge.textContent = `${val.toFixed(0)}%`;

    bar.className = 'progress-bar ';
    badge.className = 'badge ';

    if (val >= critThresh) {
        bar.classList.add('bg-danger');
        badge.classList.add('bg-danger');
    } else if (val >= warnThresh) {
        bar.classList.add('bg-warning', 'text-dark');
        badge.classList.add('bg-warning', 'text-dark');
    } else {
        bar.classList.add(type === 'ram' ? 'bg-info' : type === 'storage' ? 'bg-primary' : 'bg-success');
        badge.classList.add(type === 'ram' ? 'bg-info' : type === 'storage' ? 'bg-primary' : 'bg-success');
    }
}

function initDashboardChart() {
    const canvas = document.getElementById('telemetryChart');
    if (!canvas || typeof Chart === 'undefined') return;

    const initialLabels = ['-25s', '-20s', '-15s', '-10s', '-5s', 'Now'];
    telemetryChartInstance = new Chart(canvas, {
        type: 'line',
        data: {
            labels: initialLabels,
            datasets: [
                {
                    label: 'Fleet CPU (%)',
                    data: [18, 24, 20, 26, 22, 25],
                    borderColor: '#60a5fa',
                    backgroundColor: 'rgba(96, 165, 250, 0.12)',
                    fill: true,
                    tension: 0.35,
                    borderWidth: 2,
                    pointRadius: 2,
                },
                {
                    label: 'Fleet RAM (%)',
                    data: [45, 46, 46, 47, 47, 48],
                    borderColor: '#34d399',
                    backgroundColor: 'transparent',
                    fill: false,
                    tension: 0.35,
                    borderWidth: 2,
                    pointRadius: 2,
                },
                {
                    label: 'Fleet Storage (%)',
                    data: [62, 62, 62, 62, 62, 62],
                    borderColor: '#f59e0b',
                    backgroundColor: 'transparent',
                    fill: false,
                    tension: 0.35,
                    borderWidth: 2,
                    pointRadius: 2,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 600 },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { color: '#94a3b8', font: { size: 11, family: 'system-ui' } },
                },
            },
            scales: {
                y: {
                    min: 0,
                    max: 100,
                    ticks: { color: '#94a3b8', callback: v => `${v}%` },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                },
                x: {
                    ticks: { color: '#94a3b8' },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                },
            },
        },
    });
}

function appendChartPoint(cpu, ram, storage) {
    if (!telemetryChartInstance) return;
    const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const labels = telemetryChartInstance.data.labels;
    if (labels.length >= 12) {
        labels.shift();
        telemetryChartInstance.data.datasets.forEach(ds => ds.data.shift());
    }
    labels.push(nowStr);
    if (cpu != null) telemetryChartInstance.data.datasets[0].data.push(cpu);
    if (ram != null) telemetryChartInstance.data.datasets[1].data.push(ram);
    if (storage != null) telemetryChartInstance.data.datasets[2].data.push(storage);
    telemetryChartInstance.update();
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

        if (result.metrics) {
            updateGauge('cpu', result.metrics.cpu, 80, 92);
            updateGauge('ram', result.metrics.ram, 85, 95);
            updateGauge('storage', result.metrics.storage, 90, 95);
        }

        const body = document.getElementById('dashboardDeviceTableBody');
        body.innerHTML = result.devices.length ? result.devices.map(device => `
            <tr data-device-id="${device.id}">
                <td class="fw-semibold">${escapeHTML(device.name)}</td>
                <td>${escapeHTML(device.owner)}</td>
                <td>${escapeHTML(device.os)}</td>
                <td>${escapeHTML(device.cpu)}</td>
                <td>${escapeHTML(device.ram)}</td>
                <td class="load-cell">${device.cpu_percent != null ? `<code>${device.cpu_percent.toFixed(1)}%</code>` : '<span class="text-muted">—</span>'}</td>
                <td class="status-cell"><span class="${device.status === 'Online' ? 'badge-online' : 'badge-offline'}">${escapeHTML(device.status)}</span></td>
            </tr>`).join('') :
            '<tr><td colspan="7" class="text-center text-muted py-4">No registered devices yet.</td></tr>';

        initDashboardChart();
        initEventStream();
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

/* ==============================================================
   DEVICE MANAGEMENT & REAL DIAGNOSTICS
   ============================================================== */

async function refreshDevices() {
    devices = await api('/api/devices');
    renderDevicesTable();
}

function renderDevicesTable() {
    const body = document.getElementById('devicesTableBody');
    if (!body) return;
    let rows = devices.filter(device => device.name.toLowerCase().includes(deviceSearch));
    rows = sortRows(rows, deviceSort, 'name');
    const start = (devicePage - 1) * ITEMS_PER_PAGE;
    const pageRows = rows.slice(start, start + ITEMS_PER_PAGE);
    body.innerHTML = pageRows.length ? pageRows.map(device => `
        <tr>
            <td class="fw-semibold">${escapeHTML(device.name)}</td>
            <td>${escapeHTML(device.type)}</td>
            <td>${escapeHTML(device.os)}</td>
            <td>${escapeHTML(device.cpu)}</td>
            <td>${escapeHTML(device.ram)}</td>
            <td>${escapeHTML(device.storage)}</td>
            <td><span class="${device.status === 'Online' ? 'badge-online' : 'badge-offline'}">
                ${escapeHTML(device.status)}</span></td>
            <td>${escapeHTML(device.lastUpdated ? new Date(device.lastUpdated).toLocaleDateString() : '')}</td>
            <td><div class="action-btn-group">
                <button class="btn btn-sm btn-outline-info" title="View details"
                    onclick="openDeviceModal('view', ${device.id})"><i class="bi bi-eye"></i></button>
                <button class="btn btn-sm btn-outline-primary" title="Edit device"
                    onclick="openDeviceModal('edit', ${device.id})"><i class="bi bi-pencil"></i></button>
                <button class="btn btn-sm btn-outline-warning" title="View history & metrics"
                    onclick="openHistoryModal(${device.id})"><i class="bi bi-clock-history"></i></button>
                <button class="btn btn-sm btn-outline-success" title="Run real diagnostic test"
                    onclick="scanDevice(${device.id})"><i class="bi bi-shield-check"></i></button>
                <button class="btn btn-sm btn-outline-danger" title="Archive"
                    onclick="confirmDeleteDevice(${device.id})"><i class="bi bi-archive"></i></button>
            </div></td>
        </tr>`).join('') : '<tr><td colspan="9" class="text-center text-muted py-4">No devices found.</td></tr>';
    renderPagination('devicesPagination', rows.length, devicePage, page => {
        devicePage = page;
        renderDevicesTable();
    });
}

function initDevicesPage() {
    refreshDevices().catch(error => showToast(error.message, 'danger'));
    document.getElementById('deviceSearchInput')?.addEventListener('input', event => {
        deviceSearch = event.target.value.trim().toLowerCase();
        devicePage = 1;
        renderDevicesTable();
    });
    document.getElementById('deviceSortSelect')?.addEventListener('change', event => {
        deviceSort = event.target.value;
        renderDevicesTable();
    });
    initEventStream();
}

function openDeviceModal(mode, deviceId) {
    const device = devices.find(item => item.id === deviceId);
    selectedDeviceId = deviceId || null;
    const form = document.getElementById('deviceForm');
    form.reset();
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
    bootstrap.Modal.getOrCreateInstance(document.getElementById('deviceModal')).show();
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
        showToast('Device archived; history was retained.');
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

async function scanDevice(deviceId) {
    const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('scanModal'));
    document.getElementById('scanProgress').classList.remove('d-none');
    document.getElementById('scanResults').classList.add('d-none');
    document.getElementById('scanProgressBar').style.width = '35%';
    modal.show();

    try {
        document.getElementById('scanProgressBar').style.width = '70%';
        const result = await api(`/api/devices/${deviceId}/diagnostics`, { method: 'POST' });
        document.getElementById('scanProgressBar').style.width = '100%';

        setTimeout(() => {
            document.getElementById('scanProgress').classList.add('d-none');
            document.getElementById('scanSummaryText').textContent = result.result;

            const tbody = document.getElementById('scanResultsBody');
            if (result.checks && result.checks.length) {
                tbody.innerHTML = result.checks.map(c => `
                    <tr>
                        <td class="fw-semibold">${escapeHTML(c.name)}</td>
                        <td><span class="badge ${c.status === 'passed' ? 'bg-success' : c.status === 'warning' ? 'bg-warning text-dark' : 'bg-danger'}">
                            ${escapeHTML(c.status.toUpperCase())}</span></td>
                        <td><small class="text-muted">${escapeHTML(c.summary)}</small></td>
                    </tr>
                `).join('') + `
                    <tr class="table-active">
                        <td colspan="3"><small><strong>Recommendation:</strong> ${escapeHTML(result.recommendation)}</small></td>
                    </tr>
                `;
            } else {
                tbody.innerHTML = `
                    <tr><th>Result</th><td>${escapeHTML(result.result)}</td></tr>
                    <tr><th>Detected Problem</th><td>${escapeHTML(result.detected_problem || 'Nominal')}</td></tr>
                    <tr><th>Recommendation</th><td>${escapeHTML(result.recommendation)}</td></tr>`;
            }

            document.getElementById('scanResults').classList.remove('d-none');
        }, 400);
    } catch (error) {
        modal.hide();
        showToast(error.message, 'danger');
    }
}

async function openHistoryModal(deviceId) {
    const device = devices.find(item => item.id === deviceId);
    document.getElementById('historyDeviceName').textContent = device?.name || '';
    const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('historyModal'));
    modal.show();

    try {
        const history = await api(`/api/devices/${deviceId}/history`);

        const diagBody = document.getElementById('historyDiagnosticsBody');
        diagBody.innerHTML = history.diagnostics.length ? history.diagnostics.map(run => `
            <tr>
                <td><small>${escapeHTML(new Date(run.scanned_at).toLocaleString())}</small></td>
                <td><span class="badge ${run.problem && run.problem !== 'None. All system health indicators are nominal.' ? 'bg-warning text-dark' : 'bg-success'}">${escapeHTML(run.status)}</span></td>
                <td><small>${escapeHTML(run.problem || 'Nominal')}</small></td>
                <td><small class="text-muted">${escapeHTML(run.recommendation || '—')}</small></td>
            </tr>
        `).join('') : '<tr><td colspan="4" class="text-center text-muted py-3">No diagnostic runs recorded yet.</td></tr>';

        const netBody = document.getElementById('historyNetworkBody');
        netBody.innerHTML = history.network.length ? history.network.map(rec => `
            <tr>
                <td><small>${escapeHTML(new Date(rec.recorded_at).toLocaleString())}</small></td>
                <td><code>${escapeHTML(rec.ip_address || '—')}</code></td>
                <td><small>${escapeHTML(rec.subnet_mask || '—')}</small></td>
                <td><small>${escapeHTML(rec.default_gateway || '—')}</small></td>
                <td><small>${escapeHTML(rec.dns_server || '—')}</small></td>
                <td><span class="${rec.connectivity_status === 'connected' ? 'badge-online' : 'badge-offline'}">${escapeHTML(rec.connectivity_status)}</span></td>
            </tr>
        `).join('') : '<tr><td colspan="6" class="text-center text-muted py-3">No network snapshots recorded.</td></tr>';

        // Load historical telemetry metrics for chart tab
        loadDeviceMetricsChart(deviceId);
    } catch (err) {
        showToast(err.message, 'danger');
    }
}

async function loadDeviceMetricsChart(deviceId) {
    const canvas = document.getElementById('deviceMetricChart');
    if (!canvas || typeof Chart === 'undefined') return;

    try {
        const samples = await api(`/api/devices/${deviceId}/metrics/history`);
        const labels = samples.map(s => s.time);
        const cpuData = samples.map(s => s.cpu);
        const ramData = samples.map(s => s.ram);
        const diskData = samples.map(s => s.storage);

        if (deviceChartInstance) deviceChartInstance.destroy();
        deviceChartInstance = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels.length ? labels : ['No data'],
                datasets: [
                    { label: 'CPU %', data: cpuData.length ? cpuData : [0], borderColor: '#60a5fa', tension: 0.3, fill: false },
                    { label: 'RAM %', data: ramData.length ? ramData : [0], borderColor: '#34d399', tension: 0.3, fill: false },
                    { label: 'Disk %', data: diskData.length ? diskData : [0], borderColor: '#fbbf24', tension: 0.3, fill: false },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { min: 0, max: 100, ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255, 255, 255, 0.05)' } },
                    x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255, 255, 255, 0.05)' } },
                },
                plugins: {
                    legend: { labels: { color: '#94a3b8' } },
                },
            },
        });
    } catch (err) {
        console.error('Failed to load device metrics chart:', err);
    }
}

/* ==============================================================
   ADMIN PANEL: USER MANAGEMENT & AUDIT LOGS
   ============================================================== */

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
            <td>${escapeHTML(user.role)}</td>
            <td><span class="badge ${user.status.toLowerCase() === 'active' ? 'bg-success' : user.status.toLowerCase() === 'locked' ? 'bg-danger' : 'bg-secondary'}">${escapeHTML(user.status)}</span></td>
            <td class="text-center"><div class="action-btn-group justify-content-center">
                <button class="btn btn-sm btn-outline-primary" title="Edit account"
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

async function loadAuditLogs() {
    const tbody = document.getElementById('auditLogsTableBody');
    if (!tbody) return;
    try {
        const logs = await api('/api/audit-logs');
        tbody.innerHTML = logs.length ? logs.map(log => `
            <tr>
                <td><small>${escapeHTML(new Date(log.timestamp).toLocaleString())}</small></td>
                <td><span class="fw-semibold">${escapeHTML(log.actor)}</span></td>
                <td><code>${escapeHTML(log.event)}</code></td>
                <td><small>${escapeHTML(log.entity)} #${escapeHTML(log.entity_id)}</small></td>
                <td><small class="text-muted">${escapeHTML(JSON.stringify(log.details))}</small></td>
            </tr>
        `).join('') : '<tr><td colspan="5" class="text-center text-muted py-3">No audit logs recorded yet.</td></tr>';
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-3">${escapeHTML(err.message)}</td></tr>`;
    }
}

function initAdminPage() {
    refreshUsers().catch(error => showToast(error.message, 'danger'));
    loadAuditLogs().catch(error => showToast(error.message, 'danger'));

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
        await loadAuditLogs();
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
        await loadAuditLogs();
        showToast('User deactivated; associated records were retained.');
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

/* ==============================================================
   LIFECYCLE INITIALIZATION
   ============================================================== */

document.addEventListener('DOMContentLoaded', () => {
    initSidebar();
    initAlerts();

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
