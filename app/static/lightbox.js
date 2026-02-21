/* Lightbox — modal viewer for documents (PDF, images, video, audio) */

function openLightbox(doc) {
    const overlay = document.getElementById('lightbox');
    const content = document.getElementById('lb-content');
    const ext = (doc.file_extension || '').toLowerCase();

    let html = '';
    const fileUrl = `/api/documents/${doc.id}/file`;

    if (ext === 'pdf') {
        html = `<iframe src="${fileUrl}" title="${escapeHtml(doc.title || 'Document')}"></iframe>`;
    } else if (['jpg','jpeg','png','gif','bmp','webp','tif','tiff'].includes(ext)) {
        html = `<img src="${fileUrl}" alt="${escapeHtml(doc.title || 'Image')}">`;
    } else if (['mp4','webm','mov','avi'].includes(ext)) {
        html = `<video controls autoplay><source src="${fileUrl}">Your browser does not support video.</video>`;
    } else if (['mp3','m4a','wav','ogg','flac'].includes(ext)) {
        html = `<div style="padding:2rem;text-align:center">
            <p style="margin-bottom:1rem;font-weight:600">${escapeHtml(doc.title || 'Audio')}</p>
            <audio controls autoplay><source src="${fileUrl}">Your browser does not support audio.</audio>
        </div>`;
    } else {
        // Unsupported — offer download
        html = `<div style="padding:2rem;text-align:center">
            <p style="margin-bottom:1rem">Preview not available for .${escapeHtml(ext)} files</p>
            <a href="${fileUrl}" download class="btn btn-primary">Download File</a>
        </div>`;
    }

    content.innerHTML = html;
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
