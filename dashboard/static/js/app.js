const STATE = { charts: {}, learner: null, courses: null };

document.querySelectorAll('.sidebar nav a').forEach(a => {
    a.addEventListener('click', () => {
        document.querySelectorAll('.sidebar nav a').forEach(x => x.classList.remove('active'));
        a.classList.add('active');
        const tab = a.dataset.tab;
        document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
        document.getElementById('panel-' + tab).classList.add('active');
        const titles = {dashboard:'Dashboard',progress:'Progress',knowledge:'Knowledge Graph',courses:'Courses',mastery:'Mastery',spaced:'Spaced Repetition'};
        document.getElementById('page-title').textContent = titles[tab] || tab;
        loadTab(tab);
    });
});

async function api(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
    return res.json();
}

async function loadTab(tab) {
    try {
        if (['dashboard','progress','mastery','spaced'].includes(tab)) {
            const [progress, courses, schedule] = await Promise.all([
                api('/api/learner/alice/progress'), api('/api/courses'),
                api('/api/learner/alice/schedule?course_id=intro-python')
            ]);
            STATE.learner = progress; STATE.courses = courses;
            if (tab === 'dashboard') renderDashboard(progress, courses, schedule);
            if (tab === 'progress') renderProgress(progress);
            if (tab === 'mastery') renderMastery(progress);
            if (tab === 'spaced') renderSpaced(schedule);
        }
        if (tab === 'courses') {
            const courses = STATE.courses || await api('/api/courses');
            STATE.courses = courses;
            renderCourses(courses);
        }
        if (tab === 'knowledge') renderKnowledgeGraph();
    } catch(e) { console.error('Load error:', e); }
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function renderDashboard(progress, courses, schedule) {
    const mc = progress.courses || [];
    let totalTopics = 0;
    mc.forEach(c => { totalTopics += c.topics_covered || 0; });
    const allScores = mc.map(c => Math.round((c.average_mastery || 0) * 100));
    const avg = allScores.length ? Math.round(allScores.reduce((a,b)=>a+b,0)/allScores.length) : 0;
    document.getElementById('stat-courses').textContent = courses.courses.length;
    document.getElementById('stat-topics').textContent = totalTopics;
    document.getElementById('stat-exercises').textContent = totalTopics;
    document.getElementById('stat-score').textContent = avg + '%';
    document.getElementById('overall-mastery').textContent = avg;
    const totalHours = Math.round((progress.total_time_on_task || 0) / 60 * 10) / 10;
    document.getElementById('hours').textContent = totalHours;
    document.getElementById('streak').textContent = '7d';
    renderActivityChart(); renderOverviewChart(progress);
}

function renderActivityChart() {
    const ctx = document.getElementById('activity-chart');
    if (STATE.charts.activity) STATE.charts.activity.destroy();
    STATE.charts.activity = new Chart(ctx, {
        type: 'bar',
        data: { labels: ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'], datasets: [{
            label: 'Hours', data: [2.5,3.1,1.8,4.2,2.9,3.5,2.1],
            backgroundColor: 'rgba(99,102,241,0.6)', borderColor: 'rgba(99,102,241,1)', borderWidth: 1, borderRadius: 6
        }]},
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true, grid: { color: 'rgba(42,53,72,0.5)' }, ticks: { color: '#94a3b8' } },
            x: { grid: { display: false }, ticks: { color: '#94a3b8' } } } }
    });
}

function renderOverviewChart(progress) {
    const ctx = document.getElementById('overview-chart');
    if (STATE.charts.overview) STATE.charts.overview.destroy();
    const mc = progress.courses || [];
    const names = mc.map(c => (c.course_title || '').split(' ').slice(0,2).join(' '));
    const scores = mc.map(c => Math.round((c.average_mastery || 0) * 100));
    STATE.charts.overview = new Chart(ctx, {
        type: 'radar',
        data: { labels: names, datasets: [{ label: 'Completion %', data: scores,
            backgroundColor: 'rgba(99,102,241,0.2)', borderColor: 'rgba(99,102,241,1)', borderWidth: 2,
            pointBackgroundColor: 'rgba(99,102,241,1)', pointRadius: 4 }]},
        options: { responsive: true, maintainAspectRatio: false,
            scales: { r: { beginAtZero: true, max: 100, grid: { color: 'rgba(42,53,72,0.5)' }, ticks: { color: '#94a3b8', backdropColor: 'transparent' }, angleLines: { color: 'rgba(42,53,72,0.5)' } } } }
    });
}

