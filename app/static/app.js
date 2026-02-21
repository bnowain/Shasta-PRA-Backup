/* Shared utilities for all pages */

async function apiFetch(path) {
    const resp = await fetch(path);
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    return resp.json();
}

function escapeHtml(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return '—';
    return dateStr;
}

function statusPill(state) {
    if (!state) return '<span class="pill pill-gray">Unknown</span>';
    const s = state.toLowerCase();
    if (s.includes('closed') || s.includes('completed')) return `<span class="pill pill-green">${escapeHtml(state)}</span>`;
    if (s.includes('overdue')) return `<span class="pill pill-red">${escapeHtml(state)}</span>`;
    if (s.includes('in progress') || s.includes('processing')) return `<span class="pill pill-yellow">${escapeHtml(state)}</span>`;
    if (s.includes('submitted') || s.includes('open')) return `<span class="pill pill-blue">${escapeHtml(state)}</span>`;
    return `<span class="pill pill-gray">${escapeHtml(state)}</span>`;
}

function truncate(text, len = 120) {
    if (!text) return '';
    return text.length > len ? text.slice(0, len) + '...' : text;
}

// Highlight current nav link + inject Pull button
document.addEventListener('DOMContentLoaded', () => {
    const path = location.pathname;
    document.querySelectorAll('.topbar nav a').forEach(a => {
        const href = a.getAttribute('href');
        if (href === '/' && path === '/') a.classList.add('active');
        else if (href !== '/' && path.startsWith(href)) a.classList.add('active');
    });
    injectPullButton();
});

// ── Pull / Scrape ───────────────────────────────────────────────────────────

function injectPullButton() {
    const topbar = document.querySelector('.topbar');
    if (!topbar) return;
    const btn = document.createElement('button');
    btn.className = 'pull-btn';
    btn.textContent = 'Pull';
    btn.onclick = startScrape;
    topbar.appendChild(btn);
}

function startScrape() {
    const btn = document.querySelector('.pull-btn');
    if (btn) btn.disabled = true;

    // Build overlay
    const overlay = document.createElement('div');
    overlay.className = 'scrape-overlay';
    overlay.innerHTML = `
        <div class="scrape-card">
            <h3>Pulling New Records</h3>
            <div class="progress-bar"><div class="progress-fill" id="scrape-fill"></div></div>
            <div class="scrape-status" id="scrape-status">Connecting...</div>
            <div class="scrape-log" id="scrape-log"></div>
            <div class="scrape-actions" id="scrape-actions"></div>
        </div>`;
    document.body.appendChild(overlay);

    const fill = document.getElementById('scrape-fill');
    const status = document.getElementById('scrape-status');
    const log = document.getElementById('scrape-log');
    const actions = document.getElementById('scrape-actions');

    function addLog(msg) {
        const d = document.createElement('div');
        d.textContent = msg;
        log.appendChild(d);
        log.scrollTop = log.scrollHeight;
    }

    const es = new EventSource('/api/scrape/run');

    es.onmessage = (e) => {
        const data = JSON.parse(e.data);
        const pct = data.progress;

        if (pct >= 0) {
            fill.style.width = pct + '%';
        }

        if (data.phase === 'error') {
            fill.style.width = '100%';
            fill.classList.add('error');
            status.textContent = data.message;
            addLog('Error: ' + data.message);
            es.close();
            actions.innerHTML = '<button class="btn btn-secondary" onclick="dismissScrape()">Dismiss</button>';
            if (btn) btn.disabled = false;
            return;
        }

        status.textContent = data.message;
        addLog(data.message);

        if (data.phase === 'done') {
            es.close();
            actions.innerHTML = '<button class="btn btn-primary" onclick="finishScrape()">Done</button>';
        }
    };

    es.onerror = () => {
        es.close();
        fill.style.width = '100%';
        fill.classList.add('error');
        status.textContent = 'Connection lost';
        addLog('Error: Connection to server lost');
        actions.innerHTML = '<button class="btn btn-secondary" onclick="dismissScrape()">Dismiss</button>';
        if (btn) btn.disabled = false;
    };
}

function finishScrape() {
    location.reload();
}

function dismissScrape() {
    const overlay = document.querySelector('.scrape-overlay');
    if (overlay) overlay.remove();
    const btn = document.querySelector('.pull-btn');
    if (btn) btn.disabled = false;
}

function buildNav() {
    return `
    <div class="topbar">
        <span class="logo">Shasta PRA</span>
        <nav>
            <a href="/">Dashboard</a>
            <a href="/requests">Requests</a>
            <a href="/documents">Documents</a>
            <a href="/departments">Departments</a>
            <a href="/search">Search</a>
            <a href="/analytics">Analytics</a>
        </nav>
    </div>`;
}
