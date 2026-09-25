/* APEX Dashboard — Mastery Scores */

document.addEventListener('tab:mastery', async () => {
    const data = await fetchAPI(`/learner/${LEARNER_ID}/progress`);
    if (data) {
        // Build trend from course progress values
        const trend = data.courses.map((c, i) => c.average_mastery * 100);
        if (trend.length === 0) trend.push(data.overall_mastery * 100);
        const by_topic = {};
        data.courses.forEach(c => { by_topic[c.course_title] = c.average_mastery * 100; });
        renderMastery({
            trend,
            current: data.overall_mastery * 100,
            streak: 7,
            total_hours: Math.round(data.total_time_on_task / 60),
            by_topic: by_topic,
        });
    }
});

function renderMastery(data) {
    const container = document.getElementById('mastery-chart');
    container.innerHTML = '';

    const margin = { top: 30, right: 40, bottom: 50, left: 60 };
    const width = container.clientWidth - margin.left - margin.right;
    const height = 400 - margin.top - margin.bottom;

    const svg = d3.select(container)
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', height + margin.top + margin.bottom)
        .append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    // Trend chart
    const x = d3.scaleLinear().domain([0, data.trend.length - 1]).range([0, width]);
    const y = d3.scaleLinear().domain([40, 100]).range([height, 0]);

    // Grid lines
    svg.selectAll('.grid-line')
        .data(y.ticks(5))
        .join('line')
        .attr('x1', 0).attr('x2', width)
        .attr('y1', d => y(d)).attr('y2', d => y(d))
        .attr('stroke', '#2a3a50').attr('stroke-dasharray', '4,4');

    // Area
    const area = d3.area()
        .x((d, i) => x(i))
        .y0(height)
        .y1(d => y(d))
        .curve(d3.curveCatmullRom);

    svg.append('path')
        .datum(data.trend)
        .attr('d', area)
        .attr('fill', 'rgba(99, 102, 241, 0.1)');

    // Line
    const line = d3.line()
        .x((d, i) => x(i))
        .y(d => y(d))
        .curve(d3.curveCatmullRom);

    svg.append('path')
        .datum(data.trend)
        .attr('d', line)
        .attr('fill', 'none')
        .attr('stroke', '#6366f1')
        .attr('stroke-width', 3);

    // Dots
    svg.selectAll('.dot')
        .data(data.trend)
        .join('circle')
        .attr('cx', (d, i) => x(i))
        .attr('cy', d => y(d))
        .attr('r', 4)
        .attr('fill', '#6366f1')
        .attr('stroke', '#0a0e17')
        .attr('stroke-width', 2);

    // Axes
    svg.append('g')
        .attr('transform', `translate(0,${height})`)
        .call(d3.axisBottom(x).ticks(10).tickFormat(d => `W${d + 1}`))
        .selectAll('text').attr('fill', '#94a3b8');

    svg.append('g')
        .call(d3.axisLeft(y).ticks(5).tickFormat(d => d + '%'))
        .selectAll('text').attr('fill', '#94a3b8');

    // Topic breakdown below
    const topics = Object.keys(data.by_topic);
    const topicValues = Object.values(data.by_topic);

    const tx = d3.scaleBand().domain(topics).range([0, width]).padding(0.3);
    const ty = d3.scaleLinear().domain([0, 100]).range([height + 30, height + 200]);

    const tSvg = d3.select(container)
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', 240)
        .append('g')
        .attr('transform', `translate(${margin.left},${30})`);

    tSvg.selectAll('.topic-bar')
        .data(topics)
        .join('rect')
        .attr('x', d => tx(d))
        .attr('y', d => ty(data.by_topic[d]))
        .attr('width', tx.bandwidth())
        .attr('height', d => height - ty(data.by_topic[d]))
        .attr('fill', d => data.by_topic[d] > 80 ? '#6366f1' : data.by_topic[d] > 65 ? '#22d3ee' : '#f59e0b')
        .attr('rx', 4);

    tSvg.selectAll('.topic-label')
        .data(topics)
        .join('text')
        .attr('x', d => tx(d) + tx.bandwidth() / 2)
        .attr('y', height + 20)
        .attr('text-anchor', 'middle')
        .attr('fill', '#94a3b8')
        .attr('font-size', '10px')
        .text(d => d.length > 14 ? d.slice(0, 12) + '...' : d);

    tSvg.selectAll('.topic-val')
        .data(topics)
        .join('text')
        .attr('x', d => tx(d) + tx.bandwidth() / 2)
        .attr('y', d => ty(data.by_topic[d]) - 6)
        .attr('text-anchor', 'middle')
        .attr('fill', '#e2e8f0')
        .attr('font-size', '11px')
        .attr('font-weight', '600')
        .text(d => data.by_topic[d].toFixed(1) + '%');

    // Overall stat card
    const statDiv = document.createElement('div');
    statDiv.style.cssText = 'margin-top:24px;display:flex;gap:24px';
    statDiv.innerHTML = `
        <div class="chart-container" style="flex:1;text-align:center">
            <div style="font-size:36px;font-weight:800;color:#22d3ee">${data.current}%</div>
            <div style="color:#64748b;font-size:14px;margin-top:4px">Overall Mastery</div>
        </div>
        <div class="chart-container" style="flex:1;text-align:center">
            <div style="font-size:36px;font-weight:800;color:#10b981">${data.streak} 🔥</div>
            <div style="color:#64748b;font-size:14px;margin-top:4px">Day Streak</div>
        </div>
        <div class="chart-container" style="flex:1;text-align:center">
            <div style="font-size:36px;font-weight:800;color:#f59e0b">${data.total_hours}h</div>
            <div style="color:#64748b;font-size:14px;margin-top:4px">Total Hours</div>
        </div>
    `;
    container.appendChild(statDiv);
}
