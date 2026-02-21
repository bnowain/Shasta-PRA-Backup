/* Request detail page — metadata, timeline, documents */

document.addEventListener('DOMContentLoaded', async () => {
    const pathParts = location.pathname.split('/');
    const prettyId = decodeURIComponent(pathParts[pathParts.length - 1]);
    const container = document.getElementById('detail-content');

    try {
        const req = await apiFetch(`/api/requests/${encodeURIComponent(prettyId)}`);
        document.title = `PRA ${req.pretty_id} — Shasta PRA`;

        container.innerHTML = `
            <div style="margin-bottom:1rem">
                <a href="/requests" style="font-size:.85rem">&larr; Back to requests</a>
            </div>
            <h1 class="page-title">Request ${escapeHtml(req.pretty_id)} ${statusPill(req.request_state)}</h1>

            <div class="detail-grid">
                <div class="detail-main">
                    <div class="request-text-box">
                        ${req.request_text_html || escapeHtml(req.request_text || 'No request text available')}
                    </div>

                    ${req.timeline.length ? `
                    <h2 style="font-size:1.1rem; margin-bottom:.75rem;">Timeline</h2>
                    <div class="timeline">
                        ${req.timeline.map(t => `
                            <div class="timeline-item">
                                <div class="tl-text">
                                    ${t.timeline_icon_class ? `<i class="${escapeHtml(t.timeline_icon_class)} tl-icon"></i>` : ''}
                                    ${escapeHtml(t.timeline_display_text || t.timeline_name || '')}
                                </div>
                                ${t.timeline_byline ? `<div class="tl-byline">${escapeHtml(t.timeline_byline)}</div>` : ''}
                            </div>
                        `).join('')}
                    </div>
                    ` : ''}

                    ${req.documents.length ? `
                    <h2 style="font-size:1.1rem; margin:1.5rem 0 .75rem;">Documents (${req.documents.length})</h2>
                    <div class="table-wrap">
                        <table>
                            <thead><tr>
                                <th>Title</th><th>Type</th><th>Size</th><th>Date</th><th>Status</th>
                            </tr></thead>
                            <tbody>
                                ${req.documents.map(d => `
                                    <tr class="doc-row" onclick="handleDocClick(${d.id}, ${d.downloaded}, '${escapeHtml(d.asset_url || '')}')">
                                        <td>${escapeHtml(d.title || 'Untitled')}</td>
                                        <td><span class="doc-ext">${escapeHtml(d.file_extension || '?')}</span></td>
                                        <td>${d.file_size_mb ? d.file_size_mb.toFixed(2) + ' MB' : '—'}</td>
                                        <td style="white-space:nowrap">${escapeHtml(d.upload_date || '—')}</td>
                                        <td>${d.downloaded ? '<span class="pill pill-green">Downloaded</span>' : '<span class="pill pill-gray">Metadata</span>'}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                    ` : ''}
                </div>

                <div class="detail-sidebar">
                    <div class="card">
                        <div class="meta-row"><span class="meta-label">Department</span><span>${escapeHtml(req.department_names || '—')}</span></div>
                        <div class="meta-row"><span class="meta-label">POC</span><span>${escapeHtml(req.poc_name || '—')}</span></div>
                        <div class="meta-row"><span class="meta-label">Requester</span><span>${escapeHtml(req.requester_name || '—')}</span></div>
                        ${req.requester_company ? `<div class="meta-row"><span class="meta-label">Company</span><span>${escapeHtml(req.requester_company)}</span></div>` : ''}
                        <div class="meta-row"><span class="meta-label">Filed</span><span>${formatDate(req.request_date)}</span></div>
                        <div class="meta-row"><span class="meta-label">Due</span><span>${formatDate(req.due_date)}</span></div>
                        ${req.closed_date ? `<div class="meta-row"><span class="meta-label">Closed</span><span>${formatDate(req.closed_date)}</span></div>` : ''}
                        ${req.staff_cost ? `<div class="meta-row"><span class="meta-label">Cost</span><span>${escapeHtml(req.staff_cost)}</span></div>` : ''}
                        ${req.request_staff_hours ? `<div class="meta-row"><span class="meta-label">Hours</span><span>${escapeHtml(req.request_staff_hours)}</span></div>` : ''}
                        ${req.page_url ? `<div class="meta-row"><a href="${escapeHtml(req.page_url)}" target="_blank" rel="noopener">View on NextRequest &rarr;</a></div>` : ''}
                    </div>
                </div>
            </div>
        `;

        // Store document data for lightbox
        window._docs = {};
        req.documents.forEach(d => { window._docs[d.id] = d; });

    } catch (err) {
        container.innerHTML = `<div class="error">Failed to load request: ${escapeHtml(err.message)}</div>`;
    }
});

function handleDocClick(docId, downloaded, assetUrl) {
    if (downloaded && window._docs[docId]) {
        openLightbox(window._docs[docId]);
    } else if (assetUrl) {
        window.open(assetUrl.startsWith('//') ? 'https:' + assetUrl : assetUrl, '_blank');
    }
}
