/* APEX Dashboard — Knowledge Graph Visualization */

document.addEventListener('tab:knowledge', async () => {
    const data = await fetchAPI(`/learner/${LEARNER_ID}/knowledge-graph?course_id=intro-python`);
    if (data) renderKnowledgeGraph(data);
});

function renderKnowledgeGraph(data) {
    const container = document.getElementById('graph-chart');
    container.innerHTML = '';

    const width = container.clientWidth;
    const height = 480;

    const svg = d3.select(container)
        .append('svg')
        .attr('width', width)
        .attr('height', height);

    const colorMap = {
        language: '#6366f1',
        concept: '#22d3ee',
        framework: '#f59e0b',
        tool: '#10b981',
        format: '#ec4899',
    };

    const simulation = d3.forceSimulation(data.nodes)
        .force('link', d3.forceLink(data.links).id(d => d.id).distance(80))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(25));

    // Links
    const link = svg.append('g')
        .selectAll('line')
        .data(data.edges)
        .join('line')
        .attr('class', 'graph-link')
        .attr('stroke', '#6366f1')
        .attr('stroke-opacity', 0.4)
        .attr('stroke-width', d => d.strength * 3 + 1)
        .attr('marker-end', 'url(#arrow)');

    // Nodes
    const node = svg.append('g')
        .selectAll('g')
        .data(data.nodes)
        .join('g')
        .attr('class', 'graph-node')
        .call(d3.drag()
            .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
            .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }));

    node.append('circle')
        .attr('r', 18)
        .attr('fill', '#1a2332')
        .attr('stroke', '#6366f1')
        .attr('stroke-width', 2);

    node.append('text')
        .attr('dy', 4)
        .attr('text-anchor', 'middle')
        .attr('fill', '#e2e8f0')
        .attr('font-size', '10px')
        .attr('font-weight', '700')
        .text(d => d.id);

    // Tooltip on hover
    node.append('title').text(d => d.id);

    // Hover effects
    node.on('mouseover', function(event, d) {
        d3.select(this).select('circle').transition().duration(200).attr('r', 24).attr('stroke-width', 3);
        link.transition().duration(200)
            .attr('stroke-opacity', l => (l.source.id === d.id || l.target.id === d.id) ? 0.9 : 0.1);
        showTooltip(event, `${d.id} — ${data.edges.filter(e => e.source.id === d.id || e.target.id === d.id).length} connections`);
    }).on('mouseout', function() {
        d3.select(this).select('circle').transition().duration(200).attr('r', 18).attr('stroke-width', 2);
        link.transition().duration(200).attr('stroke-opacity', 0.4);
        hideTooltip();
    });

    simulation.on('tick', () => {
        link
            .attr('x1', d => d.source.x)
            .attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x)
            .attr('y2', d => d.target.y);

        node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    function dragstarted(event) { if (!event.active) simulation.alphaTarget(0.3).restart(); }
    function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
    function dragended(event) { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }
}