function renderProgress(progress) {
    const ctx = document.getElementById('heatmap-chart');
    if (STATE.charts.heatmap) STATE.charts.heatmap.destroy();
    const firstCourse = (progress.courses && progress.courses[0] && progress.courses[0].course_id) || 'intro-python';
    api('/api/learner/alice/heatmap?course_id=' + firstCourse)
        .then(data => data.data || [])
        .then(heatmapData => {
            // Heatmap rows are {date, topics: {topic: minutes}} — sum per day
            const vals = heatmapData.map(r => Object.values(r.topics || {}).reduce((a,b)=>a+b, 0));
            const labels = heatmapData.map(r => (r.date || '').slice(5));
            STATE.charts.heatmap = new Chart(ctx, {
                type: 'bar', data: { labels: labels, datasets: [{ label: 'Minutes', data: vals,
                    backgroundColor: vals.map(v => v>60?'rgba(99,102,241,0.8)':v>30?'rgba(139,92,246,0.6)':'rgba(42,53,72,0.5)'), borderRadius: 3 }]},
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
                    scales: { y: { beginAtZero: true, grid: { color: 'rgba(42,53,72,0.5)' }, ticks: { color: '#94a3b8' } },
                    x: { grid: { display: false }, ticks: { color: '#64748b', maxTicksLimit: 10 } } } }
            });
        })
        .catch(e => console.error('Heatmap load failed:', e));
}

function renderMastery(progress) {
    const container = document.getElementById('mastery-bars');
    const firstCourse = (progress.courses && progress.courses[0] && progress.courses[0].course_id) || 'intro-python';
    if (container) {
        container.textContent = '';
        api('/api/learner/alice/mastery?course_id=' + firstCourse)
            .then(data => {
                const colors = ['#6366f1','#8b5cf6','#22c55e','#3b82f6','#f59e0b','#ef4444','#06b6d4','#ec4899'];
                (data.topics || []).forEach((t, i) => {
                    const color = colors[i % colors.length];
                    const row = el('div', 'mastery-item');
                    const label = el('span', 'mastery-label', t.topic);
                    const barWrap = el('div', 'mastery-bar');
                    const fill = el('div', 'mastery-fill');
                    fill.style.width = Math.round(t.score) + '%';
                    fill.style.background = color;
                    barWrap.appendChild(fill);
                    const value = el('span', 'mastery-value', Math.round(t.score) + '%');
                    value.style.color = color;
                    row.append(label, barWrap, value);
                    container.appendChild(row);
                });
            })
            .catch(e => console.error('Mastery load failed:', e));
    }
    const ctx = document.getElementById('mastery-chart');
    if (STATE.charts.mastery) STATE.charts.mastery.destroy();
    const mc = progress.courses || [];
    const scores = mc.map(c => Math.round((c.average_mastery || 0) * 100));
    const labels = mc.map(c => (c.course_title || c.course_id || 'Course').split(' ').slice(0, 2).join(' '));
    STATE.charts.mastery = new Chart(ctx, {
        type: 'line',
        data: { labels: labels.length ? labels : ['—'], datasets: [
            { label: 'Avg mastery %', data: scores.length ? scores : [0], borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)', fill: true, tension: 0.4 }
        ]},
        options: { responsive: true, maintainAspectRatio: false,
            scales: { y: { beginAtZero: true, max: 100, grid: { color: 'rgba(42,53,72,0.5)' }, ticks: { color: '#94a3b8' } },
            x: { grid: { display: false }, ticks: { color: '#94a3b8' } } },
            plugins: { legend: { labels: { color: '#94a3b8' } } }
        }
    });
}

