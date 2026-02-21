/* Department list + detail page logic */

document.addEventListener('DOMContentLoaded', async () => {
    const tbody = document.getElementById('dept-table');
    try {
        const depts = await apiFetch('/api/departments');
        tbody.innerHTML = depts.map(d => `
            <tr onclick="location.href='/departments/${d.id}'">
                <td><strong>${escapeHtml(d.name || 'Unknown')}</strong></td>
                <td class="text-right">${d.request_count}</td>
            </tr>
        `).join('');
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="2" class="error">${escapeHtml(err.message)}</td></tr>`;
    }
});
