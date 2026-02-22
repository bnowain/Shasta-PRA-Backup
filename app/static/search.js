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

function stripHtml(str) {
    if (!str) return '';
    // Replace <br> and block tags with spaces so words don't smush together
    let s = str.replace(/<br\s*\/?>/gi, ' ').replace(/<\/(p|div|li|tr|td|th)>/gi, ' ');
    const tmp = document.createElement('div');
    tmp.innerHTML = s;
    return (tmp.textContent || tmp.innerText || '').replace(/\s+/g, ' ').trim();
}

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
                ${data.timeline_events.map(t => {
                    const rawText = t.timeline_display_text || '';
                    const cleanByline = stripHtml(t.timeline_byline || '');
                    const linkHref = t.request_pretty_id ? `/requests/${encodeURIComponent(t.request_pretty_id)}` : null;

                    // Detect document lists (br-separated filenames)
                    const isDocList = rawText.includes('<br>') && /\.\w{2,5}(<br|\s*$)/i.test(rawText);
                    let bodyHtml;
                    if (isDocList) {
                        const names = rawText.split(/<br\s*\/?>/gi).map(n => n.replace(/<[^>]*>/g, '').trim()).filter(Boolean);
                        const MAX_BUBBLES = 20;
                        const shown = names.slice(0, MAX_BUBBLES);
                        const remaining = names.length - shown.length;
                        bodyHtml = '<div class="doc-bubble-wrap">' +
                            shown.map(n => `<span class="doc-bubble">${highlight(n, q)}</span>`).join('') +
                            (remaining > 0 ? `<a class="doc-bubble-more" ${linkHref ? `href="${linkHref}"` : ''} onclick="event.stopPropagation()">View all</a>` : '') +
                            '</div>';
                    } else {
                        const cleanText = stripHtml(rawText);
                        const truncText = cleanText.length > 300 ? cleanText.slice(0, 300) + '...' : cleanText;
                        bodyHtml = `<div style="font-size:.87rem">${highlight(truncText, q)}</div>`;
                    }

                    return `
                    <div class="result-item" ${linkHref ? `onclick="location.href='${linkHref}'" style="cursor:pointer"` : ''}>
                        <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.3rem">
                            ${t.request_pretty_id ? `<span class="pill pill-blue">${escapeHtml(t.request_pretty_id)}</span>` : ''}
                            ${t.timeline_name ? `<span style="font-size:.78rem;font-weight:600;color:var(--text-dim)">${escapeHtml(t.timeline_name)}</span>` : ''}
                        </div>
                        ${bodyHtml}
                        ${cleanByline ? `<div style="font-size:.78rem;color:var(--text-dim);margin-top:.3rem">${highlight(cleanByline, q)}</div>` : ''}
                    </div>`;
                }).join('')}
            </div>`;
        }

        if (data.documents.length) {
            html += `<div class="result-group">
                <h3>Documents (${data.documents.length})</h3>
                ${data.documents.map(d => {
                    const linkHref = d.request_pretty_id ? `/requests/${encodeURIComponent(d.request_pretty_id)}` : null;
                    return `
                    <div class="result-item" ${linkHref ? `onclick="location.href='${linkHref}'" style="cursor:pointer"` : ''}>
                        <div style="display:flex;align-items:center;gap:.5rem">
                            <span class="doc-ext">${escapeHtml(d.file_extension || '?')}</span>
                            <span>${highlight(d.title || 'Untitled', q)}</span>
                            ${d.request_pretty_id ? `<span class="pill pill-blue" style="margin-left:auto">${escapeHtml(d.request_pretty_id)}</span>` : ''}
                        </div>
                        ${d.file_size_mb ? `<div style="font-size:.78rem;color:var(--text-dim);margin-top:.2rem">${d.file_size_mb.toFixed(2)} MB</div>` : ''}
                    </div>`;
                }).join('')}
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
