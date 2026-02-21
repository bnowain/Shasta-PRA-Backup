/* Analytics page — charts and tables */

const COLORS = [
    '#6c8cff','#4ade80','#fbbf24','#f87171','#fb923c',
    '#a78bfa','#22d3ee','#f472b6','#818cf8','#34d399',
    '#facc15','#ef4444','#3b82f6','#10b981','#8b5cf6'
];

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const [stats, topDocs] = await Promise.all([
            apiFetch('/api/stats'),
            apiFetch('/api/requests?sort=newest&limit=10'),
        ]);

        // Department workload bar chart
        const deptData = stats.department_breakdown.slice(0, 15);
        new Chart(document.getElementById('dept-chart').getContext('2d'), {
            type: 'bar',
            data: {
                labels: deptData.map(d => d.department.length > 25 ? d.department.slice(0, 25) + '...' : d.department),
                datasets: [{
                    label: 'Requests',
                    data: deptData.map(d => d.count),
                    backgroundColor: COLORS,
                    borderWidth: 0,
                }],
            },
            options: {
                indexAxis: 'y',
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: '#8b8fa3' }, grid: { color: 'rgba(42,45,58,.5)' } },
                    y: { ticks: { color: '#8b8fa3', font: { size: 11 } }, grid: { display: false } },
                },
            },
        });

        // Status pie chart
        new Chart(document.getElementById('status-pie').getContext('2d'), {
            type: 'pie',
            data: {
                labels: stats.status_breakdown.map(s => s.status),
                datasets: [{
                    data: stats.status_breakdown.map(s => s.count),
                    backgroundColor: COLORS,
                    borderWidth: 0,
                }],
            },
            options: {
                plugins: { legend: { position: 'bottom', labels: { color: '#8b8fa3', font: { size: 11 } } } },
            },
        });

        // Time chart (line)
        new Chart(document.getElementById('time-chart').getContext('2d'), {
            type: 'bar',
            data: {
                labels: stats.requests_by_month.map(m => m.month),
                datasets: [{
                    label: 'Requests',
                    data: stats.requests_by_month.map(m => m.count),
                    backgroundColor: 'rgba(108,140,255,.6)',
                    borderColor: '#6c8cff',
                    borderWidth: 1,
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

        // POC table — derive from requests data
        const pocResp = await apiFetch('/api/requests?limit=200&sort=newest');
        const pocMap = {};
        pocResp.results.forEach(r => {
            if (r.poc_name) {
                pocMap[r.poc_name] = (pocMap[r.poc_name] || 0) + 1;
            }
        });
        const pocList = Object.entries(pocMap).sort((a, b) => b[1] - a[1]).slice(0, 10);
        document.getElementById('poc-table-wrap').innerHTML = `
            <table>
                <thead><tr><th>POC</th><th class="text-right">Requests</th></tr></thead>
                <tbody>${pocList.map(([name, count]) => `
                    <tr style="cursor:default"><td>${escapeHtml(name)}</td><td class="text-right">${count}</td></tr>
                `).join('')}</tbody>
            </table>`;

        // Most documented requests
        const docResp = await apiFetch('/api/requests?limit=200&sort=newest');
        const withDocs = docResp.results.filter(r => r.doc_count > 0).sort((a, b) => b.doc_count - a.doc_count).slice(0, 10);
        document.getElementById('topdocs-table-wrap').innerHTML = `
            <table>
                <thead><tr><th>Request</th><th class="text-right">Documents</th></tr></thead>
                <tbody>${withDocs.map(r => `
                    <tr onclick="location.href='/requests/${encodeURIComponent(r.pretty_id)}'">
                        <td><strong>${escapeHtml(r.pretty_id)}</strong> — ${escapeHtml(truncate(r.request_text, 60))}</td>
                        <td class="text-right">${r.doc_count}</td>
                    </tr>
                `).join('')}</tbody>
            </table>`;

    } catch (err) {
        console.error(err);
        document.querySelector('.container').innerHTML += `<div class="error">Failed to load analytics: ${escapeHtml(err.message)}</div>`;
    }
});
