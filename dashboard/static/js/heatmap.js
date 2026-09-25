/* APEX Dashboard — Heatmap & Topic Charts */

document.addEventListener('tab:heatmap', async () => {
    const [heatmapData, progressData] = await Promise.all([
        fetchAPI(`/learner/${LEARNER_ID}/heatmap?course_id=intro-python`),
        fetchAPI(`/learner/${LEARNER_ID}/progress`),
    ]);
    if (heatmapData) renderHeatmap(heatmapData.data);
    if (progressData && progressData.courses.length > 0) {
        const c = progressData.courses[0];
        renderTopics(c.course_title, c.average_mastery * 100);
    }
});

function renderHeatmap(data) {
    const container = document.getElementById('heatmap-chart');
    container.innerHTML = '';

    const margin = { top: 30, right: 20, bottom: 40, left: 120 };
    const width = container.clientWidth - margin.left - margin.right;
    const height = 300 - margin.top - margin.bottom;

    const svg = d3.select(container)
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', height + margin.top + margin.bottom)
        .append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    // data is array of { date, topics: { topicName: minutes } }
    const allTopics = [...new Set(data.flatMap(d => Object.keys(d.topics)))];
    const dates = data.map(d => d.date);

    const x0 = d3.scaleBand().domain(dates).range([0, width]).padding(0.04);
    const x1 = d3.scaleBand().domain(allTopics).range([0, x0.bandwidth()]).padding(0.08);
    const y = d3.scaleBand().domain(allTopics).range([0, height]).padding(0.15);

    const allVals = data.flatMap(d => Object.values(d.topics));
    const maxTime = d3.max(allVals) || 90;
    const color = d3.scaleSequential()
        .domain([0, maxTime])
        .interpolator(d3.interpolateRgbBasis(['#1a2332', '#3b82f6', '#6366f1', '#22d3ee']));

    // Cells
    data.forEach(row => {
        allTopics.forEach(topic => {
            const val = row.topics[topic] ?? 0;
            svg.append('rect')
                .attr('class', 'heatmap-cell')
                .attr('x', x0(row.date) + x1(topic))
                .attr('y', y(topic))
                .attr('width', x1.bandwidth())
                .attr('height', y.bandwidth())
                .attr('fill', val > 0 ? color(val) : 'var(--bg-primary)')
                .attr('opacity', val > 0 ? 0.9 : 0.3)
                .on('mouseover', function(event) {
                    showTooltip(event, `${topic}: ${val.toFixed(1)} min on ${row.date}`);
                })
                .on('mouseout', hideTooltip);
        });
    });

    // Week labels (Y axis)
    svg.selectAll('.heatmap-label')
        .data(allTopics)
        .join('text')
        .attr('class', 'heatmap-label')
        .attr('x', -8)
        .attr('y', d => y(d) + y.bandwidth() / 2 + 4)
        .attr('text-anchor', 'end')
        .text(d => d);

    // Day labels (X axis) — show first letter of each date
    dates.forEach((d, i) => {
        if (i % 7 === 0) {
            svg.append('text')
                .attr('x', x0(d) + x0.bandwidth() / 2)
                .attr('y', -8)
                .attr('text-anchor', 'middle')
                .attr('fill', '#94a3b8')
                .attr('font-size', '11px')
                .text(new Date(d).toLocaleDateString('en', { month: 'short', day: 'numeric' }));
        }
    });
}

function renderTopics(label, masteryPct) {
    const container = document.getElementById('topic-chart');
    container.innerHTML = '';

    const margin = { top: 20, right: 60, bottom: 20, left: 140 };
    const width = container.clientWidth - margin.left - margin.right;
    const height = 80 + margin.top + margin.bottom;

    const svg = d3.select(container)
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', height)
        .append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    // Single horizontal bar showing mastery for the course
    const x = d3.scaleLinear().domain([0, 100]).range([0, width]);

    // Background bar
    svg.append('rect')
        .attr('x', 0).attr('y', 10)
        .attr('width', width).attr('height', 28)
        .attr('fill', '#1a2332').attr('rx', 4);

    // Mastery fill
    svg.append('rect')
        .attr('class', 'topic-bar')
        .attr('x', 0).attr('y', 10)
        .attr('width', x(masteryPct)).attr('height', 28)
        .attr('fill', masteryPct > 80 ? '#6366f1' : masteryPct > 65 ? '#22d3ee' : '#f59e0b')
        .attr('rx', 4);

    // Label
    svg.append('text')
        .attr('x', -8).attr('y', 28)
        .attr('text-anchor', 'end')
        .attr('fill', '#94a3b8').attr('font-size', '12px')
        .text(label);

    // Value
    svg.append('text')
        .attr('x', x(masteryPct) + 6).attr('y', 28)
        .attr('fill', '#e2e8f0').attr('font-size', '11px').attr('font-weight', '600')
        .text(masteryPct.toFixed(1) + '%');

    // Gradient legend
    const legendW = 100;
    const lg = svg.append('defs').append('linearGradient').attr('id', 'topic-grad').attr('x1', '0').attr('x2', '1');
    lg.append('stop').attr('offset', '0%').attr('stop-color', '#1a2332');
    lg.append('stop').attr('offset', '50%').attr('stop-color', '#3b82f6');
    lg.append('stop').attr('offset', '100%').attr('stop-color', '#22d3ee');

    svg.append('rect')
        .attr('x', width - legendW).attr('y', 10)
        .attr('width', legendW).attr('height', 28)
        .attr('fill', 'url(#topic-grad)').attr('rx', 4).attr('opacity', 0.3);
}
