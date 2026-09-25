/* APEX Dashboard — D3.js visualizations */

import { apiClient } from "./api.js";

/* ------------------------------------------------------------------ */
/* Mastery Heatmap (Calendar-style)                                   */
/* ------------------------------------------------------------------ */

export function renderHeatmap(containerId, data, opts = {}) {
  const container = document.getElementById(containerId);
  if (!container) return console.warn(`#${containerId} not found`);

  container.innerHTML = "";
  const width = container.clientWidth || 700;
  const height = Math.max(200, data.length * 8 + 40);
  const margin = { top: 20, right: 20, bottom: 30, left: 50 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;

  const svg = d3.select(container)
    .append("svg")
    .attr("width", width)
    .attr("height", height)
    .append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  const allDates = data.map(d => d.date);
  const allTopics = [...new Set(data.flatMap(d => Object.keys(d.topics)))];
  const dateExtent = d3.extent(allDates);

  // Color scale: mastery 0–90 → red → yellow → green
  const color = d3.scaleSequential(d3.interpolateRdYlGn)
    .domain([0, 100]);

  const cellW = innerW / allDates.length;
  const cellH = Math.min(22, Math.max(6, innerH / allTopics.length));

  // X scale — dates
  const xScale = d3.scaleBand()
    .domain(allDates)
    .range([0, innerW])
    .padding(0.05);

  // Y scale — topics
  const yScale = d3.scaleBand()
    .domain(allTopics)
    .range([0, innerH])
    .padding(0.15);

  // Draw cells
  const cells = [];
  data.forEach(row => {
    allTopics.forEach(topic => {
      const val = row.topics[topic] ?? 0;
      cells.push({ date: row.date, topic, value: val });
    });
  });

  svg.selectAll(".cell")
    .data(cells)
    .join("rect")
    .attr("class", "cell")
    .attr("x", d => xScale(d.date))
    .attr("y", d => yScale(d.topic))
    .attr("width", xScale.bandwidth())
    .attr("height", yScale.bandwidth())
    .attr("rx", 2)
    .attr("fill", d => {
      if (d.value === 0) return "var(--muted-foreground)";
      return color(d.value);
    })
    .attr("opacity", d => (d.value === 0 ? 0.15 : 0.85))
    .on("mouseover", function (e, d) {
      d3.select(this).attr("stroke", "var(--accent)").attr("stroke-width", 2);
      showTooltip(e, `${d.topic}: ${d.value.toFixed(1)} min`);
    })
    .on("mouseout", function () {
      d3.select(this).attr("stroke", "none");
      hideTooltip();
    });

  // X axis — month labels
  const monthLabels = d3.timeMonths(dateExtent[0], dateExtent[1] || dateExtent[0]);
  svg.append("g")
    .attr("transform", `translate(0,${innerH + 5})`)
    .call(d3.axisBottom(xScale).tickValues(monthLabels)
      .tickFormat(d3.timeFormat("%b")))
    .selectAll("text")
    .attr("fill", "var(--muted-foreground)")
    .attr("font-size", "11px");

  // Y axis
  svg.append("g")
    .call(d3.axisLeft(yScale).tickSize(0))
    .selectAll("text")
    .attr("fill", "var(--muted-foreground)")
    .attr("font-size", "12px");

  // Legend
  const legendW = 120;
  const legendH = 10;
  const legendX = innerW - legendW - 10;
  const legendY = 5;

  const defs = svg.append("defs");
  const gradId = `legend-grad-${containerId}`;
  const grad = defs.append("linearGradient").attr("id", gradId).attr("x1", "0").attr("x2", "1");
  grad.append("stop").attr("offset", "0%").attr("stop-color", d3.interpolateRdYlGn(0));
  grad.append("stop").attr("offset", "50%").attr("stop-color", d3.interpolateRdYlGn(50));
  grad.append("stop").attr("offset", "100%").attr("stop-color", d3.interpolateRdYlGn(100));

  svg.append("rect")
    .attr("x", legendX).attr("y", legendY)
    .attr("width", legendW).attr("height", legendH)
    .attr("rx", 3)
    .attr("fill", `url(#${gradId})`);

  svg.append("text")
    .attr("x", legendX).attr("y", legendY - 4)
    .attr("fill", "var(--muted-foreground)")
    .attr("font-size", "10px")
    .text("0 min");

  svg.append("text")
    .attr("x", legendX + legendW).attr("y", legendY - 4)
    .attr("fill", "var(--muted-foreground)")
    .attr("font-size", "10px")
    .attr("text-anchor", "end")
    .text("90+ min");
}

/* ------------------------------------------------------------------ */
/* Knowledge Graph (Force-directed)                                  */
/* ------------------------------------------------------------------ */

export function renderKnowledgeGraph(containerId, nodes, edges, opts = {}) {
  const container = document.getElementById(containerId);
  if (!container) return console.warn(`#${containerId} not found`);

  container.innerHTML = "";
  const width = container.clientWidth || 600;
  const height = Math.max(400, Math.min(600, width * 0.7));

  const svg = d3.select(container)
    .append("svg")
    .attr("width", width)
    .attr("height", height)
    .attr("viewBox", `0 0 ${width} ${height}`)
    .style("background", "transparent");

  // Build D3-compatible data
  const nodeMap = new Map(nodes.map((n, i) => [n.id, { ...n, index: i }]));
  const linkData = edges.map(e => ({
    source: nodeMap.get(e.source),
    target: nodeMap.get(e.target),
    strength: e.strength,
  }));

  const simulation = d3.forceSimulation(Array.from(nodeMap.values()))
    .force("link", d3.forceLink(linkData).id(d => d.id).distance(120))
    .force("charge", d3.forceManyBody().strength(-200))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collision", d3.forceCollide().radius(25));

  // Arrow marker
  svg.append("defs").append("marker")
    .attr("id", `arrow-${containerId}`)
    .attr("viewBox", "0 -5 10 10")
    .attr("refX", 25)
    .attr("refY", 0)
    .attr("markerWidth", 6)
    .attr("markerHeight", 6)
    .attr("orient", "auto")
    .append("path")
    .attr("d", "M0,-5L10,0L0,5")
    .attr("fill", "var(--accent)");

  // Links
  const link = svg.append("g")
    .selectAll("line")
    .data(linkData)
    .join("line")
    .attr("stroke", "var(--accent)")
    .attr("stroke-opacity", d => 0.3 + d.strength * 0.5)
    .attr("stroke-width", d => 1 + d.strength * 3)
    .attr("marker-end", `url(#arrow-${containerId})`);

  // Node groups
  const nodeGroup = svg.append("g")
    .selectAll("g")
    .data(Array.from(nodeMap.values()))
    .join("g")
    .call(d3.drag()
      .on("start", (e, d) => {
        if (!e.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (e, d) => {
        d.fx = e.x;
        d.fy = e.y;
      })
      .on("end", (e, d) => {
        if (!e.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      }));

  // Node circles
  nodeGroup.append("circle")
    .attr("r", 18)
    .attr("fill", "var(--card)")
    .attr("stroke", "var(--accent)")
    .attr("stroke-width", 2)
    .style("cursor", "pointer");

  // Node labels
  nodeGroup.append("text")
    .text(d => d.id)
    .attr("text-anchor", "middle")
    .attr("dy", 4)
    .attr("fill", "var(--foreground)")
    .attr("font-size", "11px")
    .attr("font-weight", "600");

  // Tooltip
  nodeGroup.on("mouseover", function (e, d) {
    d3.select(this).select("circle").attr("stroke-width", 4);
    showTooltip(e, `Concept: ${d.id}`);
  }).on("mouseout", function () {
    d3.select(this).select("circle").attr("stroke-width", 2);
    hideTooltip();
  });

  simulation.on("tick", () => {
    link
      .attr("x1", d => d.source.x)
      .attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x)
      .attr("y2", d => d.target.y);

    nodeGroup.attr("transform", d => `translate(${d.x},${d.y})`);
  });

  return simulation;
}

/* ------------------------------------------------------------------ */
/* Progress Ring Chart                                                */
/* ------------------------------------------------------------------ */

export function renderProgressRing(containerId, pct, label, opts = {}) {
  const container = document.getElementById(containerId);
  if (!container) return console.warn(`#${containerId} not found`);

  container.innerHTML = "";
  const size = container.clientWidth || 120;
  const strokeW = 10;
  const radius = (size - strokeW) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.min(pct, 100) / 100);

  const color = pct >= 80 ? "var(--accent)"
    : pct >= 50 ? "#f59e0b"
    : "#ef4444";

  const svg = d3.select(container)
    .append("svg")
    .attr("width", size)
    .attr("height", size)
    .append("g")
    .attr("transform", `translate(${size / 2},${size / 2})`);

  // Background ring
  svg.append("circle")
    .attr("r", radius)
    .attr("fill", "none")
    .attr("stroke", "var(--border)")
    .attr("stroke-width", strokeW);

  // Progress ring
  const path = svg.append("circle")
    .attr("r", radius)
    .attr("fill", "none")
    .attr("stroke", color)
    .attr("stroke-width", strokeW)
    .attr("stroke-linecap", "round")
    .attr("stroke-dasharray", circumference)
    .attr("stroke-dashoffset", circumference)
    .attr("transform", "rotate(-90)");

  path.transition()
    .duration(opts.duration || 800)
    .ease(d3.easeCubicOut)
    .attr("stroke-dashoffset", offset);

  // Percentage text
  svg.append("text")
    .attr("text-anchor", "middle")
    .attr("dy", -4)
    .attr("fill", "var(--foreground)")
    .attr("font-size", "22px")
    .attr("font-weight", "700")
    .text(`${Math.round(pct)}%`);

  // Label
  svg.append("text")
    .attr("text-anchor", "middle")
    .attr("dy", 20)
    .attr("fill", "var(--muted-foreground)")
    .attr("font-size", "11px")
    .text(label || "");
}

/* ------------------------------------------------------------------ */
/* Spaced Repetition Timeline                                        */
/* ------------------------------------------------------------------ */

export function renderScheduleTimeline(containerId, items, opts = {}) {
  const container = document.getElementById(containerId);
  if (!container) return console.warn(`#${containerId} not found`);

  container.innerHTML = "";

  const width = container.clientWidth || 700;
  const rowH = 44;
  const height = items.length * rowH + 60;
  const margin = { top: 20, right: 160, bottom: 30, left: 140 };

  const svg = d3.select(container)
    .append("svg")
    .attr("width", width)
    .attr("height", height)
    .append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  const innerW = width - margin.left - margin.right;

  // Parse dates
  const parsed = items.map((item, i) => ({
    ...item,
    next_ms: new Date(item.next_review).getTime(),
    last_ms: new Date(item.last_reviewed).getTime(),
    index: i,
  }));

  const dateExtent = d3.extent(parsed.flatMap(d => [d.last_ms, d.next_ms]));
  const xScale = d3.scaleTime()
    .domain(dateExtent)
    .range([0, innerW]);

  // Y scale — topic rows
  const yScale = d3.scaleBand()
    .domain(parsed.map(d => d.topic))
    .range([0, items.length * rowH])
    .padding(0.3);

  // Grid lines
  svg.append("g")
    .attr("class", "grid")
    .call(d3.axisLeft(yScale).tickSize(0).tickFormat(""))
    .selectAll("line").attr("stroke", "var(--border)").attr("stroke-opacity", 0.3);

  // Today marker
  const today = new Date();
  svg.append("line")
    .attr("x1", xScale(today))
    .attr("x2", xScale(today))
    .attr("y1", 0)
    .attr("y2", items.length * rowH)
    .attr("stroke", "var(--accent)")
    .attr("stroke-width", 2)
    .attr("stroke-dasharray", "4,4")
    .attr("opacity", 0.6);

  svg.append("text")
    .attr("x", xScale(today) + 4)
    .attr("y", -6)
    .attr("fill", "var(--accent)")
    .attr("font-size", "10px")
    .attr("font-weight", "700")
    .text("Today");

  // Last-reviewed markers (circles)
  svg.selectAll(".last-reviewed")
    .data(parsed)
    .join("circle")
    .attr("class", "last-reviewed")
    .attr("cx", d => xScale(d.last_ms))
    .attr("cy", d => yScale(d.topic) + yScale.bandwidth() / 2)
    .attr("r", 5)
    .attr("fill", "var(--muted-foreground)");

  // Next-review bars
  svg.selectAll(".next-bar")
    .data(parsed)
    .join("rect")
    .attr("class", "next-bar")
    .attr("x", d => xScale(d.last_ms))
    .attr("y", d => yScale(d.topic))
    .attr("width", d => Math.max(2, xScale(d.next_ms) - xScale(d.last_ms)))
    .attr("height", yScale.bandwidth())
    .attr("fill", "var(--accent)")
    .attr("fill-opacity", 0.2)
    .attr("rx", 4);

  // Next-review markers (larger circles)
  svg.selectAll(".next-review")
    .data(parsed)
    .join("circle")
    .attr("class", "next-review")
    .attr("cx", d => xScale(d.next_ms))
    .attr("cy", d => yScale(d.topic) + yScale.bandwidth() / 2)
    .attr("r", 7)
    .attr("fill", "var(--accent)")
    .attr("stroke", "var(--card)")
    .attr("stroke-width", 2)
    .on("mouseover", function (e, d) {
      d3.select(this).attr("r", 10);
      showTooltip(e, `${d.topic}: review ${new Date(d.next_review).toLocaleDateString()}`);
    })
    .on("mouseout", function () {
      d3.select(this).attr("r", 7);
      hideTooltip();
    });

  // Topic labels
  svg.append("g")
    .call(d3.axisLeft(yScale).tickSize(0))
    .selectAll("text")
    .attr("fill", "var(--foreground)")
    .attr("font-size", "12px")
    .attr("font-weight", "500");

  // X axis — date ticks
  svg.append("g")
    .attr("transform", `translate(0,${items.length * rowH})`)
    .call(d3.axisBottom(xScale).ticks(6).tickFormat(d3.timeFormat("%b %d")))
    .selectAll("text")
    .attr("fill", "var(--muted-foreground)")
    .attr("font-size", "10px");
}

/* ------------------------------------------------------------------ */
/* Tooltip helpers (shared)                                          */
/* ------------------------------------------------------------------ */

let tooltipEl = null;

function showTooltip(event, text) {
  if (!tooltipEl) {
    tooltipEl = document.createElement("div");
    tooltipEl.style.cssText = `
      position: fixed; pointer-events: none; z-index: 9999;
      background: var(--card); color: var(--foreground);
      border: 1px solid var(--border); border-radius: 6px;
      padding: 6px 12px; font-size: 12px; font-family: var(--font-sans);
      box-shadow: 0 4px 12px rgba(0,0,0,0.4); opacity: 0;
      transition: opacity 0.15s ease;
    `;
    document.body.appendChild(tooltipEl);
  }
  tooltipEl.textContent = text;
  const rect = event.target?.getBoundingClientRect?.() || { left: 0, top: 0 };
  tooltipEl.style.left = (rect.left + rect.width / 2 - tooltipEl.offsetWidth / 2) + "px";
  tooltipEl.style.top = (rect.top - tooltipEl.offsetHeight - 8) + "px";
  tooltipEl.style.opacity = "1";
}

function hideTooltip() {
  if (tooltipEl) tooltipEl.style.opacity = "0";
}
