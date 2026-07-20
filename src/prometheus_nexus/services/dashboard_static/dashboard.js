const API = '';
let charts = {};
let lastSummary = null;

async function fetchJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(path + ' ' + r.status);
  return await r.json();
}
function fmt(n) { return (n ?? 0).toLocaleString(); }
function fmtUptime(s) {
  s = s || 0; const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h + 'h ' + m + 'm';
}
function el(id) { return document.getElementById(id); }

function switchPanel(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  el('panel-' + name).classList.add('active');
  document.querySelector('.nav-item[data-panel="' + name + '"]').classList.add('active');
}

async function updateAll() {
  try {
    const [status, summary, cns, cc, ar] = await Promise.all([
      fetchJSON('/api/v1/status'),
      fetchJSON('/api/v1/dashboard/summary'),
      fetchJSON('/api/v1/nervous/cns'),
      fetchJSON('/api/v1/nervous/cc'),
      fetchJSON('/api/v1/nervous/ar'),
    ]).catch(async () => {
      // 退化: 逐个取
      return [
        await fetchJSON('/api/v1/status'),
        await fetchJSON('/api/v1/dashboard/summary'),
        await fetchJSON('/api/v1/nervous/cns'),
        await fetchJSON('/api/v1/nervous/cc'),
        await fetchJSON('/api/v1/nervous/ar'),
      ];
    });
    lastSummary = summary && summary.data ? summary.data : {};
    renderHeader(status, lastSummary);
    renderOverview(lastSummary, cns, cc, ar);
    renderMechanisms(lastSummary);
    renderEvolution(lastSummary);
    renderMemory(lastSummary);
    renderAgents(lastSummary);
    renderPapers(lastSummary);
    el('sb-last-update').textContent = new Date().toLocaleTimeString();
  } catch (e) {
    console.error('updateAll failed', e);
  }
}

function renderHeader(status, summary) {
  status = status || {};
  const mem = (summary && summary.memory) || {};
  const ag = (summary && summary.agents) || {};
  el('hdr-nodes').textContent = fmt(status.node_count || mem.node_count);
  el('hdr-mechs').textContent = fmt((summary.mechanisms && summary.mechanisms.total) || status.mechanisms);
  el('hdr-util').textContent = mem.global_utility != null ? mem.global_utility.toFixed(3) : '—';
  el('hdr-host').textContent = ag.active_host || 'none';
  const healthy = status.health === 'healthy' || !status.health;
  el('hdr-dot').className = 'status-dot ' + (healthy ? 'online' : 'offline');
  el('hdr-health-text').textContent = status.health || 'ok';
  el('hdr-uptime').textContent = fmtUptime(status.uptime_seconds);
}

function kpiCard(val, label) {
  return `<div class="kpi"><div class="k-val">${val}</div><div class="k-label">${label}</div></div>`;
}

function renderOverview(summary, cns, cc, ar) {
  cns = cns && cns.data ? cns.data : cns; cc = cc && cc.data ? cc.data : cc; ar = ar && ar.data ? ar.data : ar;
  const mem = summary.memory || {};
  const mech = summary.mechanisms || {};
  const kpis = [
    kpiCard(fmt(mem.node_count), '记忆节点'),
    kpiCard(fmt(mech.total), '机制总数'),
    kpiCard(fmt(mech.enabled), '激活机制'),
    kpiCard(fmt(mech.superposed && mech.superposed.length), '叠加态候选'),
    kpiCard((mem.global_utility != null ? mem.global_utility.toFixed(3) : '—'), '全局效用锚'),
    kpiCard((summary.agents ? summary.agents.active_host : '—'), '接入 Agent'),
  ];
  el('kpi-grid').innerHTML = kpis.join('');
  el('cns-body').innerHTML = `<div class="mono">state: ${cns.state || '—'}<br>chain_depth: ${cns.auto_chain_depth || 0}<br>triggers: ${cns.triggers_fired || 0}</div>`;
  el('cc-body').innerHTML = `<div class="mono">gaps: ${(cc.gaps || []).length}<br>threshold: ${((cc.evolve_threshold || 0)).toFixed(3)}<br>admin_log: ${cc.admin_log_entries || 0}</div>`;
  el('ar-body').innerHTML = `<div class="mono">${ar && typeof ar === 'object' ? JSON.stringify(ar).slice(0, 160) : '—'}</div>`;
  // telemetry mini chart
  const tel = (summary.evolution && summary.evolution.engine_stats) || {};
  drawLine('telemetry-chart', ['gen', 'fitness'], [{x: 's', y: mem.global_utility || 0.5}]);
}

function drawLine(canvasId, labels, points) {
  const ctx = el(canvasId); if (!ctx) return;
  if (charts[canvasId]) charts[canvasId].destroy();
  charts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: { labels: points.map(p => p.x), datasets: [{ label: labels[1], data: points.map(p => p.y), borderColor: '#a5b4fc', backgroundColor: 'rgba(99,102,241,0.15)', fill: true, tension: 0.4 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#5d6b8a' } }, y: { ticks: { color: '#5d6b8a' }, min: 0, max: 1 } } }
  });
}
function drawDoughnut(canvasId, labels, values, colors) {
  const ctx = el(canvasId); if (!ctx) return;
  if (charts[canvasId]) charts[canvasId].destroy();
  charts[canvasId] = new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { color: '#9aa6c0', font: { size: 11 } } } } }
  });
}

