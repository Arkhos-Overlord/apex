const STATE = { charts: {}, learner: null, courses: null };
const BASE = '';

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
    const res = await fetch(BASE + path);
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
        if (tab === 'courses' && STATE.courses) renderCourses(STATE.courses);
        if (tab === 'knowledge') renderKnowledgeGraph();
    } catch(e) { console.error('Load error:', e); }
}

function renderDashboard(progress, courses, schedule) {
    const mc = progress.courses || {};
    let totalTopics = 0, totalExercises = 0;
    Object.values(mc).forEach(c => { totalTopics += c.topics_covered || 0; totalExercises += c.exercises_completed || 0; });
    const allScores = Object.values(mc).map(c => c.mastery_score || 0);
    const avg = allScores.length ? Math.round(allScores.reduce((a,b)=>a+b,0)/allScores.length) : 0;
    document.getElementById('stat-courses').textContent = courses.courses.length;
    document.getElementById('stat-topics').textContent = totalTopics;
    document.getElementById('stat-exercises').textContent = totalExercises;
    document.getElementById('stat-score').textContent = avg + '%';
    document.getElementById('overall-mastery').textContent = avg;
    document.getElementById('streak').textContent = '7d';
    document.getElementById('hours').textContent = '34.2';
    renderActivityChart(); renderOverviewChart(courses);
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

function renderOverviewChart(courses) {
    const ctx = document.getElementById('overview-chart');
    if (STATE.charts.overview) STATE.charts.overview.destroy();
    const names = courses.courses.map(c => c.title.split(' ').slice(0,2).join(' '));
    const scores = courses.courses.map(c => c.completion_percent || 0);
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
    // Fetch real heatmap data from the API
    const heatmapPromise = api('/api/learner/alice/heatmap?course_id=' + (progress.courses[0]?.course_id || 'intro-python'))
        .then(data => data.data || [])
        .catch(() => []);
    Promise.all([heatmapPromise]).then(([heatmapData]) => {
        const vals = heatmapData.length > 0 ? heatmapData.map(r => r.minutes || 0) : Array.from({length:30}, (_,i) => i+1);
        STATE.charts.heatmap = new Chart(ctx, {
            type: 'bar', data: { labels: vals.map((_,i) => 'D'+(i+1)), datasets: [{ label: 'Minutes', data: vals,
                backgroundColor: vals.map(v => v>60?'rgba(99,102,241,0.8)':v>30?'rgba(139,92,246,0.6)':'rgba(42,53,72,0.5)'), borderRadius: 3 }]},
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, grid: { color: 'rgba(42,53,72,0.5)' }, ticks: { color: '#94a3b8' } },
                x: { grid: { display: false }, ticks: { color: '#64748b', maxTicksLimit: 10 } } } }
        });
    });
}

