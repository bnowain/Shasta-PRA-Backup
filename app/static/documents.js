/* Documents catalog — filter, paginate, preview */

let currentOffset = 0;
const PAGE_SIZE = 50;

document.addEventListener('DOMContentLoaded', async () => {
    // Populate file type dropdown from DB
    try {
        const exts = await apiFetch('/api/documents/extensions');
        const extSel = document.getElementById('f-ext');
        exts.forEach(e => {
            const opt = document.createElement('option');
            opt.value = e.ext;
            opt.textContent = `.${e.ext} (${e.count})`;
            extSel.appendChild(opt);
        });
    } catch (e) { console.error('Extension filter init error:', e); }

    document.getElementById('btn-filter').addEventListener('click', () => { currentOffset = 0; loadDocuments(); });
    document.getElementById('btn-clear').addEventListener('click', clearFilters);
    document.getElementById('f-query').addEventListener('keydown', e => { if (e.key === 'Enter') { currentOffset = 0; loadDocuments(); } });

    loadDocuments();
});

function getFilterParams() {
    const params = new URLSearchParams();
    const q = document.getElementById('f-query').value.trim();
    const ext = document.getElementById('f-ext').value;
    const from = document.getElementById('f-from').value;
    const to = document.getElementById('f-to').value;
    const sort = document.getElementById('f-sort').value;

    if (q) params.set('q', q);
    if (ext) params.set('ext', ext);
    if (from) params.set('date_from', from);
    if (to) params.set('date_to', to);
    params.set('sort', sort);
    params.set('limit', PAGE_SIZE);
    params.set('offset', currentOffset);
    return params;
}

async function loadDocuments() {
    const tbody = document.getElementById('doc-table');
    const info = document.getElementById('results-info');
    tbody.innerHTML = '<tr><td colspan="7" class="loading">Loading...</td></tr>';

    try {
        const params = getFilterParams();
        const data = await apiFetch('/api/documents?' + params.toString());
        info.textContent = `${data.total.toLocaleString()} documents found`;

        // Store docs for lightbox
        window._docs = {};
        data.results.forEach(d => { window._docs[d.id] = d; });
        window._docList = data.results.filter(d => d.downloaded);

        if (data.results.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:2rem;color:var(--text-dim)">No documents found</td></tr>';
        } else {
            tbody.innerHTML = data.results.map(d => `
                <tr class="doc-row" onclick="handleDocRowClick(${d.id}, ${d.downloaded}, '${escapeHtml(d.asset_url || '')}')">
                    <td>${escapeHtml(d.title || 'Untitled')}</td>
                    <td><span class="doc-ext">${escapeHtml(d.file_extension || '?')}</span></td>
                    <td>${d.file_size_mb ? d.file_size_mb.toFixed(2) + ' MB' : '—'}</td>
                    <td>${d.request_pretty_id ? `<a href="/requests/${encodeURIComponent(d.request_pretty_id)}" onclick="event.stopPropagation()">${escapeHtml(d.request_pretty_id)}</a>` : '—'}</td>
                    <td style="white-space:nowrap">${escapeHtml(d.upload_date || '—')}</td>
                    <td>${d.downloaded ? '<span class="pill pill-green">Downloaded</span>' : '<span class="pill pill-gray">Metadata</span>'}</td>
                    <td>
                        ${d.downloaded ? `<a href="/api/documents/${d.id}/file" download onclick="event.stopPropagation()" class="btn btn-secondary btn-sm">Download</a>` : ''}
                    </td>
                </tr>
            `).join('');
        }

        renderPagination(data.total);
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7" class="error">${escapeHtml(err.message)}</td></tr>`;
    }
}

function handleDocRowClick(docId, downloaded, assetUrl) {
    if (downloaded && window._docs[docId]) {
        openLightboxWithNav(window._docs[docId], window._docList || []);
    } else if (assetUrl) {
        window.open(assetUrl.startsWith('//') ? 'https:' + assetUrl : assetUrl, '_blank');
    }
}

function renderPagination(total) {
    const pg = document.getElementById('pagination');
    const totalPages = Math.ceil(total / PAGE_SIZE);
    const currentPage = Math.floor(currentOffset / PAGE_SIZE) + 1;
    if (totalPages <= 1) { pg.innerHTML = ''; return; }
    pg.innerHTML = `
        <button ${currentPage <= 1 ? 'disabled' : ''} onclick="goPage(${currentPage - 1})">Prev</button>
        <span class="page-info">Page ${currentPage} of ${totalPages}</span>
        <button ${currentPage >= totalPages ? 'disabled' : ''} onclick="goPage(${currentPage + 1})">Next</button>
    `;
}

function goPage(page) {
    currentOffset = (page - 1) * PAGE_SIZE;
    loadDocuments();
    window.scrollTo(0, 0);
}

function clearFilters() {
    document.getElementById('f-query').value = '';
    document.getElementById('f-ext').value = '';
    document.getElementById('f-from').value = '';
    document.getElementById('f-to').value = '';
    document.getElementById('f-sort').value = 'newest';
    currentOffset = 0;
    loadDocuments();
}
