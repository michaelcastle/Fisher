"""
Sea Conditions & Forecast page — served at /conditions.

Free:        Embedded Windy.com map showing live SST, wind, waves, ocean currents.
With API key: Numerical wind / wave / CMEMS current forecasts via Windy Point API.
"""


def build_conditions_html() -> str:
    return _PAGE_HTML


_PAGE_HTML = '''<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Sea Conditions &mdash; TunaTrack SEQ</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    :root { --accent:#00f2ff; }
    body  { background:#020b14; color:#e2e8f0; font-family:system-ui,-apple-system,sans-serif; }
    .text-accent  { color:var(--accent); }
    .nav-active   { background:rgba(8,145,178,.2); border-right:4px solid var(--accent); color:var(--accent); font-weight:700; }
    .nav-inactive { color:#94a3b8; transition:all .15s; }
    .nav-inactive:hover { background:rgba(30,41,59,.8); color:#e2e8f0; }
    .card { background:#0d1b2a; border:1px solid rgba(30,58,95,.5); border-radius:12px; }
    .loc-btn {
      padding:6px 16px; border-radius:20px; font-size:13px; cursor:pointer;
      border:1px solid rgba(51,65,85,.8); background:rgba(15,23,42,.6);
      color:#94a3b8; transition:all .15s; white-space:nowrap;
    }
    .loc-btn.active { background:rgba(8,145,178,.25); border-color:#06b6d4; color:#67e8f9; font-weight:600; }
    .layer-btn {
      padding:6px 18px; border-radius:20px; font-size:13px; cursor:pointer;
      border:1px solid rgba(51,65,85,.8); background:rgba(15,23,42,.6);
      color:#94a3b8; transition:all .15s;
    }
    .layer-btn.active { background:#0e7490; border-color:#06b6d4; color:#fff; font-weight:600; }
    .wind-good  { color:#34d399; }
    .wind-ok    { color:#fbbf24; }
    .wind-rough { color:#fb923c; }
    .wind-bad   { color:#f87171; }
    .wave-good  { color:#34d399; }
    .wave-ok    { color:#fbbf24; }
    .wave-rough { color:#fb923c; }
    .wave-bad   { color:#f87171; }
    .curr-strong { color:#22d3ee; }
    .curr-active { color:#60a5fa; }
    .curr-weak   { color:#64748b; }
    .tl-head { font-size:11px; color:#64748b; padding:7px 10px; border-bottom:1px solid rgba(30,58,95,.6); font-weight:700; letter-spacing:.05em; text-transform:uppercase; }
    .tl-cell { padding:7px 10px; font-size:12px; border-bottom:1px solid rgba(30,58,95,.25); }
    .tl-row:nth-child(even) { background:rgba(15,23,42,.35); }
    .tl-row:hover { background:rgba(8,145,178,.07); }
    #windy-frame { width:100%; height:calc(100vh - 145px); min-height:400px; border:none; display:block; }
    @media(max-width:768px) {
      #windy-frame { height:calc(100vh - 110px); min-height:320px; }
      .grid-3col { grid-template-columns:1fr !important; }
    }
  </style>
</head>
<body class="h-full flex overflow-hidden">

<!-- ========== SIDEBAR ========== -->
<aside style="width:220px;min-width:220px;background:#0f172a;border-right:1px solid rgba(30,41,59,.8)" class="flex flex-col h-screen sticky top-0 shrink-0">
  <div class="p-4" style="border-bottom:1px solid rgba(30,41,59,.8)">
    <a href="/" style="text-decoration:none">
      <h1 class="text-sm font-bold text-accent flex items-center gap-2">
        <svg class="w-5 h-5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M21 12c0 0-3-6-9-6S3 12 3 12s3 6 9 6 9-6 9-6z" stroke-linecap="round"/>
          <circle cx="15" cy="12" r="1.5" fill="currentColor"/>
        </svg>
        TunaTrack<span class="text-white">SEQ</span>
      </h1>
    </a>
  </div>
  <nav class="flex-1 px-3 py-2 space-y-1 overflow-y-auto">
    <a href="/" style="text-decoration:none" class="flex items-center gap-3 px-3 py-2.5 rounded-lg nav-inactive">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path d="M9 20l-5.447-2.724A2 2 0 013 15.488V5.111a2 2 0 011.168-1.815l6-2.667a2 2 0 011.664 0l6 2.667A2 2 0 0119 5.111v10.377a2 2 0 01-1.168 1.815L12 20m-3 0l3 1.5m0-1.5v-6" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
      </svg>
      Live Map
    </a>
    <a href="/tactics" style="text-decoration:none" class="flex items-center gap-3 px-3 py-2.5 rounded-lg nav-inactive">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
      </svg>
      Catching Tactics
    </a>
    <a href="/tips" style="text-decoration:none" class="flex items-center gap-3 px-3 py-2.5 rounded-lg nav-inactive">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
      </svg>
      Yellowfin Tips
    </a>
    <a href="/conditions" style="text-decoration:none" class="flex items-center gap-3 px-3 py-2.5 rounded-lg nav-active">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
      </svg>
      Sea Conditions
    </a>
  </nav>
  <div class="p-4 text-xs text-slate-500" style="border-top:1px solid rgba(30,41,59,.8)">
    SE Queensland<br/>Noosa &rarr; Gold Coast
  </div>
</aside>

<!-- ========== MAIN ========== -->
<main class="flex-1 overflow-y-auto" style="background:#020b14">

  <!-- HERO -->
  <section style="background:linear-gradient(135deg,#0d1f2d 0%,#061824 60%,#0a1118 100%);border-bottom:1px solid rgba(8,145,178,.2)" class="px-8 py-6">
    <div class="flex items-center gap-3 mb-1">
      <span style="background:rgba(0,242,255,.07);border:1px solid rgba(0,242,255,.2)" class="text-accent text-xs font-bold tracking-widest uppercase px-3 py-1 rounded-full">Live Conditions</span>
    </div>
    <h1 class="text-2xl font-black text-white mt-2">Sea Conditions <span class="text-accent">&amp; Forecast</span></h1>
    <p style="color:#64748b" class="text-sm mt-1">Wind &middot; Waves &middot; Ocean Currents &middot; SST &mdash; SE Queensland offshore</p>
  </section>

  <!-- LOCATION TABS (sticky) -->
  <div style="background:#0a1118;border-bottom:1px solid rgba(30,58,95,.5);position:sticky;top:0;z-index:20" class="px-5 py-3">
    <div id="loc-tabs" class="flex gap-2 overflow-x-auto pb-0.5" style="scrollbar-width:none">
      <button class="loc-btn active" onclick="selectLoc(0)">Brisbane Canyon</button>
      <button class="loc-btn" onclick="selectLoc(1)">Sunshine Coast</button>
      <button class="loc-btn" onclick="selectLoc(2)">North Reef</button>
      <button class="loc-btn" onclick="selectLoc(3)">Moreton Island</button>
      <button class="loc-btn" onclick="selectLoc(4)">Gold Coast</button>
      <button class="loc-btn" onclick="selectLoc(5)">Qld Seamount</button>
    </div>
  </div>

  <!-- WINDY MAP -->
  <div class="px-5 pt-5 pb-3">
    <div class="flex items-center gap-2 mb-3 flex-wrap">
      <span style="font-size:12px;color:#475569;margin-right:2px">Layer:</span>
      <button class="layer-btn active" data-layer="sst"      onclick="setLayer('sst')">SST</button>
      <button class="layer-btn"        data-layer="wind"     onclick="setLayer('wind')">Wind</button>
      <button class="layer-btn"        data-layer="waves"    onclick="setLayer('waves')">Waves</button>
      <button class="layer-btn"        data-layer="currents" onclick="setLayer('currents')">Currents</button>
      <button class="layer-btn"        data-layer="rain"     onclick="setLayer('rain')">Rain</button>
    </div>
    <div style="border-radius:12px;overflow:hidden;border:1px solid rgba(8,145,178,.3)">
      <iframe id="windy-frame" src="" allowfullscreen></iframe>
    </div>
    <p style="font-size:11px;color:#334155;margin-top:5px">
      Powered by <a href="https://windy.com" target="_blank" rel="noopener" style="color:#0369a1;text-decoration:none">Windy.com</a>
      &mdash; switch layers above &bull; SST shows sea-surface temperature &bull; Currents shows live EAC flow
    </p>
  </div>

  <!-- GO / NO-GO BANNER -->
  <div class="px-5 pb-3">
    <div id="go-nogo"></div>
  </div>

  <!-- CONDITIONS NOW (3 cards) -->
  <div class="px-5 pb-4">
    <div class="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">Current Conditions</div>
    <div id="conditions-now" class="grid gap-3 grid-3col" style="grid-template-columns:repeat(3,1fr)">
      <div class="card p-4 text-center py-8" style="grid-column:1/-1;color:#475569;font-size:13px">
        Loading forecast data&hellip;
      </div>
    </div>
  </div>

  <!-- BEST FISHING WINDOW -->
  <div id="best-window-wrap" style="display:none" class="px-5 pb-4">
    <div class="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">Best Fishing Window &mdash; Next 48h</div>
    <div id="best-window" class="card p-4"></div>
  </div>

  <!-- 48-HOUR TIMELINE -->
  <div class="px-5 pb-6">
    <div class="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">48-Hour Forecast</div>
    <div id="timeline" class="card overflow-x-auto" style="min-height:60px">
      <div style="padding:20px;color:#334155;font-size:12px;text-align:center">Loading&hellip;</div>
    </div>
  </div>

  <!-- API KEY NOTE (shown on demand) -->
  <div id="api-note" style="display:none" class="px-5 pb-6">
    <div style="background:rgba(120,53,15,.15);border:1px solid rgba(217,119,6,.4);border-radius:12px;padding:18px 22px">
      <div style="color:#fbbf24;font-weight:700;font-size:14px;margin-bottom:8px">&#9888;&#xFE0F; Forecast data requires a Windy API key</div>
      <p style="color:#94a3b8;font-size:13px;line-height:1.7">
        The Windy map above is <strong style="color:#e2e8f0">always free</strong> and shows live SST, wind, waves and currents visually.<br/>
        For numerical forecast values (wind speed in knots, wave height, EAC current speed) add your key to <code style="color:#67e8f9;font-size:12px">.env</code>:
      </p>
      <div style="background:#0a1118;border:1px solid rgba(30,58,95,.8);border-radius:8px;padding:12px 16px;margin:10px 0;font-family:monospace;font-size:12px;color:#67e8f9">
        WINDY_API_KEY=your_key_here
      </div>
      <p style="color:#64748b;font-size:12px;line-height:1.6">
        Get a free key at <a href="https://api.windy.com/keys" target="_blank" rel="noopener" style="color:#0ea5e9">api.windy.com/keys</a>
        (500&nbsp;req/day &mdash; free tier returns shuffled test data, not real forecasts).<br/>
        Professional plan (€990/yr, 10&nbsp;000&nbsp;req/day) provides real ECMWF-calibrated forecasts.
      </p>
    </div>
  </div>

  <!-- FOOTER -->
  <div style="border-top:1px solid rgba(30,58,95,.3);padding:14px 22px;color:#1e293b;font-size:11px">
    TunaTrack SEQ &mdash; Sea Conditions powered by Windy.com &bull; CMEMS ocean currents &bull; GFS wind &bull; gfsWave swell
  </div>

</main>

<!-- ========== JAVASCRIPT ========== -->
<script>
var LOCATIONS = [
  {name:'Brisbane Canyon', lat:-27.0,  lon:154.0},
  {name:'Sunshine Coast',  lat:-26.65, lon:153.85},
  {name:'North Reef',      lat:-26.4,  lon:153.7},
  {name:'Moreton Island',  lat:-27.1,  lon:153.6},
  {name:'Gold Coast',      lat:-27.95, lon:154.1},
  {name:'Qld Seamount',    lat:-26.5,  lon:155.0}
];

var activeLoc  = LOCATIONS[0];
var activeLayer = 'sst';

function windyUrl(lat, lon, layer) {
  return 'https://embed.windy.com/embed2.html?lat=' + lat + '&lon=' + lon +
    '&zoom=7&level=surface&overlay=' + layer +
    '&product=ecmwf&menu=&message=true&marker=true&calendar=now&pressure=' +
    '&type=map&location=coordinates&detail=&metricWind=kn&metricTemp=C&radarRange=-1';
}

function selectLoc(idx) {
  activeLoc = LOCATIONS[idx];
  var btns = document.getElementById('loc-tabs').querySelectorAll('.loc-btn');
  btns.forEach(function(b, i) { b.classList.toggle('active', i === idx); });
  document.getElementById('windy-frame').src = windyUrl(activeLoc.lat, activeLoc.lon, activeLayer);
  loadForecast(activeLoc.lat, activeLoc.lon, activeLoc.name);
}

function setLayer(layer) {
  activeLayer = layer;
  document.querySelectorAll('.layer-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.layer === layer);
  });
  document.getElementById('windy-frame').src = windyUrl(activeLoc.lat, activeLoc.lon, layer);
}

/* ---- helpers ---- */
var _dirs = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];
function compassDir(deg) {
  if (deg === null || deg === undefined) return '';
  return _dirs[Math.round(deg / 22.5) % 16];
}

function arrow(deg) {
  if (deg === null || deg === undefined) return '';
  return '<span style="display:inline-block;transform:rotate(' + deg + 'deg);font-size:15px;vertical-align:middle;margin-right:2px">&#8593;</span>';
}

function windCls(kt) {
  if (kt === null || kt === undefined) return 'curr-weak';
  return kt < 10 ? 'wind-good' : kt < 20 ? 'wind-ok' : kt < 30 ? 'wind-rough' : 'wind-bad';
}
function waveCls(h) {
  if (h === null || h === undefined) return 'curr-weak';
  return h < 1.0 ? 'wave-good' : h < 2.0 ? 'wave-ok' : h < 3.0 ? 'wave-rough' : 'wave-bad';
}
function currCls(kt) {
  if (kt === null || kt === undefined) return 'curr-weak';
  return kt >= 2.0 ? 'curr-strong' : kt >= 0.5 ? 'curr-active' : 'curr-weak';
}

function goNoGo(windKt, waveH) {
  var u = (windKt === null || windKt === undefined);
  var v = (waveH  === null || waveH  === undefined);
  if (u && v) return {label:'UNKNOWN', bg:'rgba(71,85,105,.15)', bd:'rgba(100,116,139,.4)', col:'#64748b', msg:'No forecast data — see API key note below'};
  var w = u ? 0 : windKt;
  var h = v ? 0 : waveH;
  if (w > 35 || h > 4)   return {label:'STAY ASHORE',  bg:'rgba(185,28,28,.15)',  bd:'rgba(239,68,68,.5)',  col:'#f87171', msg:'Dangerous offshore conditions &mdash; do not proceed'};
  if (w > 25 || h > 3)   return {label:'HIGH RISK',    bg:'rgba(154,52,18,.15)',  bd:'rgba(249,115,22,.5)', col:'#fb923c', msg:'Very rough seas &mdash; experienced crews only'};
  if (w > 20 || h > 2)   return {label:'USE CAUTION',  bg:'rgba(133,77,14,.15)',  bd:'rgba(234,179,8,.5)',  col:'#facc15', msg:'Moderate conditions &mdash; assess carefully before departure'};
  if (w > 15 || h > 1.5) return {label:'MODERATE',     bg:'rgba(20,83,45,.12)',   bd:'rgba(34,197,94,.35)', col:'#86efac', msg:'Manageable &mdash; suitable for capable vessels'};
  return                         {label:'GO FISHING',   bg:'rgba(6,78,59,.2)',     bd:'rgba(16,185,129,.5)', col:'#34d399', msg:'Excellent conditions for offshore yellowfin tuna'};
}

/* ---- card renderers ---- */
function renderWindCard(w) {
  if (!w) return noDataCard('Wind');
  var spd = w.wind_kt  !== null && w.wind_kt  !== undefined ? w.wind_kt  : '&mdash;';
  var dir = w.wind_dir !== null && w.wind_dir !== undefined ? compassDir(w.wind_dir) : '';
  var gst = w.gust_kt  !== null && w.gust_kt  !== undefined ? w.gust_kt  : '&mdash;';
  var cls = windCls(w.wind_kt);
  var capeLine = '';
  if (w.cape !== null && w.cape !== undefined) {
    var capCol = w.cape > 500 ? '#f87171' : w.cape > 100 ? '#fb923c' : '#475569';
    var capMsg = w.cape > 500 ? ' &mdash; storm risk' : w.cape > 100 ? ' &mdash; unstable' : '';
    capeLine = '<div style="font-size:11px;margin-top:5px;color:' + capCol + '">CAPE ' + w.cape + ' J/kg' + capMsg + '</div>';
  }
  return statCard('&#127788; Wind',
    '<span class="' + cls + '" style="font-size:2.2rem;font-weight:900;line-height:1">' + spd + '</span>' +
    '<span style="color:#64748b;font-size:13px;margin-left:4px">kt</span>' +
    '<div style="color:#94a3b8;font-size:13px;margin-top:5px">' + arrow(w.wind_dir) + dir + '</div>' +
    '<div style="color:#64748b;font-size:12px;margin-top:3px">Gusts: ' + gst + ' kt</div>' +
    capeLine
  );
}

function renderWaveCard(wv) {
  if (!wv) return noDataCard('Waves');
  var h  = wv.wave_h    !== null && wv.wave_h    !== undefined ? wv.wave_h    : '&mdash;';
  var p  = wv.wave_p    !== null && wv.wave_p    !== undefined ? wv.wave_p    : '&mdash;';
  var sh = wv.swell_h   !== null && wv.swell_h   !== undefined ? wv.swell_h   : '&mdash;';
  var sp = wv.swell_p   !== null && wv.swell_p   !== undefined ? wv.swell_p   : '&mdash;';
  var sd = wv.swell_dir !== null && wv.swell_dir !== undefined ? compassDir(wv.swell_dir) : '';
  var cls = waveCls(wv.wave_h);
  var pwrLine = wv.power_kw !== null && wv.power_kw !== undefined ?
    '<div style="color:#334155;font-size:11px;margin-top:4px">' + wv.power_kw + ' kW/m energy</div>' : '';
  return statCard('&#127754; Waves',
    '<span class="' + cls + '" style="font-size:2.2rem;font-weight:900;line-height:1">' + h + '</span>' +
    '<span style="color:#64748b;font-size:13px;margin-left:4px">m</span>' +
    '<div style="color:#94a3b8;font-size:13px;margin-top:5px">Period: ' + p + 's</div>' +
    '<div style="color:#64748b;font-size:12px;margin-top:3px">Swell ' + sh + 'm @ ' + sp + 's ' + sd + '</div>' +
    pwrLine
  );
}

function renderCurrentCard(c) {
  if (!c) return noDataCard('EAC Current');
  var spd  = c.current_kt  !== null && c.current_kt  !== undefined ? c.current_kt  : '&mdash;';
  var dir  = c.current_dir !== null && c.current_dir !== undefined ? compassDir(c.current_dir) : '';
  var tide = c.tide_kt     !== null && c.tide_kt     !== undefined ? c.tide_kt     : '&mdash;';
  var cls  = currCls(c.current_kt);
  var eacMsg = c.current_kt >= 2.0 ? 'Strong EAC &mdash; prime tuna-holding zone' :
               c.current_kt >= 0.5 ? 'Active current present' :
               'Weak current &mdash; check SST for boundaries';
  return statCard('&#127875; EAC Current',
    '<span class="' + cls + '" style="font-size:2.2rem;font-weight:900;line-height:1">' + spd + '</span>' +
    '<span style="color:#64748b;font-size:13px;margin-left:4px">kt</span>' +
    '<div style="color:#94a3b8;font-size:13px;margin-top:5px">' + arrow(c.current_dir) + 'flowing ' + dir + '</div>' +
    '<div style="color:#64748b;font-size:12px;margin-top:3px;line-height:1.5">' + eacMsg + '</div>' +
    '<div style="color:#334155;font-size:11px;margin-top:3px">Tidal: ' + tide + ' kt</div>'
  );
}

function statCard(title, body) {
  return '<div class="card p-4">' +
    '<div style="color:#64748b;font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin-bottom:10px">' + title + '</div>' +
    body + '</div>';
}

function noDataCard(title) {
  return statCard(title, '<div style="color:#475569;font-size:13px;padding:10px 0">No data</div>');
}

/* ---- timeline ---- */
function renderTimeline(wind, waves, currents) {
  var el = document.getElementById('timeline');
  if (!wind && !waves && !currents) { el.innerHTML = ''; return; }
  var ref = wind || waves || currents;
  var n = Math.min(ref.data.length, 16);

  var h = '<table style="width:100%;border-collapse:collapse">';
  h += '<thead><tr>';
  h += '<th class="tl-head" style="text-align:left;min-width:90px">Time</th>';
  h += '<th class="tl-head" style="text-align:center">Wind</th>';
  h += '<th class="tl-head" style="text-align:center">Dir</th>';
  h += '<th class="tl-head" style="text-align:center">Gust</th>';
  h += '<th class="tl-head" style="text-align:center">Wave</th>';
  h += '<th class="tl-head" style="text-align:center">Swell</th>';
  h += '<th class="tl-head" style="text-align:center">Current</th>';
  h += '<th class="tl-head" style="text-align:center">CAPE</th>';
  h += '</tr></thead><tbody>';

  for (var i = 0; i < n; i++) {
    var step = ref.data[i];
    var w  = wind     ? wind.data[i]     : null;
    var wv = waves    ? waves.data[i]    : null;
    var c  = currents ? currents.data[i] : null;

    var d = new Date(step.ts);
    var dayS  = d.toLocaleDateString('en-AU', {weekday:'short'});
    var timeS = d.toLocaleTimeString('en-AU', {hour:'2-digit', minute:'2-digit', hour12:false});

    var wk  = w  ? w.wind_kt    : null;
    var wdR = w  ? w.wind_dir   : null;
    var gk  = w  ? w.gust_kt    : null;
    var cp  = w  ? w.cape       : null;
    var wvH = wv ? wv.wave_h    : null;
    var wvP = wv ? wv.wave_p    : null;
    var svH = wv ? wv.swell_h   : null;
    var ck  = c  ? c.current_kt : null;

    var wCls  = windCls(wk);
    var wvCls = waveCls(wvH);
    var cCls  = currCls(ck);
    var cpCol = cp > 500 ? '#f87171' : cp > 100 ? '#fb923c' : '#475569';

    h += '<tr class="tl-row">';
    h += '<td class="tl-cell" style="color:#94a3b8">' + dayS + ' ' + timeS + '</td>';
    h += '<td class="tl-cell ' + wCls  + '" style="font-weight:700;text-align:center">' + (wk  !== null ? wk  + ' kt' : '&mdash;') + '</td>';
    h += '<td class="tl-cell" style="color:#475569;text-align:center">' + (wdR !== null ? compassDir(wdR) : '&mdash;') + '</td>';
    h += '<td class="tl-cell ' + wCls  + '" style="text-align:center">' + (gk  !== null ? gk  + ' kt' : '&mdash;') + '</td>';
    h += '<td class="tl-cell ' + wvCls + '" style="font-weight:700;text-align:center">' +
         (wvH !== null ? wvH + 'm' + (wvP !== null ? ' <span style="font-weight:400;color:#475569">@' + wvP + 's</span>' : '') : '&mdash;') + '</td>';
    h += '<td class="tl-cell ' + wvCls + '" style="text-align:center">' + (svH !== null ? svH + 'm' : '&mdash;') + '</td>';
    h += '<td class="tl-cell ' + cCls  + '" style="font-weight:700;text-align:center">' + (ck  !== null ? ck  + ' kt' : '&mdash;') + '</td>';
    h += '<td class="tl-cell" style="color:' + cpCol + ';text-align:center">' + (cp !== null ? cp : '&mdash;') + '</td>';
    h += '</tr>';
  }
  h += '</tbody></table>';
  el.innerHTML = h;
}

/* ---- best fishing window ---- */
function renderBestWindow(wind, waves) {
  if (!wind || !waves) return;
  var best = [];
  var n = Math.min(wind.data.length, waves.data.length, 16);
  for (var i = 0; i < n; i++) {
    var w = wind.data[i];
    var wv = waves.data[i];
    if (w.wind_kt !== null && wv.wave_h !== null && w.wind_kt <= 20 && wv.wave_h <= 2.0) {
      best.push({ts:w.ts, wind:w.wind_kt, wave:wv.wave_h});
    }
  }
  if (!best.length) return;
  document.getElementById('best-window-wrap').style.display = 'block';
  var bw = document.getElementById('best-window');
  var h = '<div style="color:#94a3b8;font-size:13px;margin-bottom:10px">Windows with wind &le;20&nbsp;kt and waves &le;2&nbsp;m:</div>';
  h += '<div style="display:flex;flex-wrap:wrap;gap:8px">';
  for (var j = 0; j < Math.min(best.length, 8); j++) {
    var it = best[j];
    var dd = new Date(it.ts);
    var ds = dd.toLocaleDateString('en-AU',{weekday:'short',month:'short',day:'numeric'}) + ' ' +
             dd.toLocaleTimeString('en-AU',{hour:'2-digit',minute:'2-digit',hour12:false});
    h += '<div style="background:rgba(6,78,59,.2);border:1px solid rgba(16,185,129,.3);border-radius:8px;padding:7px 13px">';
    h += '<div style="color:#34d399;font-weight:700;font-size:12px">' + ds + '</div>';
    h += '<div style="color:#64748b;font-size:11px">' + it.wind + ' kt wind &bull; ' + it.wave + ' m waves</div>';
    h += '</div>';
  }
  h += '</div>';
  bw.innerHTML = h;
}

/* ---- main fetch ---- */
async function loadForecast(lat, lon, locName) {
  var area     = document.getElementById('conditions-now');
  var timeline = document.getElementById('timeline');
  var gonogo   = document.getElementById('go-nogo');
  document.getElementById('best-window-wrap').style.display = 'none';

  area.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:30px;color:#475569;font-size:13px">Loading forecast for ' + locName + '&hellip;</div>';
  timeline.innerHTML = '<div style="padding:18px;color:#334155;font-size:12px;text-align:center">Loading&hellip;</div>';
  gonogo.innerHTML = '';

  try {
    var res = await fetch('/api/windy/forecast', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({lat:lat, lon:lon})
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var data = await res.json();

    /* Check for no-API-key error */
    if (data.errors) {
      var msgs = Object.values(data.errors);
      if (msgs.length > 0 && msgs[0].indexOf('WINDY_API_KEY') !== -1) {
        document.getElementById('api-note').style.display = 'block';
        area.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:30px">' +
          '<div style="color:#fbbf24;font-weight:700;font-size:14px;margin-bottom:8px">API Key Required</div>' +
          '<div style="color:#64748b;font-size:12px">Add <code style="color:#67e8f9">WINDY_API_KEY</code> to .env to see forecast values</div>' +
          '<div style="color:#334155;font-size:11px;margin-top:5px">The Windy map above always works without a key</div>' +
          '</div>';
        timeline.innerHTML = '';
        return;
      }
    }

    var wind     = (data.wind     && !(data.errors && data.errors.wind))     ? data.wind     : null;
    var waves    = (data.waves    && !(data.errors && data.errors.waves))    ? data.waves    : null;
    var currents = (data.currents && !(data.errors && data.errors.currents)) ? data.currents : null;

    var w0  = wind     ? wind.data[0]     : null;
    var wv0 = waves    ? waves.data[0]    : null;
    var c0  = currents ? currents.data[0] : null;

    /* Cards */
    area.innerHTML = renderWindCard(w0) + renderWaveCard(wv0) + renderCurrentCard(c0);

    /* Go/no-go */
    var gng = goNoGo(w0 ? w0.wind_kt : null, wv0 ? wv0.wave_h : null);
    gonogo.innerHTML = '<div style="background:' + gng.bg + ';border:1px solid ' + gng.bd + ';border-radius:12px;padding:14px 20px;display:flex;align-items:center;gap:16px">' +
      '<div style="color:' + gng.col + ';font-size:1.25rem;font-weight:900;white-space:nowrap">' + gng.label + '</div>' +
      '<div style="color:#94a3b8;font-size:13px">' + gng.msg + '</div></div>';

    /* Best window */
    renderBestWindow(wind, waves);

    /* Timeline */
    renderTimeline(wind, waves, currents);

    /* Show note if partial errors */
    if (data.errors && Object.keys(data.errors).length > 0) {
      document.getElementById('api-note').style.display = 'block';
    }

  } catch(e) {
    area.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:30px;color:#f87171;font-size:13px">Error: ' + e.message + '</div>';
    timeline.innerHTML = '';
  }
}

/* ---- init ---- */
selectLoc(0);
</script>
</body>
</html>'''
