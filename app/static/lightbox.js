/* Lightbox — modal viewer for documents (PDF, images, video, audio)
   Uses /api/documents/{id}/preview for display, /api/documents/{id}/file for download */

const _MEDIA_EXTENSIONS = ['mp4','webm','mov','avi','mkv','mp3','m4a','wav','ogg','flac'];

/* Navigation state */
let _docList = [];
let _docIndex = -1;

function _transcriptPanel(docId) {
    return `<div class="lb-transcript-panel" id="lb-transcript-panel">
        <div class="lb-transcript-actions" id="lb-transcript-actions">
            <button class="btn btn-secondary btn-sm" onclick="loadTranscript(${docId})">Show Transcript</button>
        </div>
        <div class="lb-transcript-body" id="lb-transcript-body" style="display:none"></div>
    </div>`;
}

function formatTimestamp(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    return `${m}:${String(s).padStart(2,'0')}`;
}

async function loadTranscript(docId) {
    const actions = document.getElementById('lb-transcript-actions');
    const body = document.getElementById('lb-transcript-body');

    actions.innerHTML = '<span class="lb-transcript-loading">Loading transcript...</span>';
    body.style.display = 'none';

    try {
        const resp = await fetch(`/api/documents/${docId}/transcript`);

        if (resp.status === 404) {
            // No transcript yet — offer to transcribe
            actions.innerHTML = `
                <span style="color:var(--text-dim);font-size:.82rem">No transcript available</span>
                <button class="btn btn-primary btn-sm" onclick="triggerTranscribe(${docId})">Transcribe</button>`;
            return;
        }

        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const data = await resp.json();
        actions.innerHTML = `
            <button class="btn btn-secondary btn-sm" onclick="toggleTranscript()">Hide Transcript</button>
            <span class="lb-transcript-meta">${data.segments.length} segments | ${formatTimestamp(data.duration_seconds || 0)}</span>`;

        let html = '<div class="lb-segments">';
        for (const seg of data.segments) {
            const ts = formatTimestamp(seg.start);
            html += `<div class="lb-segment">
                <span class="lb-seg-time">${ts}</span>
                <span class="lb-seg-text">${escapeHtml(seg.text)}</span>
            </div>`;
        }
        html += '</div>';

        body.innerHTML = html;
        body.style.display = '';

    } catch (err) {
        actions.innerHTML = `<span class="error" style="font-size:.82rem">Failed to load transcript: ${escapeHtml(err.message)}</span>`;
    }
}

function toggleTranscript() {
    const body = document.getElementById('lb-transcript-body');
    const actions = document.getElementById('lb-transcript-actions');
    if (body.style.display === 'none') {
        body.style.display = '';
        actions.querySelector('button').textContent = 'Hide Transcript';
    } else {
        body.style.display = 'none';
        actions.querySelector('button').textContent = 'Show Transcript';
    }
}

async function triggerTranscribe(docId) {
    const actions = document.getElementById('lb-transcript-actions');
    actions.innerHTML = `
        <div class="lb-transcript-loading">
            <div class="lb-spinner" style="width:20px;height:20px;border-width:2px"></div>
            <span>Transcribing... this may take several minutes</span>
        </div>`;

    try {
        const resp = await fetch(`/api/documents/${docId}/transcribe`, { method: 'POST' });

        if (resp.status === 503) {
            actions.innerHTML = `<span class="error" style="font-size:.82rem">Transcription service not running. Start civic_media first.</span>`;
            return;
        }

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        // Transcription complete — load the transcript
        await loadTranscript(docId);

    } catch (err) {
        actions.innerHTML = `<span class="error" style="font-size:.82rem">Transcription failed: ${escapeHtml(err.message)}</span>`;
    }
}


/* ── Spreadsheet viewer (SheetJS) ────────────────────────────────────────── */