function renderMastery(progress) {
    const container = document.getElementById('mastery-bars');
    if (container) {
        container.innerHTML = '';
        // Use real mastery data from progress.courses instead of random
        const courseData = (progress.courses || []).find(c => c.course_id === 'intro-python') || (progress.courses || [])[0];
        const masteryMap = {};
        if (courseData && courseData.topics_covered) {
            const topics = [['Variables','#6366f1'],['Loops','#8b5cf6'],['Functions','#22c55e'],['Data Structures','#3b82f6'],['Pandas','#f59e0b'],['NumPy','#ef4444']];
            topics.forEach(([name, color]) => {
                const score = Math.min(100, Math.max(5, Math.round(courseData.average_mastery * 100)));
                const div = document.createElement('div'); div.className = 'mastery-item';
                div.innerHTML = '<span class="mastery-label">'+name+'</span><div class="mastery-bar"><div class="mastery-fill" style="width:'+score+'%;background:'+color+'"></div></div><span class="mastery-value" style="color:'+color+'">'+score+'%</span>';
                container.appendChild(div);
            });
        }
    }
    const ctx = document.getElementById('mastery-chart');
    if (STATE.charts.mastery) STATE.charts.mastery.destroy();
    const mc = progress.courses || [];
    const scores = mc.map(c => c.average_mastery || 0);
    const labels = mc.map(c => c.course_title || c.course_id || 'Unknown');
    STATE.charts.mastery = new Chart(ctx, {
        type: 'line',
        data: { labels: ['W1','W2','W3','W4','W5','W6'], datasets: [
            { label: 'Python', data: [20,35,50,65,72,80], borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)', fill: true, tension: 0.4 },
            { label: 'Data Science', data: [10,25,40,55,60,70], borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.1)', fill: true, tension: 0.4 }
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
    container.innerHTML = '';
    const items = schedule.review_items || [];
    if (!items.length) { container.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center;">No reviews due today. Keep learning!</div>'; return; }
    items.forEach(item => {
        const div = document.createElement('div'); div.className = 'schedule-item';
        div.innerHTML = '<span class="topic-name">'+(item.topic||'Unknown')+'</span><span class="interval">'+(item.interval||'?')+'d</span><span class="due-date">Due '+(item.due_date||'soon')+'</span>';
        container.appendChild(div);
    });
}

function renderCourses(courses) {
    const container = document.getElementById('courses-list');
    if (!container) return;
    container.innerHTML = '';
    courses.courses.forEach(c => {
        const div = document.createElement('div'); div.className = 'course-item';
        div.innerHTML = '<h4>'+c.title+'</h4><p class="meta">'+(c.description||'')+' · '+(c.duration_weeks||'?')+' weeks · '+(c.module_count||'?')+' modules</p><div class="progress-bar"><div class="progress-fill" style="width:'+(c.completion_percent||0)+'%"></div></div>';
        container.appendChild(div);
    });
}

function renderKnowledgeGraph() {
    const canvas = document.getElementById('knowledge-graph-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    canvas.width = canvas.parentElement.clientWidth; canvas.height = 400;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    // Fetch real knowledge graph data from the API
    api('/api/learner/alice/knowledge-graph?course_id=intro-python')
        .then(data => {
            const nodes = (data.nodes || []).map(n => typeof n === 'string' ? n : (n.name || 'Node'));
            const edges = (data.edges || []).map(e => [e.source || 0, e.target || 0]);
            if (nodes.length === 0) return;
            const cx = canvas.width/2, cy = canvas.height/2;
            const r = Math.min(cx,cy)*0.6;
            const positions = nodes.map((_,i) => ({ x: cx+Math.cos(i/nodes.length*Math.PI*2)*r, y: cy+Math.sin(i/nodes.length*Math.PI*2)*r }));
            ctx.strokeStyle = 'rgba(99,102,241,0.3)'; ctx.lineWidth = 2;
            edges.forEach(([a,b]) => { ctx.beginPath(); ctx.moveTo(positions[a].x,positions[a].y); ctx.lineTo(positions[b].x,positions[b].y); ctx.stroke(); });
            const colors = ['#6366f1','#8b5cf6','#22c55e','#3b82f6','#f59e0b','#ef4444','#06b6d4','#ec4899'];
            positions.forEach((p,i) => {
                ctx.beginPath(); ctx.arc(p.x,p.y,20,0,Math.PI*2); ctx.fillStyle=colors[i % colors.length]; ctx.fill();
                ctx.fillStyle='#fff'; ctx.font='11px sans-serif'; ctx.textAlign='center'; ctx.textBaseline='middle';
                ctx.fillText(nodes[i],p.x,p.y);
            });
        })
        .catch(() => {
            // Fallback: show hardcoded graph if API fails
            const nodes = ['Variables','Loops','Functions','Data Structures','Pandas','NumPy','Statistics','Visualization'];
            const edges = [[0,1],[0,2],[1,2],[2,3],[3,4],[4,5],[4,6],[5,7],[6,7]];
            const cx = canvas.width/2, cy = canvas.height/2;
            const r = Math.min(cx,cy)*0.6;
            const positions = nodes.map((_,i) => ({ x: cx+Math.cos(i/nodes.length*Math.PI*2)*r, y: cy+Math.sin(i/nodes.length*Math.PI*2)*r }));
            ctx.strokeStyle = 'rgba(99,102,241,0.3)'; ctx.lineWidth = 2;
            edges.forEach(([a,b]) => { ctx.beginPath(); ctx.moveTo(positions[a].x,positions[a].y); ctx.lineTo(positions[b].x,positions[b].y); ctx.stroke(); });
            const colors = ['#6366f1','#8b5cf6','#22c55e','#3b82f6','#f59e0b','#ef4444','#06b6d4','#ec4899'];
            positions.forEach((p,i) => {
                ctx.beginPath(); ctx.arc(p.x,p.y,20,0,Math.PI*2); ctx.fillStyle=colors[i]; ctx.fill();
                ctx.fillStyle='#fff'; ctx.font='11px sans-serif'; ctx.textAlign='center'; ctx.textBaseline='middle';
                ctx.fillText(nodes[i],p.x,p.y);
            });
        });
}

loadTab('dashboard');
