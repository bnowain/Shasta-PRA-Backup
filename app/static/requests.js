/* Request browser — filter, paginate, sort */

let currentOffset = 0;
const PAGE_SIZE = 50;

document.addEventListener('DOMContentLoaded', async () => {
    // Populate filter dropdowns
    try {
        const [stats, depts] = await Promise.all([
            apiFetch('/api/stats'),
            apiFetch('/api/departments'),
        ]);
        const statusSel = document.getElementById('f-status');
        stats.status_breakdown.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.status;
            opt.textContent = `${s.status} (${s.count})`;
            statusSel.appendChild(opt);
        });
        const deptSel = document.getElementById('f-dept');
        depts.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.name;
            opt.textContent = `${d.name} (${d.request_count})`;
            deptSel.appendChild(opt);
        });
    } catch (e) { console.error('Filter init error:', e); }

    // Check URL params for initial filter
    const urlParams = new URLSearchParams(location.search);
    if (urlParams.get('q')) document.getElementById('f-query').value = urlParams.get('q');
    if (urlParams.get('status')) document.getElementById('f-status').value = urlParams.get('status');
    if (urlParams.get('department')) document.getElementById('f-dept').value = urlParams.get('department');

    document.getElementById('btn-filter').addEventListener('click', () => { currentOffset = 0; loadRequests(); });
    document.getElementById('btn-clear').addEventListener('click', clearFilters);
    document.getElementById('f-query').addEventListener('keydown', e => { if (e.key === 'Enter') { currentOffset = 0; loadRequests(); } });

    loadRequests();
});

function getFilterParams() {
    const params = new URLSearchParams();
    const q = document.getElementById('f-query').value.trim();
    const status = document.getElementById('f-status').value;
    const dept = document.getElementById('f-dept').value;
    const poc = document.getElementById('f-poc').value.trim();
    const from = document.getElementById('f-from').value;
    const to = document.getElementById('f-to').value;
    const sort = document.getElementById('f-sort').value;

    if (q) params.set('q', q);
    if (status) params.set('status', status);
    if (dept) params.set('department', dept);
    if (poc) params.set('poc', poc);
    if (from) params.set('date_from', from);
    if (to) params.set('date_to', to);
    params.set('sort', sort);
    params.set('limit', PAGE_SIZE);
    params.set('offset', currentOffset);
    return params;
}

async function loadRequests() {
    const tbody = document.getElementById('req-table');
    const info = document.getElementById('results-info');
    tbody.innerHTML = '<tr><td colspan="7" class="loading">Loading...</td></tr>';

    try {
        const params = getFilterParams();
        const data = await apiFetch('/api/requests?' + params.toString());
        info.textContent = `${data.total.toLocaleString()} requests found`;

        if (data.results.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:2rem;color:var(--text-dim)">No results</td></tr>';
        } else {
            tbody.innerHTML = data.results.map(r => `
                <tr onclick="location.href='/requests/${encodeURIComponent(r.pretty_id)}'">
                    <td><strong>${escapeHtml(r.pretty_id)}</strong></td>
                    <td>${statusPill(r.request_state)}</td>
                    <td>${escapeHtml(truncate(r.request_text, 100))}</td>
                    <td>${escapeHtml(r.department_names || '—')}</td>
                    <td>${escapeHtml(r.poc_name || '—')}</td>
                    <td style="white-space:nowrap">${formatDate(r.request_date)}</td>
                    <td class="text-right">${r.doc_count}</td>
                </tr>
            `).join('');
        }

        renderPagination(data.total);
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7" class="error">${escapeHtml(err.message)}</td></tr>`;
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
    loadRequests();
    window.scrollTo(0, 0);
}

function clearFilters() {
    document.getElementById('f-query').value = '';
    document.getElementById('f-status').value = '';
    document.getElementById('f-dept').value = '';
    document.getElementById('f-poc').value = '';
    document.getElementById('f-from').value = '';
    document.getElementById('f-to').value = '';
    document.getElementById('f-sort').value = 'newest';
    currentOffset = 0;
    loadRequests();
}