async function _loadSpreadsheet(docId, ext) {
    const container = document.getElementById('lb-sheet-container');
    if (!container) return;

    try {
        const resp = await fetch(`/api/documents/${docId}/file`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const buf = await resp.arrayBuffer();
        const wb = XLSX.read(new Uint8Array(buf), { type: 'array' });

        // Build tab bar if multiple sheets
        let tabsHtml = '';
        if (wb.SheetNames.length > 1) {
            tabsHtml = '<div class="lb-sheet-tabs">';
            wb.SheetNames.forEach((name, i) => {
                tabsHtml += `<button class="lb-sheet-tab${i === 0 ? ' active' : ''}" onclick="_switchSheet(this, ${i})">${escapeHtml(name)}</button>`;
            });
            tabsHtml += '</div>';
        }

        // Render each sheet as hidden HTML table
        let sheetsHtml = '';
        wb.SheetNames.forEach((name, i) => {
            const ws = wb.Sheets[name];
            const html = XLSX.utils.sheet_to_html(ws, { editable: false });
            sheetsHtml += `<div class="lb-sheet-content" data-sheet="${i}" style="${i === 0 ? '' : 'display:none'}">${html}</div>`;
        });

        container.innerHTML = tabsHtml + sheetsHtml;
    } catch (err) {
        container.innerHTML = `<div class="lb-fallback">
            <p>Failed to load spreadsheet: ${escapeHtml(err.message)}</p>
            <a href="/api/documents/${docId}/file" download class="btn btn-primary">Download File</a>
        </div>`;
    }
}

function _switchSheet(btn, index) {
    const container = btn.closest('.lb-spreadsheet');
    if (!container) return;

    container.querySelectorAll('.lb-sheet-tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');

    container.querySelectorAll('.lb-sheet-content').forEach(s => {
        s.style.display = parseInt(s.dataset.sheet) === index ? '' : 'none';
    });
}

/* ── Email viewer (.msg) ────────────────────────────────────────────────── */

async function _loadEmail(docId) {
    const container = document.getElementById('lb-email-container');
    if (!container) return;

    try {
        const resp = await fetch(`/api/documents/${docId}/email`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const data = await resp.json();

        const headers = [
            ['From', data.sender],
            ['To', data.to],
            ['CC', data.cc],
            ['Date', data.date],
            ['Subject', data.subject],
        ].filter(([, v]) => v);

        let html = '<div class="lb-email-headers">';
        for (const [label, value] of headers) {
            html += `<div class="lb-email-row"><span class="lb-email-label">${label}</span><span class="lb-email-value">${escapeHtml(value)}</span></div>`;
        }
        html += '</div>';

        if (data.body_html) {
            html += '<iframe class="lb-email-body" sandbox="allow-same-origin"></iframe>';
        } else if (data.body_text) {
            html += `<pre class="lb-email-text">${escapeHtml(data.body_text)}</pre>`;
        } else {
            html += '<p style="padding:1rem;color:var(--text-dim)">No message body</p>';
        }

        container.innerHTML = html;

        // Set srcdoc via DOM to avoid quote-escaping issues in template literals
        if (data.body_html) {
            const iframe = container.querySelector('.lb-email-body');
            if (iframe) iframe.srcdoc = data.body_html;
        }
    } catch (err) {
        container.innerHTML = `<div class="lb-fallback">
            <p>Failed to load email: ${escapeHtml(err.message)}</p>
            <a href="/api/documents/${docId}/file" download class="btn btn-primary">Download File</a>
        </div>`;
    }
}

/* ── Text / HTML file viewer ────────────────────────────────────────────── */

async function _loadTextFile(docId, ext) {
    const container = document.getElementById('lb-text-container');
    if (!container) return;

    try {
        const resp = await fetch(`/api/documents/${docId}/file`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const text = await resp.text();

        if (ext === 'html') {
            container.innerHTML = '<iframe class="lb-text-iframe" sandbox="allow-same-origin"></iframe>';
            const iframe = container.querySelector('.lb-text-iframe');
            if (iframe) iframe.srcdoc = text;
        } else {
            container.innerHTML = `<pre class="lb-text-pre">${escapeHtml(text)}</pre>`;
        }
    } catch (err) {
        container.innerHTML = `<div class="lb-fallback">
            <p>Failed to load file: ${escapeHtml(err.message)}</p>
            <a href="/api/documents/${docId}/file" download class="btn btn-primary">Download File</a>
        </div>`;
    }
}


function openLightboxWithNav(doc, docList) {
    _docList = docList || [];
    _docIndex = _docList.findIndex(d => d.id === doc.id);
    openLightbox(doc);
}

function navLightbox(delta) {
    const newIndex = _docIndex + delta;
    if (newIndex < 0 || newIndex >= _docList.length) return;
    _docIndex = newIndex;
    openLightbox(_docList[_docIndex]);
}

function _updateNavArrows() {
    const prev = document.getElementById('lb-prev');
    const next = document.getElementById('lb-next');
    if (!prev || !next) return;

    if (_docList.length <= 1) {
        prev.style.display = 'none';
        next.style.display = 'none';
        return;
    }
    prev.style.display = _docIndex > 0 ? '' : 'none';
    next.style.display = _docIndex < _docList.length - 1 ? '' : 'none';
}

function openLightbox(doc) {
    const overlay = document.getElementById('lightbox');
    const content = document.getElementById('lb-content');
    const ext = (doc.file_extension || '').toLowerCase();

    const previewUrl = `/api/documents/${doc.id}/preview`;
    const fileUrl = `/api/documents/${doc.id}/file`;
    const title = escapeHtml(doc.title || 'Document');
    const isMedia = _MEDIA_EXTENSIONS.includes(ext);
    const navInfo = _docList.length > 1 ? `<span class="lb-nav-info">${_docIndex + 1} / ${_docList.length}</span>` : '';

    // "Save as PDF" for types that support conversion
    const _OFFICE_EXTS = ['docx','doc','pptx','ppt','odt','ods','odp','rtf'];
    let savePdfBtn = '';
    if (ext === 'msg') {
        savePdfBtn = `<a href="/api/documents/${doc.id}/email/pdf" download class="btn btn-secondary btn-sm">Save as PDF</a>`;
    } else if (_OFFICE_EXTS.includes(ext)) {
        savePdfBtn = `<a href="${previewUrl}" download class="btn btn-secondary btn-sm">Save as PDF</a>`;
    }

    // Toolbar always shown
    const toolbar = `
        <div class="lb-toolbar">
            <span class="lb-title" title="${title}">${title}</span>
            ${navInfo}
            <div class="lb-actions">
                ${savePdfBtn}
                <a href="${fileUrl}" download class="btn btn-primary btn-sm">Download original</a>
            </div>
        </div>`;

    let body = '';

    if (ext === 'pdf') {
        body = `<embed src="${previewUrl}" type="application/pdf" class="lb-pdf">`;
    } else if (['jpg','jpeg','png','gif','bmp','webp','svg'].includes(ext)) {
        body = `<img src="${fileUrl}" alt="${title}">`;
    } else if (['tif','tiff'].includes(ext)) {
        // Browsers can't render TIFF — offer download
        body = `<div class="lb-fallback">
            <p>TIFF preview not supported in browsers</p>
            <a href="${fileUrl}" download class="btn btn-primary">Download File</a>
        </div>`;
    } else if (['mp4','webm','mov','avi','mkv'].includes(ext)) {
        body = `<video controls autoplay><source src="${fileUrl}">Your browser does not support video.</video>`;
        body += _transcriptPanel(doc.id);
    } else if (['mp3','m4a','wav','ogg','flac'].includes(ext)) {
        body = `<div class="lb-audio-wrap">
            <p style="font-weight:600;margin-bottom:1rem">${title}</p>
            <audio controls autoplay><source src="${fileUrl}">Your browser does not support audio.</audio>
        </div>`;
        body += _transcriptPanel(doc.id);
    } else if (['xlsx','xls','csv'].includes(ext)) {
        // Spreadsheets — client-side rendering with SheetJS
        body = `<div class="lb-spreadsheet" id="lb-sheet-container">
            <div class="lb-loading" id="lb-loading">
                <div class="lb-spinner"></div>
                <p>Loading spreadsheet...</p>
            </div>
        </div>`;
        setTimeout(() => _loadSpreadsheet(doc.id, ext), 0);
    } else if (ext === 'msg') {
        // Outlook email — parsed server-side with extract-msg
        body = `<div class="lb-email" id="lb-email-container">
            <div class="lb-loading" id="lb-loading">
                <div class="lb-spinner"></div>
                <p>Loading email...</p>
            </div>
        </div>`;
        setTimeout(() => _loadEmail(doc.id), 0);
    } else if (['txt','html'].includes(ext)) {
        // Text / HTML files — inline display
        body = `<div class="lb-text" id="lb-text-container">
            <div class="lb-loading" id="lb-loading">
                <div class="lb-spinner"></div>
                <p>Loading file...</p>
            </div>
        </div>`;
        setTimeout(() => _loadTextFile(doc.id, ext), 0);
    } else if (['docx','doc','pptx','ppt','odt','ods','odp','rtf'].includes(ext)) {
        // Office docs — preview endpoint converts to PDF via LibreOffice
        // Show loading indicator while conversion happens
        body = `<div class="lb-loading" id="lb-loading">
            <div class="lb-spinner"></div>
            <p>Converting document to PDF...</p>
        </div>
        <embed src="${previewUrl}" type="application/pdf" class="lb-pdf" style="display:none" onload="this.style.display='';var l=document.getElementById('lb-loading');if(l)l.remove();">`;
        // Fallback: hide spinner after timeout in case onload doesn't fire
        setTimeout(() => {
            const loading = document.getElementById('lb-loading');
            const embed = content.querySelector('embed.lb-pdf');
            if (loading) loading.remove();
            if (embed) embed.style.display = '';
        }, 15000);
    } else {
        body = `<div class="lb-fallback">
            <p>Preview not available for .${escapeHtml(ext)} files</p>
            <a href="${fileUrl}" download class="btn btn-primary">Download File</a>
        </div>`;
    }

    content.innerHTML = toolbar + body;
    overlay.classList.add('active');
    _updateNavArrows();
}

function closeLightbox() {
    const overlay = document.getElementById('lightbox');
    const content = document.getElementById('lb-content');
    overlay.classList.remove('active');
    content.innerHTML = '';
    _docList = [];
    _docIndex = -1;
}

document.addEventListener('DOMContentLoaded', () => {
    const overlay = document.getElementById('lightbox');

    // Create nav arrows dynamically
    const prevBtn = document.createElement('button');
    prevBtn.id = 'lb-prev';
    prevBtn.className = 'lb-nav lb-nav-prev';
    prevBtn.innerHTML = '&#x2039;';
    prevBtn.title = 'Previous document (Left arrow)';
    prevBtn.style.display = 'none';
    prevBtn.addEventListener('click', e => { e.stopPropagation(); navLightbox(-1); });
    overlay.appendChild(prevBtn);

    const nextBtn = document.createElement('button');
    nextBtn.id = 'lb-next';
    nextBtn.className = 'lb-nav lb-nav-next';
    nextBtn.innerHTML = '&#x203a;';
    nextBtn.title = 'Next document (Right arrow)';
    nextBtn.style.display = 'none';
    nextBtn.addEventListener('click', e => { e.stopPropagation(); navLightbox(1); });
    overlay.appendChild(nextBtn);

    document.getElementById('lb-close').addEventListener('click', closeLightbox);
    overlay.addEventListener('click', e => {
        if (e.target === e.currentTarget) closeLightbox();
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeLightbox();
        if (!overlay.classList.contains('active')) return;
        if (e.key === 'ArrowLeft') navLightbox(-1);
        if (e.key === 'ArrowRight') navLightbox(1);
    });
});
