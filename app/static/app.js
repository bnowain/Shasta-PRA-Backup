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

// Highlight current nav link
document.addEventListener('DOMContentLoaded', () => {
    const path = location.pathname;
    document.querySelectorAll('.topbar nav a').forEach(a => {
        const href = a.getAttribute('href');
        if (href === '/' && path === '/') a.classList.add('active');
        else if (href !== '/' && path.startsWith(href)) a.classList.add('active');
    });
});

function buildNav() {
    return `
    <div class="topbar">
        <span class="logo">Shasta PRA</span>
        <nav>
            <a href="/">Dashboard</a>
            <a href="/requests">Requests</a>
            <a href="/departments">Departments</a>
            <a href="/search">Search</a>
            <a href="/analytics">Analytics</a>
        </nav>
    </div>`;
}
