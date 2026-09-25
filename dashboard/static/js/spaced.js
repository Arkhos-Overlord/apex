/* APEX Dashboard — Spaced Repetition Schedule */

document.addEventListener('tab:spaced', async () => {
    const data = await fetchAPI(`/learner/${LEARNER_ID}/schedule?course_id=intro-python`);
    if (data) {
        const items = data.items.map(item => {
            const due = new Date(item.next_review) <= new Date();
            return {
                topic: item.topic,
                due_date: item.next_review,
                _date: new Date(item.next_review),
                status: due ? 'due' : 'upcoming',
                interval_days: item.interval_days,
                repetitions: 1,
                ease_factor: item.ease_factor,
            };
        });
        renderSpaced(items);
    }
});

function renderSpaced(data) {
    const container = document.getElementById('spaced-chart');
    container.innerHTML = '';

    // Summary stats
    const dueCount = data.filter(d => d.status === 'due').length;
    const summaryDiv = document.createElement('div');
    summaryDiv.style.cssText = 'display:flex;gap:24px;margin-bottom:24px';
    summaryDiv.innerHTML = `
        <div class="chart-container" style="flex:1;text-align:center">
            <div style="font-size:36px;font-weight:800;color:#ef4444">${dueCount}</div>
            <div style="color:#64748b;font-size:14px;margin-top:4px">Due Now</div>
        </div>
        <div class="chart-container" style="flex:1;text-align:center">
            <div style="font-size:36px;font-weight:800;color:#f59e0b">${data.filter(d => d.status === 'upcoming').length}</div>
            <div style="color:#64748b;font-size:14px;margin-top:4px">Upcoming</div>
        </div>
        <div class="chart-container" style="flex:1;text-align:center">
            <div style="font-size:36px;font-weight:800;color:#6366f1">${data.length}</div>
            <div style="color:#64748b;font-size:14px;margin-top:4px">Total Items</div>
        </div>
    `;
    container.appendChild(summaryDiv);

    // Timeline chart
    const margin = { top: 20, right: 40, bottom: 40, left: 120 };
    const width = container.clientWidth - margin.left - margin.right;
    const height = Math.max(300, data.length * 38 + margin.top + margin.bottom);

    const svg = d3.select(container)
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', height)
        .append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    const parseDate = d3.timeParse('%Y-%m-%d');
    const formatDate = d3.timeFormat('%b %d');

    data.forEach(d => { d._date = d._date; });

    const x = d3.scaleTime()
        .domain(d3.extent(data, d => d._date))
        .range([0, width]);
    const statusColor = { due: '#ef4444', upcoming: '#f59e0b', review: '#6366f1' };

    // Timeline dots
    svg.selectAll('.timeline-dot')
        .data(data)
        .join('circle')
        .attr('cx', d => x(d._date))
        .attr('cy', d => d.status === 'due' ? 40 : d.status === 'upcoming' ? 60 : 80)
        .attr('r', d => d.status === 'due' ? 8 : 6)
        .attr('fill', d => statusColor[d.status])
        .attr('stroke', '#0a0e17')
        .attr('stroke-width', 2);

    // Timeline line
    svg.append('line')
        .attr('x1', 0).attr('x2', width)
        .attr('y1', 50).attr('y2', 50)
        .attr('stroke', '#2a3a50').attr('stroke-width', 2);

    // Labels
    svg.selectAll('.sr-label')
        .data(data)
        .join('text')
        .attr('x', d => x(d._date))
        .attr('y', d => d.status === 'due' ? 95 : d.status === 'upcoming' ? 115 : 135)
        .attr('text-anchor', 'middle')
        .attr('fill', '#94a3b8')
        .attr('font-size', '10px')
        .text(d => d.topic.length > 14 ? d.topic.slice(0, 12) + '...' : d.topic);

    // Interval labels
    svg.selectAll('.interval-label')
        .data(data)
        .join('text')
        .attr('x', d => x(d._date))
        .attr('y', d => d.status === 'due' ? 110 : d.status === 'upcoming' ? 130 : 150)
        .attr('text-anchor', 'middle')
        .attr('fill', '#64748b')
        .attr('font-size', '9px')
        .text(d => `+${d.interval_days}d`);

    // Due indicator
    svg.selectAll('.due-badge')
        .data(data.filter(d => d.status === 'due'))
        .join('rect')
        .attr('x', d => x(d._date) - 20)
        .attr('y', 24)
        .attr('width', 40)
        .attr('height', 14)
        .attr('fill', '#ef4444')
        .attr('rx', 4)
        .attr('opacity', 0.8);

    svg.selectAll('.due-text')
        .data(data.filter(d => d.status === 'due'))
        .join('text')
        .attr('x', d => x(d._date))
        .attr('y', 34)
        .attr('text-anchor', 'middle')
        .attr('fill', '#fff')
        .attr('font-size', '8px')
        .attr('font-weight', '700')
        .text('DUE');

    // Table view
    const tableDiv = document.createElement('div');
    tableDiv.style.marginTop = '24px';
    data.forEach(d => {
        const row = document.createElement('div');
        row.className = 'spaced-row';
        row.innerHTML = `
            <span style="width:160px;color:#e2e8f0;font-weight:500">${d.topic}</span>
            <span style="width:80px;color:#94a3b8">${formatDate(d._date)}</span>
            <span style="width:60px;color:#64748b">+${d.interval_days}d</span>
            <span style="width:60px;color:#94a3b8">${d.repetitions} rev</span>
            <span style="width:80px">${d.ease_factor}x ease</span>
            <span class="spaced-status ${d.status}">${d.status}</span>
        `;
        tableDiv.appendChild(row);
    });
    container.appendChild(tableDiv);
}
