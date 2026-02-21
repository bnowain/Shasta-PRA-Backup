/* Search page — grouped results with highlights */

document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('search-input');
    const btn = document.getElementById('btn-search');

    btn.addEventListener('click', doSearch);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });

    // Check URL for initial query
    const urlQ = new URLSearchParams(location.search).get('q');
    if (urlQ) {
        input.value = urlQ;
        doSearch();
    }
});

async function doSearch() {
    const q = document.getElementById('search-input').value.trim();
    const resultsDiv = document.getElementById('search-results');
    if (!q) { resultsDiv.innerHTML = ''; return; }

    resultsDiv.innerHTML = '<div class="loading">Searching...</div>';

    try {
        const data = await apiFetch(`/api/search?q=${encodeURIComponent(q)}&limit=30`);
        let html = '';

        if (data.requests.length) {
            html += `<div class="result-group">
                <h3>Requests (${data.requests.length})</h3>
                ${data.requests.map(r => `
                    <div class="result-item" onclick="location.href='/requests/${encodeURIComponent(r.pretty_id)}'" style="cursor:pointer">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.3rem">
                            <strong>${escapeHtml(r.pretty_id)}</strong>
                            ${statusPill(r.request_state)}
                        </div>
                        <div style="font-size:.87rem">${highlight(r.request_text || '', q)}</div>
                        <div style="font-size:.78rem;color:var(--text-dim);margin-top:.3rem">
                            ${escapeHtml(r.department_names || '')} &middot; ${formatDate(r.request_date)}
                        </div>
                    </div>
                `).join('')}
            </div>`;
        }

        if (data.timeline_events.length) {
            html += `<div class="result-group">
                <h3>Timeline Events (${data.timeline_events.length})</h3>
                ${data.timeline_events.map(t => `
                    <div class="result-item">
                        <div style="font-size:.87rem">${highlight(t.timeline_display_text || '', q)}</div>
                        ${t.timeline_byline ? `<div style="font-size:.78rem;color:var(--text-dim);margin-top:.2rem">${highlight(t.timeline_byline, q)}</div>` : ''}
                    </div>
                `).join('')}
            </div>`;
        }

        if (data.documents.length) {
            html += `<div class="result-group">
                <h3>Documents (${data.documents.length})</h3>
                ${data.documents.map(d => `
                    <div class="result-item">
                        <div style="display:flex;align-items:center;gap:.5rem">
                            <span class="doc-ext">${escapeHtml(d.file_extension || '?')}</span>
                            <span>${highlight(d.title || 'Untitled', q)}</span>
                        </div>
                        ${d.file_size_mb ? `<div style="font-size:.78rem;color:var(--text-dim);margin-top:.2rem">${d.file_size_mb.toFixed(2)} MB</div>` : ''}
                    </div>
                `).join('')}
            </div>`;
        }

        if (!html) {
            html = '<div style="text-align:center;padding:2rem;color:var(--text-dim)">No results found</div>';
        }

        resultsDiv.innerHTML = html;
    } catch (err) {
        resultsDiv.innerHTML = `<div class="error">${escapeHtml(err.message)}</div>`;
    }
}

function highlight(text, query) {
    if (!text || !query) return escapeHtml(text);
    const safe = escapeHtml(text);
    const q = escapeHtml(query);
    const regex = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return safe.replace(regex, '<mark>$1</mark>');
}
