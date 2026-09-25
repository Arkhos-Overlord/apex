/* APEX Dashboard — Course Navigator */

document.addEventListener('tab:courses', async () => {
    const [coursesData] = await Promise.all([
        fetchAPI('/courses'),
    ]);
    if (coursesData) {
        renderCourseList(coursesData.courses);
        const treeRoot = {
            name: "Courses",
            children: coursesData.courses.map(c => ({
                name: c.title,
                id: c.id,
                module_count: c.module_count,
                completed: c.id === 'intro-python' ? true : false,
            }))
        };
        renderCourseTree(treeRoot);
    }
});

function renderCourseList(courses) {
    const container = document.getElementById('courses-list');
    container.innerHTML = '<h3 style="color:#94a3b8;margin-bottom:16px">All Courses</h3>';

    const colorMap = {
        'Beginner': '#10b981',
        'Intermediate': '#22d3ee',
        'Advanced': '#ef4444',
    };

    const icons = {
        'Introduction to Python': '🐍',
        'Data Science Fundamentals': '📊',
        'Modern Web Development': '🌐',
        'Machine Learning Deep Dive': '🤖',
    };

    courses.forEach(c => {
        const card = document.createElement('div');
        card.className = 'course-card';
        const fillColor = colorMap['Intermediate'] || '#6366f1';
        const icon = icons[c.title] || '📘';
        // Simulate progress per course
        const progressMap = { 'Introduction to Python': 67, 'Data Science Fundamentals': 45, 'Modern Web Development': 32, 'Machine Learning Deep Dive': 18 };
        const progress = progressMap[c.title] || 0;
        card.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-size:20px;margin-right:12px">${icon}</span>
                <div style="flex:1">
                    <div style="font-weight:600;font-size:15px">${c.title}</div>
                    <div style="color:#64748b;font-size:12px;margin-top:2px">${c.duration_weeks} weeks · ${c.module_count} modules</div>
                </div>
                <span style="color:${fillColor};font-weight:700;font-size:18px">${progress}%</span>
            </div>
            <div class="course-progress-bar">
                <div class="course-progress-fill" style="width:${progress}%;background:${fillColor}"></div>
            </div>
        `;
        container.appendChild(card);
    });
}

function renderCourseTree(treeData) {
    const container = document.getElementById('course-tree');
    container.innerHTML = '';

    const margin = { top: 20, right: 40, bottom: 20, left: 40 };
    const width = container.clientWidth - margin.left - margin.right;

    const root = d3.hierarchy(treeData);
    const treeLayout = d3.tree().size([400, Math.max(300, width)]);
    treeLayout(root);

    // Rotate so Y is vertical
    root.descendants().forEach(d => {
        const tmp = d.x;
        d.x = d.y;
        d.y = tmp;
    });

    const svgH = Math.max(400, root.height * 80 + margin.top + margin.bottom);
    const svg = d3.select(container)
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', svgH)
        .append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    // Links
    svg.selectAll('.tree-link')
        .data(root.links())
        .join('path')
        .attr('d', d3.linkVertical().x(d => d.x).y(d => d.y))
        .attr('fill', 'none')
        .attr('stroke', '#2a3a50')
        .attr('stroke-width', 2);

    // Nodes
    const node = svg.selectAll('.tree-node')
        .data(root.descendants())
        .join('g')
        .attr('class', 'tree-node')
        .attr('transform', d => `translate(${d.x},${d.y})`)
        .on('click', (e, d) => {
            if (d.data.id) window.location.href = `/course/${d.data.id}`;
        })
        .on('mouseover', function(event, d) {
            d3.select(this).select('rect').attr('stroke', '#6366f1').attr('stroke-width', 2);
            showTooltip(event, d.data.name + (d.data.module_count ? ` · ${d.data.module_count} modules` : ''));
        })
        .on('mouseout', function() {
            d3.select(this).select('rect').attr('stroke', '#2a3a50').attr('stroke-width', 1);
            hideTooltip();
        });

    node.append('rect')
        .attr('width', d => d.data.children ? 130 : 110)
        .attr('height', 28)
        .attr('x', d => d.data.children ? -65 : -55)
        .attr('ry', 6)
        .attr('fill', d => {
            if (d.data.completed) return '#10b981';
            if (d.data.children) return '#3b82f6';
            return '#1a2332';
        })
        .attr('stroke', '#2a3a50')
        .attr('stroke-width', 1);

    node.append('text')
        .attr('dy', 4)
        .attr('text-anchor', 'middle')
        .attr('fill', '#fff')
        .attr('font-size', '11px')
        .attr('font-weight', '500')
        .text(d => {
            const name = d.data.name;
            return name.length > 18 ? name.slice(0, 16) + '...' : name;
        });
}
