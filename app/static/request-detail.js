/* Request detail page — metadata, timeline, documents */

function cleanTimelineHtml(raw) {
    // Replace <br>, <br/>, <p>, </p> with line breaks, strip all other tags
    let text = raw
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<\/p>/gi, '\n')
        .replace(/<[^>]+>/g, '')
        .trim();
    // Escape for safe display, then convert newlines to <br>
    const lines = text.split('\n').filter(l => l.trim());
    if (lines.length <= 1) return escapeHtml(text);
    // Multiple items — show as a compact list
    return '<ul class="tl-file-list">' +
        lines.map(l => `<li>${escapeHtml(l.trim())}</li>`).join('') +
        '</ul>';
}

function cleanRequestHtml(html) {
    if (!html) return '';
    const div = document.createElement('div');
    div.innerHTML = html;

    // Add href to bare <a> tags that contain URL-like text
    div.querySelectorAll('a:not([href])').forEach(a => {
        const text = a.textContent.trim();
        if (/^(https?:\/\/|www\.)/.test(text)) {
            const url = text.startsWith('www.') ? 'https://' + text : text;
            a.href = url;
            a.target = '_blank';
            a.rel = 'noopener';
        } else if (/@/.test(text) && !text.startsWith('mailto:')) {
            a.href = 'mailto:' + text;
        } else if (/^mailto:/.test(text)) {
            a.href = text;
            a.textContent = text.replace('mailto:', '');
        }
    });

    // Hide long proxy URLs shown as "&lt;https://protect.checkpoint.com/...&gt;" after a readable link
    // These appear as: <a>readable</a> &lt;<a>long_proxy_url</a>&gt;
    div.querySelectorAll('a[href]').forEach(a => {
        if (/protect\.checkpoint\.com|safelinks\.protection\.outlook/.test(a.href)) {
            // Walk backwards/forwards to remove the surrounding &lt; &gt; text and the link itself
            let node = a;
            // Check previous text node for "&lt;" or "<"
            const prev = node.previousSibling;
            if (prev && prev.nodeType === 3) {
                prev.textContent = prev.textContent.replace(/\s*<?\s*$/, '');
            }
            // Check next text node for "&gt;" or ">" — leave a space if text follows
            const next = node.nextSibling;
            if (next && next.nodeType === 3) {
                const cleaned = next.textContent.replace(/^\s*>?\s*/, '');
                next.textContent = cleaned ? ' ' + cleaned : '';
            }
            a.remove();
        }
    });

    return div.innerHTML;
}

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
                        ${cleanRequestHtml(req.request_text_html) || escapeHtml(req.request_text || 'No request text available')}
                    </div>

                    ${req.timeline.length ? `
                    <h2 style="font-size:1.1rem; margin-bottom:.75rem;">Timeline</h2>
                    <div class="timeline">
                        ${req.timeline.map(t => `
                            <div class="timeline-item">
                                <div class="tl-text">
                                    ${t.timeline_icon_class ? `<i class="${escapeHtml(t.timeline_icon_class)} tl-icon"></i>` : ''}
                                    ${cleanTimelineHtml(t.timeline_display_text || t.timeline_name || '')}
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
        window._docList = req.documents.filter(d => d.downloaded);

    } catch (err) {
        container.innerHTML = `<div class="error">Failed to load request: ${escapeHtml(err.message)}</div>`;
    }
});

function handleDocClick(docId, downloaded, assetUrl) {
    if (downloaded && window._docs[docId]) {
        openLightboxWithNav(window._docs[docId], window._docList || []);
    } else if (assetUrl) {
        window.open(assetUrl.startsWith('//') ? 'https:' + assetUrl : assetUrl, '_blank');
    }
}
