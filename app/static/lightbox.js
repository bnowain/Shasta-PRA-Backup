/* Lightbox — modal viewer for documents (PDF, images, video, audio)
   Uses /api/documents/{id}/preview for display, /api/documents/{id}/file for download */

function openLightbox(doc) {
    const overlay = document.getElementById('lightbox');
    const content = document.getElementById('lb-content');
    const ext = (doc.file_extension || '').toLowerCase();

    const previewUrl = `/api/documents/${doc.id}/preview`;
    const fileUrl = `/api/documents/${doc.id}/file`;
    const title = escapeHtml(doc.title || 'Document');

    // Toolbar always shown
    const toolbar = `
        <div class="lb-toolbar">
            <span class="lb-title" title="${title}">${title}</span>
            <div class="lb-actions">
                <a href="${previewUrl}" target="_blank" class="btn btn-secondary btn-sm">Open in new tab</a>
                <a href="${fileUrl}" download class="btn btn-primary btn-sm">Download original</a>
            </div>
        </div>`;

    let body = '';

    if (ext === 'pdf') {
        body = `<object data="${previewUrl}" type="application/pdf" class="lb-pdf">
            <iframe src="${previewUrl}" title="${title}"></iframe>
        </object>`;
    } else if (['jpg','jpeg','png','gif','bmp','webp','svg'].includes(ext)) {
        body = `<img src="${fileUrl}" alt="${title}">`;
    } else if (['tif','tiff'].includes(ext)) {
        // Browsers can't render TIFF — offer download
        body = `<div class="lb-fallback">
            <p>TIFF preview not supported in browsers</p>
            <a href="${fileUrl}" download class="btn btn-primary">Download File</a>
        </div>`;
    } else if (['mp4','webm','mov','avi'].includes(ext)) {
        body = `<video controls autoplay><source src="${fileUrl}">Your browser does not support video.</video>`;
    } else if (['mp3','m4a','wav','ogg','flac'].includes(ext)) {
        body = `<div class="lb-fallback">
            <p style="font-weight:600;margin-bottom:1rem">${title}</p>
            <audio controls autoplay><source src="${fileUrl}">Your browser does not support audio.</audio>
        </div>`;
    } else if (['docx','doc','xlsx','xls','pptx','ppt','odt','ods','odp','rtf'].includes(ext)) {
        // Office docs — preview endpoint converts to PDF
        body = `<object data="${previewUrl}" type="application/pdf" class="lb-pdf">
            <iframe src="${previewUrl}" title="${title}"></iframe>
        </object>`;
    } else {
        body = `<div class="lb-fallback">
            <p>Preview not available for .${escapeHtml(ext)} files</p>
            <a href="${fileUrl}" download class="btn btn-primary">Download File</a>
        </div>`;
    }

    content.innerHTML = toolbar + body;
    overlay.classList.add('active');
}

function closeLightbox() {
    const overlay = document.getElementById('lightbox');
    const content = document.getElementById('lb-content');
    overlay.classList.remove('active');
    content.innerHTML = '';
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('lb-close').addEventListener('click', closeLightbox);
    document.getElementById('lightbox').addEventListener('click', e => {
        if (e.target === e.currentTarget) closeLightbox();
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeLightbox();
    });
});
