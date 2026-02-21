/* Dashboard — stats cards, charts, recent requests */

const CHART_COLORS = [
    '#6c8cff','#4ade80','#fbbf24','#f87171','#fb923c',
    '#a78bfa','#22d3ee','#f472b6','#818cf8','#34d399'
];

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const [stats, recent] = await Promise.all([
            apiFetch('/api/stats'),
            apiFetch('/api/requests?limit=10&sort=newest'),
        ]);

        // Stat cards
        document.getElementById('total-requests').textContent = stats.total_requests.toLocaleString();
        document.getElementById('total-documents').textContent = stats.total_documents.toLocaleString();
        document.getElementById('total-departments').textContent = stats.total_departments.toLocaleString();

        // Status chart (doughnut)
        const statusCtx = document.getElementById('status-chart').getContext('2d');
        new Chart(statusCtx, {
            type: 'doughnut',
            data: {
                labels: stats.status_breakdown.map(s => s.status),
                datasets: [{
                    data: stats.status_breakdown.map(s => s.count),
                    backgroundColor: CHART_COLORS,
                    borderWidth: 0,
                }],
            },
            options: {
                plugins: { legend: { position: 'bottom', labels: { color: '#8b8fa3', font: { size: 11 } } } },
                cutout: '60%',
            },
        });

        // Month chart (line)
        const monthCtx = document.getElementById('month-chart').getContext('2d');
        new Chart(monthCtx, {
            type: 'line',
            data: {
                labels: stats.requests_by_month.map(m => m.month),
                datasets: [{
                    label: 'Requests',
                    data: stats.requests_by_month.map(m => m.count),
                    borderColor: '#6c8cff',
                    backgroundColor: 'rgba(108,140,255,.1)',
                    fill: true,
                    tension: .3,
                    pointRadius: 2,
                }],
            },
            options: {
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: '#8b8fa3', font: { size: 10 }, maxRotation: 45 }, grid: { color: 'rgba(42,45,58,.5)' } },
                    y: { ticks: { color: '#8b8fa3' }, grid: { color: 'rgba(42,45,58,.5)' }, beginAtZero: true },
                },
            },
        });

        // Recent requests table
        const tbody = document.getElementById('recent-table');
        tbody.innerHTML = recent.results.map(r => `
            <tr onclick="location.href='/requests/${encodeURIComponent(r.pretty_id)}'">
                <td><strong>${escapeHtml(r.pretty_id)}</strong></td>
                <td>${statusPill(r.request_state)}</td>
                <td>${escapeHtml(truncate(r.request_text, 80))}</td>
                <td>${escapeHtml(r.department_names || '—')}</td>
                <td style="white-space:nowrap">${formatDate(r.request_date)}</td>
                <td class="text-right">${r.doc_count}</td>
            </tr>
        `).join('');
    } catch (err) {
        console.error(err);
        document.querySelector('.container').innerHTML += `<div class="error">Failed to load dashboard data: ${escapeHtml(err.message)}</div>`;
    }
});