function renderSpaced(schedule) {
    const container = document.getElementById('spaced-list');
    if (!container) return;
    container.textContent = '';
    const items = schedule.items || [];
    if (!items.length) {
        container.appendChild(el('div', null, 'No reviews scheduled. Keep learning!'));
        return;
    }
    items.forEach(item => {
        const row = el('div', 'schedule-item');
        row.appendChild(el('span', 'topic-name', item.topic || 'Unknown'));
        row.appendChild(el('span', 'interval', (item.interval_days ?? '?') + 'd'));
        row.appendChild(el('span', 'due-date', 'Due ' + (item.next_review || 'soon')));
        container.appendChild(row);
    });
}

function renderCourses(courses) {
    const container = document.getElementById('courses-list');
    if (!container) return;
    container.textContent = '';
    (courses.courses || []).forEach(c => {
        const card = el('div', 'course-item');
        const title = el('h4', null, c.title || c.id);
        const meta = el('p', 'meta', `${c.description || ''} · ${c.duration_weeks || '?'} weeks · ${c.module_count || '?'} modules`);
        const barWrap = el('div', 'progress-bar');
        const fill = el('div', 'progress-fill');
        fill.style.width = '0%';
        barWrap.appendChild(fill);
        card.append(title, meta, barWrap);
        container.appendChild(card);
        // Fill in real completion from the per-course endpoint
        api('/api/course/' + c.id + '/completion')
            .then(data => { fill.style.width = (data.completion_percent || 0) + '%'; })
            .catch(() => { fill.style.width = '0%'; });
    });
}

function drawGraph(canvas, nodes, edges) {
    const ctx = canvas.getContext('2d');
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = 400;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!nodes.length) return;
    const cx = canvas.width/2, cy = canvas.height/2;
    const r = Math.min(cx,cy)*0.6;
    const positions = new Map(nodes.map((n, i) => [n, { x: cx+Math.cos(i/nodes.length*Math.PI*2)*r, y: cy+Math.sin(i/nodes.length*Math.PI*2)*r }]));
    ctx.strokeStyle = 'rgba(99,102,241,0.3)'; ctx.lineWidth = 2;
    edges.forEach(([a,b]) => {
        const pa = positions.get(a), pb = positions.get(b);
        if (!pa || !pb) return;
        ctx.beginPath(); ctx.moveTo(pa.x,pa.y); ctx.lineTo(pb.x,pb.y); ctx.stroke();
    });
    const colors = ['#6366f1','#8b5cf6','#22c55e','#3b82f6','#f59e0b','#ef4444','#06b6d4','#ec4899'];
    nodes.forEach((n, i) => {
        const p = positions.get(n);
        ctx.beginPath(); ctx.arc(p.x,p.y,20,0,Math.PI*2); ctx.fillStyle=colors[i % colors.length]; ctx.fill();
        ctx.fillStyle='#fff'; ctx.font='11px sans-serif'; ctx.textAlign='center'; ctx.textBaseline='middle';
        ctx.fillText(n,p.x,p.y);
    });
}

function renderKnowledgeGraph() {
    const canvas = document.getElementById('knowledge-graph-canvas');
    if (!canvas) return;
    api('/api/learner/alice/knowledge-graph?course_id=intro-python')
        .then(data => {
            const nodes = (data.nodes || []).map(n => n.name || n.id);
            const edges = (data.edges || []).map(e => [e.source, e.target]);
            drawGraph(canvas, nodes, edges);
        })
        .catch(e => {
            console.error('Knowledge graph load failed:', e);
            drawGraph(canvas, ['Variables','Loops','Functions','Lists','Dicts'], [['variables','loops'],['loops','functions'],['functions','lists'],['lists','dicts']]);
        });
}

loadTab('dashboard');