function renderMechanisms(summary) {
  const m = summary.mechanisms || {};
  el('mech-kpi').innerHTML = [
    kpiCard(fmt(m.total), '机制总数'),
    kpiCard(fmt(m.enabled), '激活'),
    kpiCard(fmt((m.status_dist && m.status_dist.pending) || 0), '待验证'),
    kpiCard(fmt(m.prune_candidates), '剪枝候选'),
  ].join('');
  const sd = m.status_dist || {};
  const labels = Object.keys(sd), vals = labels.map(k => sd[k]);
  const colors = ['#6366f1', '#10b981', '#f59e0b', '#22d3ee', '#c084fc', '#f43f5e'];
  drawDoughnut('mech-chart', labels, vals, colors.slice(0, labels.length));
  el('superposed-body').innerHTML = (m.superposed && m.superposed.length)
    ? m.superposed.map(s => `<div class="tag partial">${s}</div>`).join('') : '<span class="mono">无叠加态候选</span>';
  const eff = m.top_effects || [];
  el('effect-body').innerHTML = eff.length
    ? eff.map(e => `<div class="sidebar-metric"><span class="key">${e.name}</span><span class="val" style="color:${e.effect < 0 ? 'var(--red)' : 'var(--green)'}">${e.effect}</span></div>`).join('')
    : '<span class="mono">暂无效用反馈</span>';
  el('prune-body').innerHTML = m.prune_candidates > 0
    ? `<div class="tag stub">${m.prune_candidates} 个负效用机制待剪枝</div><div class="mono">主动剪枝(梯度引导)防止伪相关机制拖累系统</div>`
    : '<div class="tag match">无负效用机制</div>';
}

function renderEvolution(summary) {
  const ev = summary.evolution || {};
  const chain = (ev.last_chain && ev.last_chain.metadata) || {};
  const ct = chain.chain_trace || {};
  const steps = Object.keys(ct);
  if (steps.length) {
    el('chain-body').innerHTML = steps.map(k =>
      `<span class="chain-step ${ct[k] ? 'ok' : 'miss'}">${k} ${ct[k] ? '✓' : '✗'}</span>`).join('')
      + `<div class="mono" style="margin-top:10px">chain_complete: ${chain.chain_complete}</div>`;
  } else {
    el('chain-body').innerHTML = '<span class="mono">暂无进化记录(运行 evolve 后显示链完整性)</span>';
  }
  const es = ev.engine_stats || {};
  el('evostats-body').innerHTML = `<div class="mono">gene_specs: ${ev.gene_specs || 0}<br>${Object.keys(es).slice(0, 8).map(k => k + ': ' + (typeof es[k] === 'object' ? JSON.stringify(es[k]).slice(0, 40) : es[k])).join('<br>')}</div>`;
  drawLine('fitness-chart', ['gen', 'fitness'], [{x: 'now', y: chain.fitness_after || 0.5}]);
  drawLine('trend-chart', ['gen', 'trend'], [{x: 'now', y: chain.fitness_before || 0.5}]);
}

function renderMemory(summary) {
  const mem = summary.memory || {};
  const td = mem.type_distribution || {};
  const labels = Object.keys(td), vals = labels.map(k => td[k]);
  const palette = ['#6366f1', '#10b981', '#f59e0b', '#22d3ee', '#c084fc', '#f43f5e', '#34d399', '#fb923c'];
  drawDoughnut('type-chart', labels, vals, palette.slice(0, labels.length));
  el('mem-kpi').innerHTML = [
    kpiCard(fmt(mem.node_count), '节点总数'),
    kpiCard(Object.keys(td).length, '节点类型数'),
    kpiCard(mem.global_utility != null ? mem.global_utility.toFixed(3) : '—', '全局效用锚'),
  ].join('');
  el('util-body').innerHTML = `<div class="mono">global_utility: ${mem.global_utility != null ? mem.global_utility.toFixed(4) : '—'}<br>这是 D3 的 fitness 效用锚(真实使用度, 非参数自指)</div>`;
}

function renderAgents(summary) {
  const ag = summary.agents || {};
  el('agents-body').innerHTML = `
    <table><tr><th>字段</th><th>值</th></tr>
    <tr><td>active_host (host_id)</td><td class="mono">${ag.active_host || 'none'}</td></tr>
    <tr><td>adapter_type</td><td class="mono">${ag.adapter_type || 'none'}</td></tr>
    <tr><td>多 Agent 隔离</td><td>按 host_id 分区(V2.1 C5)</td></tr>
    <tr><td>安全边界</td><td>Ultra 不改 Agent 源码, 仅 emit 建议</td></tr></table>`;
}

function renderPapers(summary) {
  const ps = summary.papers || [];
  if (!ps.length) { el('papers-body').innerHTML = '<span class="mono">—</span>'; return; }
  let rows = ps.map(p => `<tr><td class="mono">${p.arxiv}</td><td>${p.title}</td><td>${p.ultra}</td><td><span class="tag ${p.rating.toLowerCase()}">${p.rating}</span></td><td class="mono">${p.ver}</td></tr>`).join('');
  el('papers-body').innerHTML = `<table><tr><th>arXiv</th><th>论文</th><th>ULTRA 强化</th><th>评级</th><th>版本</th></tr>${rows}</table>`;
}

// init
updateAll();
setInterval(updateAll, 5000);

