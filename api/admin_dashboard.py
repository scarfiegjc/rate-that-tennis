"""
ratethat.tennis — Admin dashboard.
Lightweight self-contained HTML page that:
  - shows green/amber/red status dots for every component
  - auto-refreshes every 5 seconds
  - has buttons to trigger each /admin/* endpoint with visible result

Mounted at /admin (HTML response).
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>ratethat.tennis — admin</title>
<style>
  body {
    margin: 0; padding: 20px 28px;
    font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
    background: #F7F5F2; color: #1C1917;
    font-size: 14px; line-height: 1.5;
  }
  h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.5px; }
  .sub { color: #78716C; font-size: 13px; margin-bottom: 24px; }
  .grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 16px; max-width: 1100px;
  }
  .card {
    background: #FFF; border: 1px solid #E0DBCF; border-radius: 8px;
    padding: 16px 18px; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }
  .card h2 { font-size: 13px; margin: 0 0 12px; text-transform: uppercase;
             letter-spacing: 0.6px; color: #78716C; font-weight: 600; }
  .row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 6px 0; border-bottom: 1px solid #EDE9E3; font-size: 13px;
  }
  .row:last-child { border-bottom: none; }
  .dot {
    display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    margin-right: 8px; vertical-align: middle; flex-shrink: 0;
  }
  .dot.green  { background: #059669; }
  .dot.amber  { background: #D97706; }
  .dot.red    { background: #DC2626; }
  .dot.grey   { background: #D6D3D1; }
  .num {
    font-variant-numeric: tabular-nums; font-weight: 700; font-size: 14px;
  }
  .label { color: #44403C; }
  button {
    border: 1px solid #E0DBCF; background: #FFF; padding: 6px 12px;
    border-radius: 6px; cursor: pointer; font-family: inherit; font-size: 12px;
    font-weight: 500; color: #1C1917; transition: all 0.1s;
  }
  button:hover  { background: #F2EFE9; border-color: #78716C; }
  button:active { background: #EDE9E3; }
  button.primary {
    background: #059669; color: #FFF; border-color: #059669;
  }
  button.primary:hover { background: #047857; border-color: #047857; }
  .actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
  pre {
    background: #1C1917; color: #E7E5E4; padding: 12px; border-radius: 6px;
    font-size: 11px; line-height: 1.4; overflow-x: auto; max-height: 280px;
    margin-top: 12px; font-family: 'SF Mono', Menlo, monospace;
  }
  .summary-row {
    display: grid; grid-template-columns: 1fr auto auto;
    align-items: center; padding: 10px 12px; gap: 10px;
    background: #FFF; border: 1px solid #E0DBCF; border-radius: 8px;
    margin-bottom: 4px;
  }
  .summary-row .progress {
    width: 120px; height: 6px; background: #EDE9E3; border-radius: 3px;
    overflow: hidden;
  }
  .summary-row .fill { height: 100%; background: #059669; transition: width 0.3s; }
  .summary-row .fill.amber { background: #D97706; }
  .summary-row .fill.red   { background: #DC2626; }
  .meta { font-size: 11px; color: #78716C; }
  #lastRun { font-size: 11px; color: #78716C; margin-left: 12px; }
  .running { animation: pulse 1s infinite; }
  @keyframes pulse { 50% { opacity: 0.5; } }
</style>
</head>
<body>
<h1>ratethat.tennis — admin</h1>
<div class="sub">
  Live status of every component, auto-refreshing every 5s.
  <span id="lastRun"></span>
</div>

<div style="margin-bottom: 16px;">
  <button class="primary" onclick="runBootstrap()">Run full bootstrap</button>
  <button onclick="run('migrate')">Migrate schema</button>
  <button onclick="run('surface-backfill')">Surface backfill</button>
  <button onclick="run('hand-backfill')">Hand backfill</button>
  <button onclick="run('point-analysis')">Point analysis</button>
  <button onclick="run('point-backfill')">Point backfill (runs + deuce)</button>
  <button onclick="run('point-diag')">Point data diag</button>
  <button onclick="run('player-sync')">Player sync</button>
  <button onclick="run('player-sync?tournaments=true')">Player sync + discover</button>
  <button onclick="showAccuracy()" style="background: #166534; color: white; border-color: #166534;">Show accuracy</button>
  <button onclick="showBacktest()" style="background: #1e40af; color: white; border-color: #1e40af;">Historic backtest</button>
  <button onclick="run('fill-ratings')">Fill ratings</button>
  <button onclick="run('form-score')">Form score</button>
  <button onclick="run('hand-splits')">Hand splits</button>
  <button onclick="run('predict')">Re-predict</button>
  <button onclick="run('settle')">Settle</button>
  <button onclick="run('systems')">Run systems</button>
  <button onclick="refresh()">↻ Refresh</button>
</div>

<div id="output"></div>

<div class="grid">
  <div class="card">
    <h2>Schema</h2>
    <div id="schema"></div>
  </div>
  <div class="card">
    <h2>Players</h2>
    <div id="players"></div>
  </div>
  <div class="card">
    <h2>Matches (next 7 days)</h2>
    <div id="matches"></div>
  </div>
  <div class="card">
    <h2>Predictions</h2>
    <div id="predictions"></div>
  </div>
  <div class="card" style="grid-column: 1 / -1;">
    <h2>Tournaments missing surface</h2>
    <div id="missingSurface"></div>
  </div>
</div>

<script>
function dot(state) {
  return `<span class="dot ${state}"></span>`;
}

function statusFor(item) {
  if (item.ok) return 'green';
  if (item.partial) return 'amber';
  return 'red';
}

async function refresh() {
  const r = await fetch('/diagnostics');
  if (!r.ok) {
    document.getElementById('output').innerHTML =
      `<div class="card"><strong>Diagnostics fetch failed:</strong> ${r.status}</div>`;
    return;
  }
  const d = await r.json();
  const lastRun = document.getElementById('lastRun');
  lastRun.textContent = 'Last refresh: ' + new Date().toLocaleTimeString();

  // Schema rows
  const schemaEl = document.getElementById('schema');
  schemaEl.innerHTML = Object.entries(d.schema || {}).map(([name, exists]) =>
    `<div class="row"><span class="label">${dot(exists ? 'green' : 'red')}${name}</span>
       <span class="num">${exists ? '✓' : '✗'}</span></div>`
  ).join('');

  // Players
  const players = d.players || {};
  const cov = players.rtt_coverage_pct;
  const covState = cov == null ? 'grey' : cov >= 80 ? 'green' : cov >= 30 ? 'amber' : 'red';
  document.getElementById('players').innerHTML = `
    <div class="row"><span class="label">Total players</span>
      <span class="num">${players.total ?? '—'}</span></div>
    <div class="row"><span class="label">${dot(covState)}With RTT score</span>
      <span class="num">${players.with_rtt ?? '—'}</span></div>
    <div class="row"><span class="label">RTT coverage</span>
      <span class="num" style="color: ${covState === 'green' ? '#059669' : covState === 'amber' ? '#D97706' : '#DC2626'}">${cov != null ? cov + '%' : '—'}</span></div>
  `;

  // Matches
  const m = d.matches || {};
  const predCov = (m.with_predictions_7d != null && m.upcoming_7d) ? Math.round(100 * m.with_predictions_7d / m.upcoming_7d) : null;
  const ffPct = (m.fifty_fifty != null && m.upcoming_7d) ? Math.round(100 * m.fifty_fifty / m.upcoming_7d) : null;
  document.getElementById('matches').innerHTML = `
    <div class="row"><span class="label">Upcoming (7d)</span>
      <span class="num">${m.upcoming_7d ?? '—'}</span></div>
    <div class="row"><span class="label">${dot(predCov >= 90 ? 'green' : predCov >= 50 ? 'amber' : 'red')}With predictions</span>
      <span class="num">${m.with_predictions_7d ?? '—'} (${predCov != null ? predCov + '%' : '—'})</span></div>
    <div class="row"><span class="label">${dot(m.no_surface_7d === 0 ? 'green' : 'red')}Missing surface</span>
      <span class="num">${m.no_surface_7d ?? '—'}</span></div>
    <div class="row"><span class="label">${dot(ffPct < 20 ? 'green' : ffPct < 50 ? 'amber' : 'red')}50/50 predictions</span>
      <span class="num">${m.fifty_fifty ?? '—'} (${ffPct != null ? ffPct + '%' : '—'})</span></div>
  `;

  // Predictions
  const p = d.predictions || {};
  document.getElementById('predictions').innerHTML = `
    <div class="row"><span class="label">Settled</span>
      <span class="num">${p.settled ?? '—'}</span></div>
    <div class="row"><span class="label">Correct</span>
      <span class="num">${p.correct ?? '—'}</span></div>
    <div class="row"><span class="label">Accuracy</span>
      <span class="num">${p.accuracy_pct != null ? p.accuracy_pct + '%' : '—'}</span></div>
  `;

  // Missing surfaces
  const ms = d.tournaments_missing_surface || [];
  if (ms.length === 0) {
    document.getElementById('missingSurface').innerHTML =
      `<div class="row"><span class="label">${dot('green')}All upcoming tournaments have a surface</span></div>`;
  } else {
    document.getElementById('missingSurface').innerHTML = ms.slice(0, 12).map(t =>
      `<div class="row"><span class="label">${dot('red')}${t.name}</span>
        <span class="meta">id ${t.id}</span></div>`
    ).join('');
  }
}

async function run(endpoint) {
  const out = document.getElementById('output');
  out.innerHTML =
    `<div class="card"><strong class="running">Running /admin/${endpoint}…</strong></div>`;
  const t0 = Date.now();
  try {
    const r = await fetch('/admin/' + endpoint);
    const data = await r.json();
    const ms = Date.now() - t0;
    out.innerHTML =
      `<div class="card"><strong>/admin/${endpoint}</strong>
       <span class="meta"> · ${ms}ms · ${new Date().toLocaleTimeString()}</span>
       <pre>${JSON.stringify(data, null, 2)}</pre></div>`;
  } catch (e) {
    out.innerHTML =
      `<div class="card"><strong style="color:#DC2626">/admin/${endpoint} failed:</strong>
       <pre>${e.message || e}</pre></div>`;
  }
  refresh();
}

async function showAccuracy() {
  const out = document.getElementById('output');
  out.innerHTML = `<div class="card"><strong class="running">Loading live accuracy…</strong></div>`;
  try {
    const r = await fetch('/api/v1/predictions/accuracy');
    const data = await r.json();
    out.innerHTML = `<div class="card"><strong>Live accuracy (settled predictions)</strong>
      <div class="meta">50/50 picks excluded</div>
      <pre>${JSON.stringify(data, null, 2)}</pre></div>`;
  } catch (e) {
    out.innerHTML = `<div class="card"><strong style="color:#DC2626">Failed:</strong><pre>${e.message || e}</pre></div>`;
  }
}

async function showBacktest() {
  const out = document.getElementById('output');
  out.innerHTML = `<div class="card"><strong class="running">Loading historic backtest…</strong></div>`;
  try {
    const r = await fetch('/predictions/backtest');
    const data = await r.json();
    const summary = data.summary || {};
    let html = `<div class="card"><strong>Historic backtest (10-year walk-forward 2015-2024)</strong>
      <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:12px; margin-top: 12px;">
        <div style="background:#dcfce7;padding:10px;border-radius:6px;">
          <div style="font-size:24px;font-weight:800;color:#166534">${(summary.mean_accuracy*100).toFixed(1)}%</div>
          <div style="font-size:11px;color:#166534;text-transform:uppercase;font-weight:600">Mean accuracy</div>
        </div>
        <div style="background:#fef3c7;padding:10px;border-radius:6px;">
          <div style="font-size:24px;font-weight:800;color:#92400e">${(summary.mean_auc).toFixed(3)}</div>
          <div style="font-size:11px;color:#92400e;text-transform:uppercase;font-weight:600">AUC</div>
        </div>
        <div style="background:#dcfce7;padding:10px;border-radius:6px;">
          <div style="font-size:24px;font-weight:800;color:#166534">+${(summary.mean_edge_vs_elo*100).toFixed(1)}pp</div>
          <div style="font-size:11px;color:#166534;text-transform:uppercase;font-weight:600">Edge over Elo</div>
        </div>
        <div style="background:#fef3c7;padding:10px;border-radius:6px;">
          <div style="font-size:24px;font-weight:800;color:#92400e">${summary.total_matches?.toLocaleString()}</div>
          <div style="font-size:11px;color:#92400e;text-transform:uppercase;font-weight:600">Matches tested</div>
        </div>
      </div>
      <div style="font-size:11px; color:#78716C; margin-top: 12px">Walk-forward test on 2015-2024 sa_matches. The XGBoost+LightGBM+Logistic ensemble is our model ceiling.</div>
    </div>`;
    out.innerHTML = html;
  } catch (e) {
    out.innerHTML = `<div class="card"><strong style="color:#DC2626">Failed:</strong><pre>${e.message || e}</pre></div>`;
  }
}

async function runBootstrap() {
  const out = document.getElementById('output');
  out.innerHTML =
    `<div class="card"><strong class="running">Running full bootstrap…</strong>
     <div class="meta">This can take 30–60 seconds. Stages: schema → backfill → fill ratings → hand splits → predict → settle → systems.</div></div>`;
  await run('bootstrap');
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""
