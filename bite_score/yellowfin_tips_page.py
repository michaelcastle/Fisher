"""
"Yellowfin Tips" — full-screen premium educational guide page.
Served at GET /tips.  Pure static HTML/CSS/JS, no Python template variables.

Leaflet depth contours are indicative only (approximate shelf geometry).
Place any additional static images in the repo-root static/ folder.
"""

_HTML = """\
<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>How to Catch Yellowfin Tuna off Brisbane | TunaTrack SEQ</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{--yellow:#f59e0b;--cyan:#06b6d4;--navy:#060e17;--surface:#0c1926;--card:#102035;--border:rgba(255,255,255,0.07);}
*{box-sizing:border-box;margin:0;padding:0;}
html{scroll-behavior:smooth;}
body{background:var(--navy);color:#e2e8f0;font-family:'Inter',system-ui,sans-serif;overflow-x:hidden;}

/* SIDEBAR NAV */
.nav-active   { background:rgba(8,145,178,.2); border-right:4px solid #00f2ff; color:#00f2ff; font-weight:700; }
.nav-inactive { color:#94a3b8; transition:all .15s; }
.nav-inactive:hover { background:rgba(30,41,59,.8); color:#e2e8f0; }

/* SECTIONS */
.sec{padding:60px 24px;}
.sec-alt{background:var(--surface);}
.wrap{max-width:1200px;margin:0 auto;}
.sec-tag{font-size:11px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:var(--yellow);margin-bottom:8px;}
.sec-h{font-size:clamp(22px,3.5vw,38px);font-weight:900;letter-spacing:-.02em;color:#f1f5f9;line-height:1.1;margin-bottom:12px;}
.sec-sub{font-size:15px;color:#94a3b8;max-width:620px;line-height:1.65;margin-bottom:36px;}
section[id]{scroll-margin-top:12px;}

/* HERO */
#hero{min-height:100vh;display:flex;align-items:center;padding:120px 40px 80px;position:relative;overflow:hidden;}
.hero-bg{position:absolute;inset:0;background:radial-gradient(ellipse 130% 80% at 75% 20%, rgba(6,182,212,.14) 0%, transparent 55%), radial-gradient(ellipse 70% 50% at 15% 80%, rgba(245,158,11,.07) 0%, transparent 50%), linear-gradient(155deg,#060e17 0%,#081e30 55%,#060e17 100%);}
.hero-grid{position:absolute;inset:0;background-image:linear-gradient(rgba(6,182,212,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(6,182,212,.04) 1px,transparent 1px);background-size:60px 60px;}
.flow-wrap{position:absolute;top:0;right:0;width:55%;height:100%;pointer-events:none;overflow:hidden;}
.fl{position:absolute;width:1px;background:linear-gradient(to bottom,transparent,rgba(6,182,212,.5),transparent);animation:fsouth 3.5s linear infinite;}
.fl:nth-child(1){left:10%;height:45%;top:-5%;animation-delay:0s;}
.fl:nth-child(2){left:28%;height:35%;top:-5%;animation-delay:-.9s;opacity:.7;}
.fl:nth-child(3){left:48%;height:50%;top:-5%;animation-delay:-1.8s;}
.fl:nth-child(4){left:67%;height:38%;top:-5%;animation-delay:-1.2s;opacity:.6;}
.fl:nth-child(5){left:85%;height:42%;top:-5%;animation-delay:-2.6s;}
@keyframes fsouth{from{transform:translateY(0);opacity:0}15%{opacity:1}85%{opacity:1}to{transform:translateY(300%);opacity:0}}
.hero-content{position:relative;z-index:2;max-width:680px;}
.hero-badge{display:inline-block;background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.3);color:var(--yellow);font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;padding:5px 14px;border-radius:999px;margin-bottom:20px;}
.hero-h{font-size:clamp(32px,5.5vw,68px);font-weight:900;letter-spacing:-.03em;line-height:1.0;color:#fff;margin-bottom:12px;text-shadow:0 2px 40px rgba(6,182,212,.2);}
.hero-sub{font-size:clamp(15px,2vw,20px);color:#94a3b8;line-height:1.6;margin-bottom:10px;}
.hero-detail{font-size:13px;color:#475569;margin-bottom:36px;}
.hero-btn{display:inline-flex;align-items:center;gap:8px;background:var(--yellow);color:#0a1118;font-weight:800;font-size:14px;letter-spacing:.04em;padding:14px 28px;border-radius:10px;text-decoration:none;transition:transform .2s,box-shadow .2s;}
.hero-btn:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(245,158,11,.4);}
.hero-scroll{position:absolute;bottom:32px;left:50%;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center;gap:6px;color:#334155;font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;}
.scroll-dot{width:6px;height:6px;border-radius:50%;background:var(--cyan);animation:bounce 1.8s ease-in-out infinite;}
@keyframes bounce{0%,100%{transform:translateY(0)}50%{transform:translateY(8px)}}

/* CARDS */
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:24px;}
.card-sm{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px 20px;}
.card-hover{transition:transform .2s,border-color .2s;}
.card-hover:hover{transform:translateY(-4px);border-color:rgba(245,158,11,.3);}

/* SEASON TIMELINE */
.stab{padding:9px 18px;border-radius:8px;font-size:12px;font-weight:700;letter-spacing:.05em;cursor:pointer;border:1px solid var(--border);background:transparent;color:#475569;transition:all .2s;}
.stab.active{background:var(--yellow);color:#0a1118;border-color:var(--yellow);}
.stab:hover:not(.active){color:#e2e8f0;border-color:rgba(255,255,255,.15);}
.season-panel{display:none;animation:fadein .3s ease;}
.season-panel.show{display:block;}
@keyframes fadein{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* EAC DIAGRAM */
.eac-box{position:relative;width:100%;max-width:860px;height:auto;margin:0 auto;border:1px solid var(--border);border-radius:20px;overflow:hidden;background:#050e18;}
.coast-strip{position:absolute;left:0;top:0;bottom:0;width:110px;background:linear-gradient(to right,#0f1f0f,#091a0a);border-right:2px solid rgba(74,222,128,.25);}
.coast-lbl{position:absolute;left:0;width:110px;top:50%;transform:translateY(-50%) rotate(-90deg) translateX(-50%);font-size:9px;font-weight:700;letter-spacing:.25em;color:rgba(74,222,128,.4);text-transform:uppercase;transform-origin:center center;}
.temp-hot{position:absolute;left:110px;right:0;top:0;height:33%;background:linear-gradient(to bottom,rgba(239,68,68,.12),transparent);}
.temp-ideal{position:absolute;left:110px;right:0;top:33%;height:34%;background:rgba(16,185,129,.06);border-top:1px dashed rgba(16,185,129,.3);border-bottom:1px dashed rgba(16,185,129,.3);}
.temp-cool{position:absolute;left:110px;right:0;bottom:0;height:33%;background:linear-gradient(to top,rgba(59,130,246,.12),transparent);}
/* EAC arrows */
.eac-arr-col{position:absolute;left:230px;top:0;bottom:0;width:100px;display:flex;flex-direction:column;justify-content:space-around;align-items:center;}
.earr{font-size:22px;color:rgba(6,182,212,.75);animation:eflow 2.2s ease-in-out infinite;}
.earr:nth-child(2){animation-delay:-.75s;}
.earr:nth-child(3){animation-delay:-1.5s;}
@keyframes eflow{0%{transform:translateY(-8px);opacity:.3}50%{opacity:1}100%{transform:translateY(8px);opacity:.3}}
/* Upwelling rings */
.up-zone{position:absolute;left:130px;top:28px;width:78px;height:78px;}
.ur{position:absolute;border-radius:50%;border:1.5px solid rgba(16,185,129,.55);animation:cw 4s linear infinite;}
.ur:nth-child(1){inset:0;}
.ur:nth-child(2){inset:16px;border-color:rgba(16,185,129,.75);animation-duration:3s;}
.ur:nth-child(3){inset:30px;border-color:rgba(16,185,129,.95);animation-duration:2s;}
@keyframes cw{from{transform:rotate(0)}to{transform:rotate(360deg)}}
/* Downwelling rings */
.dw-zone{position:absolute;right:70px;bottom:36px;width:70px;height:70px;}
.dr{position:absolute;border-radius:50%;border:1.5px solid rgba(249,115,22,.55);animation:ccw 4s linear infinite;}
.dr:nth-child(1){inset:0;}
.dr:nth-child(2){inset:14px;border-color:rgba(249,115,22,.8);animation-duration:3s;}
@keyframes ccw{from{transform:rotate(0)}to{transform:rotate(-360deg)}}
/* Slack zone */
.slack-zone{position:absolute;right:50px;top:50%;transform:translateY(-50%);width:110px;height:130px;border:1px dashed rgba(245,158,11,.45);border-radius:14px;background:rgba(245,158,11,.04);}
/* E-W collision */
.ew-line{position:absolute;left:120px;right:50px;top:49.5%;height:2px;background:linear-gradient(to right,rgba(6,182,212,.8),rgba(245,158,11,.9),rgba(6,182,212,.8));animation:cpulse 2.5s ease-in-out infinite;}
@keyframes cpulse{0%,100%{opacity:.4;box-shadow:none}50%{opacity:1;box-shadow:0 0 10px rgba(245,158,11,.5)}}
/* EAC labels */
.elbl{position:absolute;background:rgba(0,0,0,.75);border:1px solid var(--border);border-radius:7px;padding:3px 8px;font-size:10px;font-weight:700;letter-spacing:.04em;white-space:nowrap;pointer-events:none;}

/* SST SLIDER */
.sst-track{height:36px;border-radius:18px;background:linear-gradient(to right,#1d4ed8 0%,#0284c7 16%,#0d9488 32%,#10b981 48%,#ca8a04 64%,#dc2626 80%,#991b1b 100%);position:relative;box-shadow:0 2px 16px rgba(0,0,0,.4);}
.sst-range{-webkit-appearance:none;appearance:none;position:absolute;inset:0;width:100%;background:transparent;cursor:pointer;}
.sst-range::-webkit-slider-thumb{-webkit-appearance:none;width:32px;height:32px;border-radius:50%;background:#fff;border:3px solid var(--navy);box-shadow:0 0 0 3px var(--yellow);cursor:pointer;margin-top:2px;}
.sst-marks{display:flex;justify-content:space-between;margin-top:8px;padding:0 2px;}
.sst-mark{font-size:10px;color:#475569;font-weight:600;}
.sst-readout{text-align:center;margin-top:16px;}
.sst-temp{font-size:48px;font-weight:900;letter-spacing:-.03em;}
.sst-desc{font-size:13px;color:#94a3b8;margin-top:4px;}

/* MOON */
.moon-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;}
.md{aspect-ratio:1;border-radius:8px;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:10px;font-weight:700;border:1px solid transparent;position:relative;}
.md .mn{font-size:15px;line-height:1;}
.md.best{background:rgba(16,185,129,.2);border-color:rgba(16,185,129,.4);color:#34d399;}
.md.good{background:rgba(16,185,129,.1);border-color:rgba(16,185,129,.25);color:#6ee7b7;}
.md.ok{background:rgba(245,158,11,.08);border-color:rgba(245,158,11,.2);color:#fbbf24;}
.md.poor{background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.2);color:#fca5a5;}
.md.bad{background:rgba(239,68,68,.2);border-color:rgba(239,68,68,.45);color:#ef4444;}
.md.neutral{background:rgba(255,255,255,.03);border-color:var(--border);color:#334155;}

/* WIND */
.wind-scene{position:relative;height:180px;background:#050e18;border:1px solid var(--border);border-radius:16px;overflow:hidden;display:flex;align-items:center;justify-content:center;}
.wind-compass{width:70px;height:70px;border-radius:50%;border:2px solid rgba(255,255,255,.1);display:flex;align-items:center;justify-content:center;position:relative;flex-shrink:0;}
.wind-arrow{position:absolute;font-size:28px;animation:blow 1.8s ease-in-out infinite;}
.wind-arrow:nth-child(2){animation-delay:-.6s;}
.wind-arrow:nth-child(3){animation-delay:-1.2s;}
@keyframes blow{from{transform:translateY(8px);opacity:0}30%{opacity:1}to{transform:translateY(-8px);opacity:0}}

/* CHECKLIST */
.ci{display:flex;align-items:center;gap:14px;padding:12px 16px;border-radius:12px;background:var(--card);border:1px solid var(--border);cursor:pointer;transition:all .2s;user-select:none;}
.ci:hover{border-color:rgba(245,158,11,.25);}
.ci.on{background:rgba(16,185,129,.07);border-color:rgba(16,185,129,.3);}
.cbox{width:22px;height:22px;border-radius:6px;border:2px solid #1e3448;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all .2s;font-size:13px;color:transparent;}
.ci.on .cbox{background:#10b981;border-color:#10b981;color:#fff;}
.score-bar-fill{height:100%;border-radius:999px;background:linear-gradient(to right,#10b981,#f59e0b);transition:width .4s ease;}

/* POSITIONING DIAGRAM */
.pos-dia{position:relative;max-width:460px;height:360px;margin:0 auto;background:#050e18;border:1px solid var(--border);border-radius:20px;overflow:hidden;}
.bust-ring{position:absolute;left:50%;top:45%;transform:translate(-50%,-50%);border-radius:50%;border:2px solid rgba(239,68,68,.5);}
.bust-ring.r1{width:100px;height:100px;background:rgba(239,68,68,.08);}
.bust-ring.r2{width:140px;height:140px;border-color:rgba(239,68,68,.25);background:transparent;animation:expand 3s ease-in-out infinite;}
.bust-ring.r3{width:180px;height:180px;border-color:rgba(239,68,68,.1);background:transparent;animation:expand 3s ease-in-out infinite;animation-delay:-.5s;}
@keyframes expand{0%,100%{opacity:.5;transform:translate(-50%,-50%) scale(1)}50%{opacity:1;transform:translate(-50%,-50%) scale(1.04)}}
.bust-label{position:absolute;left:50%;top:calc(45% - 8px);transform:translate(-50%,-50%);font-size:9px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:rgba(239,68,68,.8);}
.boat-icon{position:absolute;font-size:26px;animation:boat-arc 6s ease-in-out infinite;}
@keyframes boat-arc{0%{left:72%;top:72%;transform:rotate(200deg);}33%{left:78%;top:40%;transform:rotate(230deg);}66%{left:50%;top:15%;transform:rotate(270deg);}100%{left:22%;top:35%;transform:rotate(310deg);}}
.wind-ind{position:absolute;top:12px;right:12px;font-size:10px;color:rgba(6,182,212,.7);font-weight:700;}
.pos-note{position:absolute;bottom:12px;left:0;right:0;text-align:center;font-size:10px;color:#475569;padding:0 16px;}

/* ELECTRONICS */
.elec-display{background:#020b11;border:2px solid #0d2a3f;border-radius:14px;padding:24px;font-family:'Courier New',monospace;}
.elec-header{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid #0d2a3f;}
.elec-stat{text-align:center;}
.elec-stat-lbl{font-size:9px;color:#1e4d6b;font-weight:700;letter-spacing:.12em;text-transform:uppercase;margin-bottom:2px;}
.elec-stat-val{font-size:20px;color:#06b6d4;font-weight:700;}
.elec-stat-unit{font-size:9px;color:#1e4d6b;}
.temp-chart{height:100px;position:relative;border:1px solid #0d2a3f;border-radius:8px;overflow:hidden;background:#020b11;margin-bottom:12px;}
.temp-line{position:absolute;bottom:0;left:0;width:100%;height:100%;}

/* BIRD CARDS */
.bird-icon-bg{height:90px;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,rgba(6,182,212,.08),transparent);}

/* OCEAN READING CARDS */
.ocean-card{border-radius:14px;overflow:hidden;border:1px solid var(--border);transition:transform .2s,border-color .2s;}
.ocean-card:hover{transform:translateY(-4px);border-color:rgba(245,158,11,.3);}
.ocean-card-top{height:70px;display:flex;align-items:center;justify-content:center;font-size:36px;}
.ocean-card-body{padding:14px 16px;background:var(--card);}

/* MAP */
#fmap{height:500px;border-radius:16px;border:1px solid var(--border);overflow:hidden;}
.leaflet-container{background:#081520;}
.map-btn{padding:8px 16px;border-radius:8px;font-size:11px;font-weight:700;letter-spacing:.05em;cursor:pointer;transition:all .2s;border:1px solid var(--border);background:var(--card);color:#64748b;}
.map-btn.on{background:rgba(245,158,11,.15);border-color:rgba(245,158,11,.5);color:var(--yellow);}

@media(max-width:768px){
  .sec{padding:60px 16px;}
  .eac-box{height:auto;}
  #hero{padding:100px 24px 60px;}
  #fmap{height:380px;}
}
</style>
</head>
<body class="h-full flex overflow-hidden">

<!-- SIDEBAR -->
<aside style="width:220px;min-width:220px;background:#0f172a;border-right:1px solid rgba(30,41,59,.8)" class="flex flex-col h-screen sticky top-0 shrink-0">
  <div class="p-4" style="border-bottom:1px solid rgba(30,41,59,.8)">
    <a href="/" style="text-decoration:none">
      <h1 class="text-sm font-bold flex items-center gap-2" style="color:#00f2ff">
        <svg class="w-5 h-5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M21 12c0 0-3-6-9-6S3 12 3 12s3 6 9 6 9-6 9-6z" stroke-linecap="round"/>
          <circle cx="15" cy="12" r="1.5" fill="currentColor"/>
        </svg>
        TunaTrack<span style="color:#fff">SEQ</span>
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
    <a href="/tips" style="text-decoration:none" class="flex items-center gap-3 px-3 py-2.5 rounded-lg nav-active">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
      </svg>
      Yellowfin Tips
    </a>
    <a href="/conditions" style="text-decoration:none" class="flex items-center gap-3 px-3 py-2.5 rounded-lg nav-inactive">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
      </svg>
      Sea Conditions
    </a>
  </nav>
  <div class="p-4 text-xs" style="border-top:1px solid rgba(30,41,59,.8);color:#475569">
    SE Queensland<br/>Noosa &rarr; Gold Coast
  </div>
</aside>

<main class="flex-1 overflow-y-auto" style="background:var(--navy)">

<!-- HERO -->
<section id="hero">
  <div class="hero-bg"></div>
  <div class="hero-grid"></div>
  <div class="flow-wrap">
    <div class="fl"></div><div class="fl"></div><div class="fl"></div><div class="fl"></div><div class="fl"></div>
  </div>
  <div class="hero-content">
    <div class="hero-badge">Offshore SEQ Expert Guide</div>
    <h1 class="hero-h">Catching<br/>Yellowfin Tuna<br/><span style="color:var(--yellow)">off Brisbane</span></h1>
    <p class="hero-sub">Spring &mdash; September through November</p>
    <p class="hero-detail">60&ndash;80&nbsp;km offshore &bull; 500m&ndash;1000m+ &bull; East Australian Current</p>
    <p style="font-size:14px;color:#4b6480;max-width:520px;line-height:1.6;margin-bottom:32px;">
      Understanding the <strong style="color:#94a3b8">water</strong> is more important than understanding the fish.<br/>
      Get the conditions right and the tuna will find you.
    </p>
    <a href="#season" class="hero-btn">
      Start Learning
      <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M19 9l-7 7-7-7" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </a>
  </div>
  <div class="hero-scroll">
    <div class="scroll-dot"></div>
    scroll
  </div>
</section>

<!-- SECTION 1: SEASON -->
<section id="season" class="sec sec-alt">
  <div class="wrap">
    <div class="sec-tag">Section 01</div>
    <h2 class="sec-h">Seasonal Movement</h2>
    <p class="sec-sub">Yellowfin spend winter off Fraser Island before pushing south with the strengthening EAC in spring. Timing your trip to the peak window makes all the difference.</p>

    <!-- Month tabs -->
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:28px;">
      <button class="stab active" onclick="showSeason('jun-aug',this)">Jun&ndash;Aug</button>
      <button class="stab" onclick="showSeason('sep',this)">September</button>
      <button class="stab" onclick="showSeason('oct',this)">October</button>
      <button class="stab" onclick="showSeason('nov',this)">November</button>
    </div>

    <div id="sp-jun-aug" class="season-panel show">
      <div class="grid md:grid-cols-3 gap-5">
        <div class="card"><div class="text-3xl mb-3">&#128313;</div><h4 style="font-weight:800;color:#f1f5f9;margin-bottom:8px;">Fraser Island</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">Yellowfin holding north of Brisbane, mainly off Fraser Island. The EAC hasn&rsquo;t fully pushed south yet. Early-season fish available but numbers are lower.</p></div>
        <div class="card"><div class="text-3xl mb-3">&#127790;</div><h4 style="font-weight:800;color:#f1f5f9;margin-bottom:8px;">Offshore Range</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">Typical range 60&ndash;100&nbsp;km offshore. Fish associating with the northern end of the EAC warm-water eddy system forming around Swain Reefs.</p></div>
        <div class="card"><div class="text-3xl mb-3">&#127777;</div><h4 style="font-weight:800;color:#f1f5f9;margin-bottom:8px;">Conditions</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">Water temps building toward the ideal 23&ndash;26&deg;C window. Northerly winds can be patchy. Worth targeting but October/November is prime.</p></div>
      </div>
    </div>

    <div id="sp-sep" class="season-panel">
      <div class="grid md:grid-cols-3 gap-5">
        <div class="card" style="border-color:rgba(245,158,11,.25)"><div class="text-3xl mb-3">&#8594;</div><h4 style="font-weight:800;color:var(--yellow);margin-bottom:8px;">Migration South Begins</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">Schools start moving down the coast. First fish showing off the Sunshine Coast. EAC strengthening and pushing warmer water into the zone.</p></div>
        <div class="card"><div class="text-3xl mb-3">&#127851;</div><h4 style="font-weight:800;color:#f1f5f9;margin-bottom:8px;">Temperature Trigger</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">SST reaches the 23&ndash;26&deg;C window. Bait schools building. Birds starting to work. Late September can produce excellent fishing.</p></div>
        <div class="card"><div class="text-3xl mb-3">&#128506;</div><h4 style="font-weight:800;color:#f1f5f9;margin-bottom:8px;">Where to Look</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">Focus north of Brisbane initially. The 500m contour off Noosa and Double Island Point. Watch for the first temperature breaks forming on satellite imagery.</p></div>
      </div>
    </div>

    <div id="sp-oct" class="season-panel">
      <div class="grid md:grid-cols-3 gap-5">
        <div class="card" style="border-color:rgba(16,185,129,.3);background:rgba(16,185,129,.05)"><div class="text-3xl mb-3">&#11088;</div><h4 style="font-weight:800;color:#34d399;margin-bottom:8px;">Peak Numbers</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">Prime time. Schools between Brisbane and the Gold Coast. EAC in full force. The entire system from Noosa to Stradbroke Island producing fish.</p></div>
        <div class="card"><div class="text-3xl mb-3">&#127794;</div><h4 style="font-weight:800;color:#f1f5f9;margin-bottom:8px;">EAC at its Best</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">Maximum temperature differentiation between EAC core and adjacent waters. Upwelling zones most active. Best bait concentrations of the year.</p></div>
        <div class="card"><div class="text-3xl mb-3">&#128064;</div><h4 style="font-weight:800;color:#f1f5f9;margin-bottom:8px;">Wider Distribution</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">Fish found from Cape Moreton south to the NSW border. The 500m&ndash;1000m range consistently producing. Best month of the year.</p></div>
      </div>
    </div>

    <div id="sp-nov" class="season-panel">
      <div class="grid md:grid-cols-3 gap-5">
        <div class="card"><div class="text-3xl mb-3">&#127807;</div><h4 style="font-weight:800;color:#f1f5f9;margin-bottom:8px;">Last of the Migration</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">Fish continuing south. Some very large specimens late in the season as bigger fish follow the main schools. Season begins winding down late November.</p></div>
        <div class="card"><div class="text-3xl mb-3">&#127758;</div><h4 style="font-weight:800;color:#f1f5f9;margin-bottom:8px;">Further South</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">Action shifts toward NSW border. Byron Bay and northern NSW start producing as the main body of fish pushes through. Longer runs required from Brisbane.</p></div>
        <div class="card"><div class="text-3xl mb-3">&#9201;</div><h4 style="font-weight:800;color:#f1f5f9;margin-bottom:8px;">Don&rsquo;t Miss It</h4><p style="font-size:14px;color:#94a3b8;line-height:1.6;">November can surprise. A late push of warm water can produce exceptional fishing right up to the end of the month. Watch SST and chlorophyll overlays on the Live Map.</p></div>
      </div>
    </div>

    <!-- Simple visual timeline -->
    <div class="card" style="margin-top:24px;padding:20px 24px;">
      <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:0;position:relative;">
        <div style="grid-column:1/3;padding:12px;text-align:center;background:rgba(255,255,255,.03);border-radius:10px 0 0 10px;border:1px solid var(--border);">
          <div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:#475569;text-transform:uppercase;margin-bottom:4px;">Jun &bull; Jul &bull; Aug</div>
          <div style="font-size:12px;color:#64748b;">Fraser Island</div>
          <div style="margin-top:8px;height:4px;border-radius:2px;background:rgba(245,158,11,.25);"></div>
        </div>
        <div style="grid-column:3/4;padding:12px;text-align:center;border:1px solid rgba(245,158,11,.2);background:rgba(245,158,11,.04);">
          <div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(245,158,11,.7);text-transform:uppercase;margin-bottom:4px;">September</div>
          <div style="font-size:12px;color:#94a3b8;">Moving South</div>
          <div style="margin-top:8px;height:4px;border-radius:2px;background:rgba(245,158,11,.5);"></div>
        </div>
        <div style="grid-column:4/5;padding:12px;text-align:center;border:1px solid rgba(16,185,129,.3);background:rgba(16,185,129,.07);">
          <div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:#34d399;text-transform:uppercase;margin-bottom:4px;">October &#11088;</div>
          <div style="font-size:12px;color:#94a3b8;">Peak Season</div>
          <div style="margin-top:8px;height:4px;border-radius:2px;background:#10b981;"></div>
        </div>
        <div style="grid-column:5/6;padding:12px;text-align:center;border:1px solid rgba(245,158,11,.2);background:rgba(245,158,11,.04);">
          <div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(245,158,11,.7);text-transform:uppercase;margin-bottom:4px;">November</div>
          <div style="font-size:12px;color:#94a3b8;">Pushing South</div>
          <div style="margin-top:8px;height:4px;border-radius:2px;background:rgba(245,158,11,.4);"></div>
        </div>
        <div style="grid-column:6/7;padding:12px;text-align:center;background:rgba(255,255,255,.02);border-radius:0 10px 10px 0;border:1px solid var(--border);">
          <div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:#334155;text-transform:uppercase;margin-bottom:4px;">Dec +</div>
          <div style="font-size:12px;color:#334155;">NSW</div>
          <div style="margin-top:8px;height:4px;border-radius:2px;background:rgba(255,255,255,.05);"></div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- SECTION 2: EAC -->
<section id="eac" class="sec">
  <div class="wrap">
    <div class="sec-tag">Section 02</div>
    <h2 class="sec-h">Reading the East Australian Current</h2>
    <p class="sec-sub">The EAC is the engine that drives everything. Understanding its structure &mdash; where it pushes, stalls, upwells and collides &mdash; tells you exactly where to find fish.</p>

    <div class="eac-box">
      <img src="/static/Section2.png"
           alt="EAC structure diagram showing upwelling, downwelling, slack water and east-west current collision zones"
           style="width:100%;height:auto;display:block;"
           onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"/>
      <div style="display:none;align-items:center;justify-content:center;height:300px;color:#334155;font-size:13px;">Section2.png not found in static/</div>
    </div>

    <div class="grid md:grid-cols-4 gap-4" style="margin-top:24px;">
      <div class="card-sm" style="border-color:rgba(16,185,129,.25)">
        <div style="color:#34d399;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px;">&#8593; Upwelling</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Clockwise rotation. Cold, nutrient-rich water rises. Food and bait concentrate near the surface. &minus;10 to the Line of Zero is the ideal window.</p>
      </div>
      <div class="card-sm" style="border-color:rgba(249,115,22,.25)">
        <div style="color:#fb923c;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px;">&#8595; Downwelling</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Anti-clockwise rotation. OK for 2&ndash;4 days before it slows. Still holds fish early. Once fully established the bite generally dies.</p>
      </div>
      <div class="card-sm" style="border-color:rgba(245,158,11,.25)">
        <div style="color:var(--yellow);font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px;">&#8651; E&rarr;W Collision</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Where east-to-west current crashes into the south-flowing EAC. A prime focal point. Bait and tuna stack on the eastern (slack) side.</p>
      </div>
      <div class="card-sm" style="border-color:rgba(6,182,212,.25)">
        <div style="color:var(--cyan);font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px;">&#9660; Slack Water</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">The eastern edge of the EAC where flow slows. Tuna hold and feed here. Generally the most productive zone in the entire system.</p>
      </div>
    </div>
  </div>
</section>

<!-- SECTION 3: FINDING WATER -->
<section id="water" class="sec sec-alt">
  <div class="wrap">
    <div class="sec-tag">Section 03</div>
    <h2 class="sec-h">Finding the Best Water</h2>
    <p class="sec-sub">Four layers tell the whole story. Use TunaTrack SEQ&rsquo;s Live Map to overlay these on each other and pinpoint your start point before you leave the ramp.</p>

    <!-- Layer cards -->
    <div class="grid md:grid-cols-2 lg:grid-cols-4 gap-5" style="margin-bottom:28px;">
      <div class="card card-hover">
        <div style="font-size:36px;margin-bottom:12px;">&#127777;</div>
        <h3 style="font-size:16px;font-weight:800;color:#f1f5f9;margin-bottom:8px;">Sea Surface Temp</h3>
        <div style="display:inline-block;background:rgba(16,185,129,.15);border:1px solid rgba(16,185,129,.3);color:#34d399;font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;margin-bottom:8px;">Best: 23&ndash;26&deg;C</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Don&rsquo;t chase a number. Find the <strong style="color:#e2e8f0">break</strong>. The line between warm and cold is where bait concentrates and tuna hunt. Eastern EAC edge is the money zone.</p>
      </div>
      <div class="card card-hover">
        <div style="font-size:36px;margin-bottom:12px;">&#127774;</div>
        <h3 style="font-size:16px;font-weight:800;color:#f1f5f9;margin-bottom:8px;">Bathymetry</h3>
        <div style="display:inline-block;background:rgba(6,182,212,.12);border:1px solid rgba(6,182,212,.3);color:var(--cyan);font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;margin-bottom:8px;">Best: 500m&ndash;1000m+</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Deep structure deflects current, creates upwelling and concentrates bait. Past 500m&nbsp;is your minimum. 1000m is where the serious fishing happens.</p>
      </div>
      <div class="card card-hover">
        <div style="font-size:36px;margin-bottom:12px;">&#127803;</div>
        <h3 style="font-size:16px;font-weight:800;color:#f1f5f9;margin-bottom:8px;">Chlorophyll</h3>
        <div style="display:inline-block;background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.25);color:#6ee7b7;font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;margin-bottom:8px;">Find the edges</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">High chlorophyll = upwelling = bait food. The edges of chlorophyll blooms are often the richest feeding zones. Tuna follow the bait that follows the nutrients.</p>
      </div>
      <div class="card card-hover">
        <div style="font-size:36px;margin-bottom:12px;">&#127739;</div>
        <h3 style="font-size:16px;font-weight:800;color:#f1f5f9;margin-bottom:8px;">Currents</h3>
        <div style="display:inline-block;background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.25);color:var(--yellow);font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;margin-bottom:8px;">Find the collision</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Look for where currents change direction or collide. East-to-west flows hitting the EAC are prime focal points. Also look for current rings and eddies.</p>
      </div>
    </div>

    <!-- Water colour guide -->
    <div class="card" style="padding:28px;">
      <h3 style="font-size:18px;font-weight:800;color:#f1f5f9;margin-bottom:20px;">Reading Water Colour on the Day</h3>
      <div class="grid md:grid-cols-3 gap-5">
        <div style="padding:16px;border-radius:12px;background:rgba(29,78,216,.15);border:1px solid rgba(29,78,216,.3);">
          <div style="font-size:24px;margin-bottom:8px;">&#128309;</div>
          <h4 style="font-size:14px;font-weight:800;color:#93c5fd;margin-bottom:6px;">Blue Water &mdash; Good</h4>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Clear, deep blue. Offshore EAC water. Low nutrients but high visibility. Tuna are comfortable here. Find the bait schools and you&rsquo;ll find yellowfin.</p>
        </div>
        <div style="padding:16px;border-radius:12px;background:rgba(5,150,105,.12);border:1px solid rgba(5,150,105,.25);">
          <div style="font-size:24px;margin-bottom:8px;">&#128994;</div>
          <h4 style="font-size:14px;font-weight:800;color:#6ee7b7;margin-bottom:6px;">Green Water &mdash; Good</h4>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Upwelling bringing nutrients. Rich bait concentrations. Often found at temperature breaks and current edges. Where blue meets green is very productive.</p>
        </div>
        <div style="padding:16px;border-radius:12px;background:rgba(120,53,15,.15);border:1px solid rgba(120,53,15,.3);">
          <div style="font-size:24px;margin-bottom:8px;">&#128997;</div>
          <h4 style="font-size:14px;font-weight:800;color:#fbbf24;margin-bottom:6px;">Brown/Murky &mdash; Avoid</h4>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Coastal runoff or heavy sedimentation. Low visibility. Tuna avoid this water. Move further offshore or find the clean-water edge.</p>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- SECTION 4: SST SLIDER -->
<section id="sst" class="sec" style="display:none"><!-- collapsed into Section 3 --></section>

<!-- SECTION 5: ELECTRONICS -->
<section id="electronics" class="sec sec-alt">
  <div class="wrap">
    <div class="sec-tag">Section 04</div>
    <h2 class="sec-h">Electronics &amp; Sounding</h2>
    <p class="sec-sub">Your sounder and chartplotter are your most important tools once offshore. Here&rsquo;s what to look for as you run across the EAC.</p>

    <div class="grid md:grid-cols-2 gap-8 items-start">

      <!-- Sounder display mockup -->
      <div class="elec-display">
        <div class="elec-header">
          <div class="elec-stat"><div class="elec-stat-lbl">SOG</div><div class="elec-stat-val">18.4<span class="elec-stat-unit"> kt</span></div></div>
          <div class="elec-stat"><div class="elec-stat-lbl">TEMP</div><div class="elec-stat-val" id="elec-temp" style="color:#10b981;">24.1<span class="elec-stat-unit"> &deg;C</span></div></div>
          <div class="elec-stat"><div class="elec-stat-lbl">DEPTH</div><div class="elec-stat-val">842<span class="elec-stat-unit"> m</span></div></div>
          <div class="elec-stat"><div class="elec-stat-lbl">HDG</div><div class="elec-stat-val" style="color:#f59e0b;">087<span class="elec-stat-unit"> &deg;T</span></div></div>
        </div>
        <!-- Temperature trace -->
        <div class="temp-chart">
          <svg width="100%" height="100%" viewBox="0 0 400 100" preserveAspectRatio="none">
            <!-- Background grid -->
            <line x1="0" y1="25" x2="400" y2="25" stroke="#0d2a3f" stroke-width="1"/>
            <line x1="0" y1="50" x2="400" y2="50" stroke="#0d2a3f" stroke-width="1"/>
            <line x1="0" y1="75" x2="400" y2="75" stroke="#0d2a3f" stroke-width="1"/>
            <!-- Temp line: rises, peaks, drops, EAC crossing, finds cool edge -->
            <polyline points="0,70 40,65 80,55 110,42 130,35 150,30 170,32 200,40 230,52 260,62 290,55 320,45 360,50 400,48"
              fill="none" stroke="#06b6d4" stroke-width="2"/>
            <!-- Highlight ideal zone -->
            <rect x="0" y="25" width="400" height="25" fill="rgba(16,185,129,0.06)"/>
            <!-- Annotations -->
            <text x="10" y="95" font-size="8" fill="#1e4d6b" font-family="Courier New">START</text>
            <text x="110" y="12" font-size="8" fill="#f59e0b" font-family="Courier New">TEMP PEAK 26.2&deg;</text>
            <text x="240" y="95" font-size="8" fill="#1e4d6b" font-family="Courier New">EAC CROSS</text>
            <text x="330" y="28" font-size="8" fill="#10b981" font-family="Courier New">COOL EDGE</text>
          </svg>
        </div>
        <div style="margin-top:10px;font-size:10px;color:#1e4d6b;line-height:1.5;">
          &mdash; SURFACE TEMPERATURE TRACE &mdash;<br/>
          <span style="color:#06b6d4;">LIVE</span> &bull; EAC TRANSIT LOG
        </div>
      </div>

      <!-- Step-by-step explanation -->
      <div class="space-y-3">
        <div class="card-sm" style="border-color:rgba(6,182,212,.2)">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
            <span style="background:rgba(6,182,212,.15);color:var(--cyan);font-size:11px;font-weight:800;padding:2px 8px;border-radius:4px;">STEP 1</span>
            <span style="font-size:13px;font-weight:700;color:#e2e8f0;">Watch temp rise as you go offshore</span>
          </div>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">As you cross into the EAC influence zone, surface temp climbs. This is the warm-water core pushing south.</p>
        </div>
        <div class="card-sm" style="border-color:rgba(245,158,11,.2)">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
            <span style="background:rgba(245,158,11,.15);color:var(--yellow);font-size:11px;font-weight:800;padding:2px 8px;border-radius:4px;">STEP 2</span>
            <span style="font-size:13px;font-weight:700;color:#e2e8f0;">Find the peak then watch for the drop</span>
          </div>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Temp will plateau then start to fall. This is the eastern edge of the EAC &mdash; a natural temperature break. Mark this GPS position.</p>
        </div>
        <div class="card-sm" style="border-color:rgba(16,185,129,.2)">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
            <span style="background:rgba(16,185,129,.15);color:#34d399;font-size:11px;font-weight:800;padding:2px 8px;border-radius:4px;">STEP 3</span>
            <span style="font-size:13px;font-weight:700;color:#e2e8f0;">Cross over and find the cool edge</span>
          </div>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Go past the drop, note the cooler water, then come back to fish the transition zone. The cool-edge side of the break is often the most productive.</p>
        </div>
        <div class="card-sm">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
            <span style="background:rgba(255,255,255,.05);color:#64748b;font-size:11px;font-weight:800;padding:2px 8px;border-radius:4px;">ALSO</span>
            <span style="font-size:13px;font-weight:700;color:#e2e8f0;">Read the bait on sounder</span>
          </div>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Look for bait balls suspended in the water column, especially 20&ndash;60m down. Tuna will be directly above or nearby, herding them toward the surface.</p>
        </div>
      </div>

    </div>
  </div>
</section>

<!-- SECTION 6: MOON & WEATHER -->
<section id="moon" class="sec">
  <div class="wrap">
    <div class="sec-tag">Section 05</div>
    <h2 class="sec-h">Moon Phase &amp; Weather</h2>
    <p class="sec-sub">The moon drives feeding activity offshore. Combined with wind direction, these two factors can make or break your day before you even reach the grounds.</p>

    <div class="grid md:grid-cols-2 gap-8">

      <!-- Moon calendar (30-day legend-style) -->
      <div>
        <h3 style="font-size:16px;font-weight:800;color:#f1f5f9;margin-bottom:4px;">Monthly Moon Cycle</h3>
        <p style="font-size:12px;color:#64748b;margin-bottom:16px;">Typical 30-day cycle &mdash; relative rating for fishing offshore yellowfin</p>
        <div class="moon-grid" id="moon-cal"></div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:14px;">
          <div style="display:flex;align-items:center;gap:6px;font-size:11px;"><div style="width:12px;height:12px;border-radius:3px;background:rgba(16,185,129,.2);border:1px solid rgba(16,185,129,.4);"></div><span style="color:#64748b;">Best</span></div>
          <div style="display:flex;align-items:center;gap:6px;font-size:11px;"><div style="width:12px;height:12px;border-radius:3px;background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.25);"></div><span style="color:#64748b;">Good</span></div>
          <div style="display:flex;align-items:center;gap:6px;font-size:11px;"><div style="width:12px;height:12px;border-radius:3px;background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2);"></div><span style="color:#64748b;">OK</span></div>
          <div style="display:flex;align-items:center;gap:6px;font-size:11px;"><div style="width:12px;height:12px;border-radius:3px;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.2);"></div><span style="color:#64748b;">Poor</span></div>
          <div style="display:flex;align-items:center;gap:6px;font-size:11px;"><div style="width:12px;height:12px;border-radius:3px;background:rgba(239,68,68,.2);border:1px solid rgba(239,68,68,.4);"></div><span style="color:#64748b;">Bad</span></div>
        </div>
        <div style="margin-top:16px;padding:14px 16px;border-radius:10px;background:rgba(245,158,11,.06);border:1px solid rgba(245,158,11,.2);">
          <p style="font-size:12px;color:#94a3b8;line-height:1.6;"><strong style="color:var(--yellow);">Key rule:</strong> The lead-up to full moon (days 11&ndash;14) is almost always the best fishing. The full moon day itself is typically poor. A couple of days after is OK. Major and minor moon windows apply throughout the month.</p>
        </div>
      </div>

      <!-- Wind guide -->
      <div>
        <h3 style="font-size:16px;font-weight:800;color:#f1f5f9;margin-bottom:4px;">Wind Direction Guide</h3>
        <p style="font-size:12px;color:#64748b;margin-bottom:16px;">Spring (Sep&ndash;Nov) &mdash; SEQ offshore conditions</p>

        <div class="grid grid-cols-2 gap-4 mb-4">
          <!-- North wind (good) -->
          <div style="padding:16px;border-radius:14px;background:rgba(16,185,129,.07);border:1px solid rgba(16,185,129,.25);">
            <div style="display:flex;justify-content:center;margin-bottom:12px;height:60px;position:relative;overflow:hidden;border-radius:8px;background:#050e18;">
              <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;">
                <div style="font-size:20px;color:#34d399;animation:blowdown 1.5s ease-in-out infinite;">&#8595;</div>
                <div style="font-size:20px;color:#34d399;animation:blowdown 1.5s ease-in-out infinite;animation-delay:-.5s;">&#8595;</div>
              </div>
            </div>
            <div style="font-size:13px;font-weight:800;color:#34d399;margin-bottom:4px;">&#10004; NORTHERLY</div>
            <p style="font-size:11px;color:#64748b;line-height:1.5;">Both tuna and birds head <em>into</em> the wind. Schools stay organised and predictable. Bait holds together. Easiest conditions to find and stay on fish.</p>
          </div>
          <!-- South wind (bad) -->
          <div style="padding:16px;border-radius:14px;background:rgba(239,68,68,.07);border:1px solid rgba(239,68,68,.25);">
            <div style="display:flex;justify-content:center;margin-bottom:12px;height:60px;position:relative;overflow:hidden;border-radius:8px;background:#050e18;">
              <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;">
                <div style="font-size:20px;color:#ef4444;animation:blowup 1.5s ease-in-out infinite;">&#8593;</div>
                <div style="font-size:20px;color:#ef4444;animation:blowup 1.5s ease-in-out infinite;animation-delay:-.5s;">&#8593;</div>
              </div>
            </div>
            <div style="font-size:13px;font-weight:800;color:#ef4444;margin-bottom:4px;">&#10006; SOUTHERLY</div>
            <p style="font-size:11px;color:#64748b;line-height:1.5;">Often associated with change in temperature and disrupted feeding. Schools scatter. Fishing generally slows significantly. Wait it out if possible.</p>
          </div>
        </div>

        @keyframes blowdown{from{transform:translateY(-6px);opacity:0}50%{opacity:1}to{transform:translateY(6px);opacity:0}}
        @keyframes blowup{from{transform:translateY(6px);opacity:0}50%{opacity:1}to{transform:translateY(-6px);opacity:0}}

        <div class="card-sm">
          <p style="font-size:13px;color:#94a3b8;line-height:1.6;"><strong style="color:#e2e8f0;">Why north wind wins:</strong> In spring, north winds align with the predominant tuna feeding direction. Birds work into the wind making them easier to track. Fish move more predictably in a straight line making them easier to intercept.</p>
        </div>

        <!-- SST slider - moved here for context -->
        <div style="margin-top:16px;">
          <h3 style="font-size:14px;font-weight:800;color:#f1f5f9;margin-bottom:12px;">SST Finder &mdash; drag to explore</h3>
          <div class="sst-track">
            <input type="range" class="sst-range" id="sst-slider" min="21" max="28" value="24" step="0.5" oninput="updateSST(this.value)"/>
          </div>
          <div class="sst-marks"><span class="sst-mark">21&deg;</span><span class="sst-mark">22&deg;</span><span class="sst-mark">23&deg;</span><span class="sst-mark">24&deg;</span><span class="sst-mark">25&deg;</span><span class="sst-mark">26&deg;</span><span class="sst-mark">27&deg;</span><span class="sst-mark">28&deg;</span></div>
          <div class="sst-readout">
            <div class="sst-temp" id="sst-temp-val" style="color:#10b981;">24.0&deg;C</div>
            <div class="sst-desc" id="sst-desc">Ideal temperature &mdash; prime yellowfin zone. Look for a break here.</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- SECTION 7: ON THE WATER -->
<section id="on-water" class="sec sec-alt">
  <div class="wrap">
    <div class="sec-tag">Section 06</div>
    <h2 class="sec-h">Reading the Ocean on the Day</h2>
    <p class="sec-sub">Once you&rsquo;re offshore, these are the real-time signs that tell you fish are nearby. Learn to read them quickly and you&rsquo;ll spend more time with hooks in the water.</p>

    <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div class="ocean-card">
        <div class="ocean-card-top" style="background:linear-gradient(135deg,rgba(6,182,212,.15),var(--card));">&#128031;</div>
        <div class="ocean-card-body">
          <h4 style="font-size:14px;font-weight:800;color:#f1f5f9;margin-bottom:6px;">Birds Diving</h4>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Birds diving into the water is the strongest sign of a bust-up below. Get upwind and wide. Don&rsquo;t drive through it.</p>
        </div>
      </div>
      <div class="ocean-card">
        <div class="ocean-card-top" style="background:linear-gradient(135deg,rgba(6,182,212,.1),var(--card));">&#128031; &#128031;</div>
        <div class="ocean-card-body">
          <h4 style="font-size:14px;font-weight:800;color:#f1f5f9;margin-bottom:6px;">Bird Tracks</h4>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">A line of birds flying in one direction tells you where the school is heading. Follow their track to intercept the fish ahead of them.</p>
        </div>
      </div>
      <div class="ocean-card">
        <div class="ocean-card-top" style="background:linear-gradient(135deg,rgba(245,158,11,.1),var(--card));">&#127754;</div>
        <div class="ocean-card-body">
          <h4 style="font-size:14px;font-weight:800;color:#f1f5f9;margin-bottom:6px;">Surface Bait</h4>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Baitfish on the surface means they&rsquo;re being pushed up from below. Tuna are directly underneath. Approach carefully and present lures quickly.</p>
        </div>
      </div>
      <div class="ocean-card">
        <div class="ocean-card-top" style="background:linear-gradient(135deg,rgba(239,68,68,.1),var(--card));">&#128165;</div>
        <div class="ocean-card-body">
          <h4 style="font-size:14px;font-weight:800;color:#f1f5f9;margin-bottom:6px;">Bust-Ups</h4>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Tuna crashing bait on the surface. Highly visual event. Work wide of it, let it come to you. Bust-ups are often short-lived so be ready to cast immediately.</p>
        </div>
      </div>
      <div class="ocean-card">
        <div class="ocean-card-top" style="background:linear-gradient(135deg,rgba(29,78,216,.12),var(--card));">&#129445;</div>
        <div class="ocean-card-body">
          <h4 style="font-size:14px;font-weight:800;color:#f1f5f9;margin-bottom:6px;">Pilot Whales</h4>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Pilot whales and false killer whales eat tuna. When you see them, tuna are nearby. Stay in the area and watch for surface activity around the whale group.</p>
        </div>
      </div>
      <div class="ocean-card">
        <div class="ocean-card-top" style="background:linear-gradient(135deg,rgba(6,182,212,.08),var(--card));">&#127754;</div>
        <div class="ocean-card-body">
          <h4 style="font-size:14px;font-weight:800;color:#f1f5f9;margin-bottom:6px;">Current Lines</h4>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Visible lines of foam or debris on the surface mark where two currents meet. These convergence zones concentrate bait. Fish along them.</p>
        </div>
      </div>
      <div class="ocean-card">
        <div class="ocean-card-top" style="background:linear-gradient(135deg,rgba(29,78,216,.15),var(--card));">&#128309;</div>
        <div class="ocean-card-body">
          <h4 style="font-size:14px;font-weight:800;color:#f1f5f9;margin-bottom:6px;">Blue Water</h4>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">Clear, deep blue &mdash; the tuna&rsquo;s preferred environment. When you find blue water past 500m with bait and birds, you&rsquo;re in the right neighbourhood.</p>
        </div>
      </div>
      <div class="ocean-card">
        <div class="ocean-card-top" style="background:linear-gradient(135deg,rgba(5,150,105,.12),var(--card));">&#128994;</div>
        <div class="ocean-card-body">
          <h4 style="font-size:14px;font-weight:800;color:#f1f5f9;margin-bottom:6px;">Green Water Edge</h4>
          <p style="font-size:12px;color:#64748b;line-height:1.5;">The line where blue meets green is one of the most productive zones in the entire ocean. Nutrient-rich upwelled water against the clear EAC is a natural bait trap.</p>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- SECTION 8: BIRDS -->
<section id="birds" class="sec">
  <div class="wrap">
    <div class="sec-tag">Section 07</div>
    <h2 class="sec-h">Understanding Bird Behaviour</h2>
    <p class="sec-sub">Birds are your free sonar. Different species behave differently and understanding what each one tells you can save hours of searching.</p>

    <div class="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
      <div class="card card-hover">
        <div class="bird-icon-bg" style="background:linear-gradient(135deg,rgba(6,182,212,.1),transparent);margin:-24px -24px 16px;border-radius:16px 16px 0 0;">
          <span style="font-size:52px;">&#128031;</span>
        </div>
        <h3 style="font-size:15px;font-weight:800;color:#f1f5f9;margin-bottom:8px;">Mutton Birds</h3>
        <div style="display:inline-block;background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.25);color:#34d399;font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;margin-bottom:10px;">MOST RELIABLE</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Black birds that follow tuna schools and dive directly onto the bait being pushed up. When mutton birds are actively diving, there&rsquo;s almost certainly tuna below. The most trustworthy yellowfin indicator.</p>
      </div>

      <div class="card card-hover">
        <div class="bird-icon-bg" style="background:linear-gradient(135deg,rgba(245,158,11,.1),transparent);margin:-24px -24px 16px;border-radius:16px 16px 0 0;">
          <span style="font-size:52px;">&#128037;</span>
        </div>
        <h3 style="font-size:15px;font-weight:800;color:#f1f5f9;margin-bottom:8px;">Gannets</h3>
        <div style="display:inline-block;background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.25);color:var(--yellow);font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;margin-bottom:10px;">HIGH CONFIDENCE</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Gannets can physically see tuna from height and dive-bomb them at high speed. When gannets are diving, they have literally seen the fish. Very high-confidence indicator. Act fast.</p>
      </div>

      <div class="card card-hover">
        <div class="bird-icon-bg" style="background:linear-gradient(135deg,rgba(6,182,212,.08),transparent);margin:-24px -24px 16px;border-radius:16px 16px 0 0;">
          <span style="font-size:52px;">&#128037;</span>
        </div>
        <h3 style="font-size:15px;font-weight:800;color:#f1f5f9;margin-bottom:8px;">Terns</h3>
        <div style="display:inline-block;background:rgba(6,182,212,.12);border:1px solid rgba(6,182,212,.25);color:var(--cyan);font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;margin-bottom:10px;">BAIT INDICATOR</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Terns hover over surface bait. They indicate bait presence more than tuna directly, but where terns are working over bait there&rsquo;s a good chance yellowfin are underneath pushing it up.</p>
      </div>

      <div class="card card-hover">
        <div class="bird-icon-bg" style="background:linear-gradient(135deg,rgba(239,68,68,.08),transparent);margin:-24px -24px 16px;border-radius:16px 16px 0 0;">
          <span style="font-size:52px;">&#129345;</span>
        </div>
        <h3 style="font-size:15px;font-weight:800;color:#f1f5f9;margin-bottom:8px;">Bird Tracks</h3>
        <div style="display:inline-block;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.2);color:#fca5a5;font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;margin-bottom:10px;">DIRECTION GUIDE</div>
        <p style="font-size:13px;color:#94a3b8;line-height:1.5;">A stream of birds flying purposefully in one direction are following a moving school. Follow the tracks ahead of the birds to intercept the school before the bust-up. Don&rsquo;t chase from behind.</p>
      </div>
    </div>

    <div class="card" style="margin-top:20px;padding:20px 24px;border-color:rgba(245,158,11,.2);background:rgba(245,158,11,.04);">
      <p style="font-size:14px;color:#94a3b8;line-height:1.7;"><strong style="color:var(--yellow);">Key insight:</strong> Birds and tuna both <strong style="color:#e2e8f0">feed into the wind</strong>. On a northerly, birds will be flying south-to-north working into the wind. This means tuna are also travelling roughly north. Position yourself ahead of where the birds are coming from and let the fish run to you.</p>
    </div>
  </div>
</section>

<!-- SECTION 9: BOAT POSITIONING -->
<section id="positioning" class="sec sec-alt">
  <div class="wrap">
    <div class="sec-tag">Section 08</div>
    <h2 class="sec-h">Boat Positioning</h2>
    <p class="sec-sub">How you approach a bust-up is just as important as finding it. A bad approach kills a school. The right approach keeps the fish feeding and your lures in the zone.</p>

    <div class="grid md:grid-cols-2 gap-8 items-center">

      <!-- Animated positioning diagram -->
      <div class="pos-dia">
        <!-- Ocean background -->
        <div style="position:absolute;inset:0;background:radial-gradient(ellipse at center, rgba(6,182,212,.06) 0%, transparent 70%);"></div>
        <!-- Wind indicator -->
        <div class="wind-ind">&#8595; N WIND</div>
        <!-- Bust-up rings -->
        <div class="bust-ring r3"></div>
        <div class="bust-ring r2"></div>
        <div class="bust-ring r1">
          <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:800;color:rgba(239,68,68,.8);letter-spacing:.08em;text-transform:uppercase;">BUST UP</div>
        </div>
        <!-- Labels -->
        <div style="position:absolute;left:50%;transform:translateX(-50%);top:14%;font-size:9px;color:rgba(6,182,212,.7);font-weight:700;letter-spacing:.08em;text-transform:uppercase;">UPWIND / AHEAD</div>
        <!-- X marks (don't approach from here) -->
        <div style="position:absolute;bottom:18%;left:50%;transform:translateX(-50%);font-size:11px;color:rgba(239,68,68,.7);font-weight:800;">&#10007; BEHIND &mdash; DON&rsquo;T APPROACH</div>
        <!-- Approach arc (static visual) -->
        <svg style="position:absolute;inset:0;width:100%;height:100%;" viewBox="0 0 460 360" fill="none">
          <path d="M 340,290 Q 400,180 350,100 Q 300,40 230,70" stroke="rgba(245,158,11,0.5)" stroke-width="2" stroke-dasharray="6,4" fill="none"/>
          <text x="370" y="200" font-size="9" fill="rgba(245,158,11,0.6)" font-family="system-ui" font-weight="700" transform="rotate(50,370,200)">WIDE ARC</text>
        </svg>
        <!-- Animated boat -->
        <div class="boat-icon">&#9971;</div>
        <div class="pos-note">Approach wide &bull; Get upwind &bull; Cast down onto fish &bull; Let them come to you</div>
      </div>

      <!-- Steps -->
      <div class="space-y-4">
        <div class="card-sm" style="border-left:3px solid var(--yellow);">
          <div style="font-size:11px;font-weight:800;color:var(--yellow);letter-spacing:.08em;text-transform:uppercase;margin-bottom:5px;">Rule 1 &mdash; Never drive through it</div>
          <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Driving through a bust-up scatters the bait and sends tuna deep. The bust-up is gone in seconds and may not reform for hours. Approach from the side at minimum.</p>
        </div>
        <div class="card-sm" style="border-left:3px solid var(--cyan);">
          <div style="font-size:11px;font-weight:800;color:var(--cyan);letter-spacing:.08em;text-transform:uppercase;margin-bottom:5px;">Rule 2 &mdash; Go wide then upwind</div>
          <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Run a wide arc around the bust-up and position yourself upwind and ahead of the school&rsquo;s direction of travel. The fish are moving toward you, not away.</p>
        </div>
        <div class="card-sm" style="border-left:3px solid #34d399;">
          <div style="font-size:11px;font-weight:800;color:#34d399;letter-spacing:.08em;text-transform:uppercase;margin-bottom:5px;">Rule 3 &mdash; Cast down on them</div>
          <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Once in position, cast your lures or put your spread down ahead of and into the school. Let them swim to you. The fish are moving fast and will arrive shortly.</p>
        </div>
        <div class="card-sm" style="border-left:3px solid #818cf8;">
          <div style="font-size:11px;font-weight:800;color:#818cf8;letter-spacing:.08em;text-transform:uppercase;margin-bottom:5px;">Rule 4 &mdash; Stay patient</div>
          <p style="font-size:13px;color:#94a3b8;line-height:1.5;">Even when the bust-up goes down, stay in the area. The school will resurface. Keep lures in the water, watch the birds and be ready to move quickly when it comes up again.</p>
        </div>
      </div>

    </div>
  </div>
</section>

<!-- SECTION 10: CHECKLIST -->
<section id="checklist" class="sec">
  <div class="wrap" style="max-width:860px;">
    <div class="sec-tag">Section 09</div>
    <h2 class="sec-h">Quick Decision Checklist</h2>
    <p class="sec-sub">Answer these questions before you commit to a location. The more YES answers, the better your chances. Tick each one as you confirm it.</p>

    <!-- Score display -->
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:24px;padding:16px 20px;border-radius:14px;background:var(--card);border:1px solid var(--border);">
      <div>
        <div style="font-size:11px;color:#64748b;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px;">Fishing Score</div>
        <div><span id="score-num" style="font-size:36px;font-weight:900;color:#10b981;">0</span><span style="font-size:18px;color:#334155;font-weight:700;"> / 10</span></div>
      </div>
      <div style="flex:1;">
        <div style="height:8px;border-radius:999px;background:rgba(255,255,255,.06);overflow:hidden;">
          <div class="score-bar-fill" id="score-bar" style="width:0%;"></div>
        </div>
        <div id="score-label" style="font-size:12px;color:#475569;margin-top:6px;">Tick the conditions you&rsquo;ve confirmed</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px;" id="checklist-items">
      <div class="ci" onclick="toggleCheck(this)"><div class="cbox"><span class="check-tick">&#10003;</span></div><span style="font-size:13px;color:#94a3b8;">SST between 23&ndash;26&deg;C ?</span></div>
      <div class="ci" onclick="toggleCheck(this)"><div class="cbox"><span class="check-tick">&#10003;</span></div><span style="font-size:13px;color:#94a3b8;">Temperature break visible ?</span></div>
      <div class="ci" onclick="toggleCheck(this)"><div class="cbox"><span class="check-tick">&#10003;</span></div><span style="font-size:13px;color:#94a3b8;">Depth over 500m ?</span></div>
      <div class="ci" onclick="toggleCheck(this)"><div class="cbox"><span class="check-tick">&#10003;</span></div><span style="font-size:13px;color:#94a3b8;">Near EAC slack edge ?</span></div>
      <div class="ci" onclick="toggleCheck(this)"><div class="cbox"><span class="check-tick">&#10003;</span></div><span style="font-size:13px;color:#94a3b8;">East-to-west current hitting EAC ?</span></div>
      <div class="ci" onclick="toggleCheck(this)"><div class="cbox"><span class="check-tick">&#10003;</span></div><span style="font-size:13px;color:#94a3b8;">Blue or green water (not murky) ?</span></div>
      <div class="ci" onclick="toggleCheck(this)"><div class="cbox"><span class="check-tick">&#10003;</span></div><span style="font-size:13px;color:#94a3b8;">Bait present on sounder ?</span></div>
      <div class="ci" onclick="toggleCheck(this)"><div class="cbox"><span class="check-tick">&#10003;</span></div><span style="font-size:13px;color:#94a3b8;">Birds actively working ?</span></div>
      <div class="ci" onclick="toggleCheck(this)"><div class="cbox"><span class="check-tick">&#10003;</span></div><span style="font-size:13px;color:#94a3b8;">North or light wind ?</span></div>
      <div class="ci" onclick="toggleCheck(this)"><div class="cbox"><span class="check-tick">&#10003;</span></div><span style="font-size:13px;color:#94a3b8;">Moon in lead-up to full or just after ?</span></div>
    </div>

    <div style="margin-top:20px;padding:16px 20px;border-radius:12px;background:rgba(245,158,11,.06);border:1px solid rgba(245,158,11,.2);">
      <p style="font-size:13px;color:#94a3b8;line-height:1.6;"><strong style="color:var(--yellow);">7+ out of 10?</strong> Deploy your spread and commit to the location. <strong style="color:var(--yellow);">5&ndash;6?</strong> Fish it but keep searching. <strong style="color:var(--yellow);">Below 5?</strong> Keep moving and look for better water. Use the <a href="/" style="color:var(--cyan);text-decoration:none;font-weight:700;">Live Map</a> to overlay SST, chlorophyll and currents before you leave.</p>
    </div>
  </div>
</section>

<!-- SECTION 11: BRISBANE FISHING MAP -->
<section id="map-sec" class="sec sec-alt">
  <div class="wrap">
    <div class="sec-tag">Section 10</div>
    <h2 class="sec-h">Brisbane Offshore Fishing Map</h2>
    <p class="sec-sub">Key landmarks, depth contours and historical yellowfin zones off South-East Queensland. Depth contours are approximate and for reference only &mdash; not for navigation.</p>

    <!-- Layer toggle buttons -->
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;">
      <button class="map-btn on" id="mbtn-depths" onclick="toggleMapLayer('depths',this)">Depth Contours</button>
      <button class="map-btn on" id="mbtn-eac"    onclick="toggleMapLayer('eac',this)">EAC Flow</button>
      <button class="map-btn on" id="mbtn-zones"  onclick="toggleMapLayer('zones',this)">Hotspot Zones</button>
      <a href="/" style="margin-left:auto;display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:8px;background:rgba(6,182,212,.1);border:1px solid rgba(6,182,212,.3);color:var(--cyan);font-size:11px;font-weight:700;letter-spacing:.05em;text-decoration:none;">&#8599; Live Satellite Data</a>
    </div>

    <div id="fmap"></div>

    <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-4" style="margin-top:16px;">
      <div class="card-sm" style="border-left:3px solid rgba(255,255,255,.3);">
        <div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:#475569;text-transform:uppercase;margin-bottom:4px;">200m Contour</div>
        <p style="font-size:12px;color:#64748b;">Start of deep water. Minimum acceptable depth. Shelf break begins here.</p>
      </div>
      <div class="card-sm" style="border-left:3px solid rgba(6,182,212,.6);">
        <div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(6,182,212,.8);text-transform:uppercase;margin-bottom:4px;">500m Contour</div>
        <p style="font-size:12px;color:#64748b;">Target minimum. Where the current really starts to interact with bathymetry.</p>
      </div>
      <div class="card-sm" style="border-left:3px solid rgba(245,158,11,.7);">
        <div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:var(--yellow);text-transform:uppercase;margin-bottom:4px;">1000m Contour</div>
        <p style="font-size:12px;color:#64748b;">Ideal depth zone. Peak EAC influence. Best upwelling and collision zones.</p>
      </div>
      <div class="card-sm" style="border-left:3px solid rgba(139,92,246,.6);">
        <div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:#a78bfa;text-transform:uppercase;margin-bottom:4px;">2000m Contour</div>
        <p style="font-size:12px;color:#64748b;">Deep water. EAC core. Occasional fish here but usually too far from bottom structure.</p>
      </div>
    </div>
  </div>
</section>

<!-- FOOTER -->
<footer style="background:var(--navy);border-top:1px solid var(--border);padding:40px 24px;">
  <div style="max-width:1200px;margin:0 auto;display:flex;flex-wrap:wrap;gap:24px;align-items:center;justify-content:space-between;">
    <div>
      <div style="font-size:18px;font-weight:900;color:var(--yellow);margin-bottom:4px;">TunaTrack SEQ</div>
      <div style="font-size:12px;color:#334155;">SE Queensland &bull; Offshore Yellowfin Intelligence</div>
    </div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;">
      <a href="/"       style="color:#64748b;font-size:12px;font-weight:700;text-decoration:none;">Live Map</a>
      <a href="/tactics" style="color:#64748b;font-size:12px;font-weight:700;text-decoration:none;">Catching Tactics</a>
      <a href="/tips"   style="color:var(--yellow);font-size:12px;font-weight:700;text-decoration:none;">Yellowfin Tips</a>
      <a href="/conditions" style="color:#22d3ee;font-size:12px;font-weight:700;text-decoration:none;">Sea Conditions</a>
    </div>
    <div style="font-size:11px;color:#1e293b;max-width:380px;line-height:1.5;">Depth contours, hotspot zones and EAC indicators are indicative only and are not for navigation. Always use official hydrographic charts. Check local conditions and forecasts before heading offshore.</div>
  </div>
</footer>

<script>
// === SEASON TABS ===
function showSeason(id, btn) {
  document.querySelectorAll('.season-panel').forEach(function(el){ el.classList.remove('show'); });
  document.querySelectorAll('.stab').forEach(function(el){ el.classList.remove('active'); });
  var el = document.getElementById('sp-' + id);
  if (el) el.classList.add('show');
  btn.classList.add('active');
}

// === SST SLIDER ===
var sstData = {
  21: { color: '#1d4ed8', label: '21.0\u00b0C', desc: 'Too cool \u2014 tuna unlikely. Move further offshore to find warmer EAC water.' },
  21.5: { color: '#0369a1', label: '21.5\u00b0C', desc: 'Still cool. Marginal. Look for areas where temp is rising rather than stable.' },
  22: { color: '#0284c7', label: '22.0\u00b0C', desc: 'Borderline. Some fish possible if bait is present. Keep searching for warmer water.' },
  22.5: { color: '#0891b2', label: '22.5\u00b0C', desc: 'Getting there. If there\u2019s a break nearby with 24\u00b0+ on the other side, this is worth fishing.' },
  23: { color: '#0d9488', label: '23.0\u00b0C', desc: 'Lower end of the ideal range. Good if on the warmer side of a break. Fish possible.' },
  23.5: { color: '#059669', label: '23.5\u00b0C', desc: 'Good temperature. In the prime zone. Check for current breaks and bait.' },
  24: { color: '#10b981', label: '24.0\u00b0C', desc: 'Ideal temperature \u2014 prime yellowfin zone. Look for a break here. Fish are comfortable.' },
  24.5: { color: '#16a34a', label: '24.5\u00b0C', desc: 'Excellent. If there\u2019s a break to slightly cooler water nearby, that edge is where to fish.' },
  25: { color: '#15803d', label: '25.0\u00b0C', desc: 'Good. Upper mid-range. Still productive. Watch for the cooler-water edge being nearby.' },
  25.5: { color: '#ca8a04', label: '25.5\u00b0C', desc: 'Warm. Not a problem alone but find the break to slightly cooler water and fish that edge.' },
  26: { color: '#d97706', label: '26.0\u00b0C', desc: 'Upper limit. Fish can be here but look hard for a nearby temperature break to fish.' },
  26.5: { color: '#dc2626', label: '26.5\u00b0C', desc: 'Too warm to be ideal. Focus on finding where this water meets cooler water \u2014 that edge is the target.' },
  27: { color: '#b91c1c', label: '27.0\u00b0C', desc: 'Very warm. Likely inside the EAC core. Look for the eastern edge where temp drops to 24\u00b025\u00b0C.' },
  27.5: { color: '#991b1b', label: '27.5\u00b0C', desc: 'Hot water. Poor fishing usually. Move east until you find the temperature break.' },
  28: { color: '#7f1d1d', label: '28.0\u00b0C', desc: 'Too warm. Well inside the EAC core. Keep travelling east to find the cooler productive edge.' }
};
function updateSST(val) {
  var v = parseFloat(val);
  var key = Math.round(v * 2) / 2;
  var d = sstData[key] || sstData[24];
  document.getElementById('sst-temp-val').textContent = d.label;
  document.getElementById('sst-temp-val').style.color = d.color;
  document.getElementById('sst-desc').textContent = d.desc;
}

// === MOON CALENDAR ===
(function() {
  var phases = [
    {n:'1',e:'\u25cf',cls:'neutral'},{n:'2',e:'\u25d1',cls:'neutral'},{n:'3',e:'\u25d1',cls:'neutral'},
    {n:'4',e:'\u25d0',cls:'ok'},{n:'5',e:'\u25d0',cls:'ok'},
    {n:'6',e:'\u25d0',cls:'good'},{n:'7',e:'\u25d0',cls:'good'},{n:'8',e:'\u25d0',cls:'good'},
    {n:'9',e:'\u25d0',cls:'good'},{n:'10',e:'\u25d0',cls:'good'},
    {n:'11',e:'\u25d0',cls:'best'},{n:'12',e:'\u25d0',cls:'best'},{n:'13',e:'\u25d0',cls:'best'},
    {n:'14',e:'\u26aa',cls:'bad',t:'FULL'},
    {n:'15',e:'\u25d1',cls:'ok'},{n:'16',e:'\u25d1',cls:'ok'},
    {n:'17',e:'\u25d1',cls:'neutral'},{n:'18',e:'\u25d1',cls:'neutral'},{n:'19',e:'\u25d1',cls:'neutral'},
    {n:'20',e:'\u25d1',cls:'ok'},{n:'21',e:'\u25d1',cls:'ok'},
    {n:'22',e:'\u25d1',cls:'neutral'},
    {n:'23',e:'\u25d2',cls:'neutral'},{n:'24',e:'\u25d2',cls:'neutral'},
    {n:'25',e:'\u25d2',cls:'ok'},{n:'26',e:'\u25d2',cls:'ok'},
    {n:'27',e:'\u25d2',cls:'good'},{n:'28',e:'\u25d2',cls:'good'},
    {n:'29',e:'\u25d2',cls:'best'},
    {n:'30',e:'\u25cf',cls:'bad',t:'NEW'}
  ];
  var cal = document.getElementById('moon-cal');
  var days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  days.forEach(function(d){
    var el = document.createElement('div');
    el.style.cssText = 'text-align:center;font-size:9px;font-weight:700;color:#1e3448;letter-spacing:.06em;text-transform:uppercase;padding:4px 0;';
    el.textContent = d;
    cal.appendChild(el);
  });
  phases.forEach(function(p) {
    var el = document.createElement('div');
    el.className = 'md ' + p.cls;
    el.innerHTML = '<div class="mn">' + p.e + '</div><div style="font-size:9px;">' + p.n + (p.t ? '<br/><span style="font-size:8px;font-weight:700;">' + p.t + '</span>' : '') + '</div>';
    el.title = 'Day ' + p.n + (p.t ? ' \u2014 ' + p.t + ' MOON' : '');
    cal.appendChild(el);
  });
})();

// === CHECKLIST ===
function toggleCheck(el) {
  el.classList.toggle('on');
  updateScore();
}
function updateScore() {
  var items = document.querySelectorAll('#checklist-items .ci');
  var on = document.querySelectorAll('#checklist-items .ci.on').length;
  var total = items.length;
  document.getElementById('score-num').textContent = on;
  document.getElementById('score-bar').style.width = (on / total * 100) + '%';
  var labels = ['Keep searching \u2014 conditions are poor','Marginal \u2014 keep looking for better water','Mixed \u2014 worth a try but don\u2019t commit','Getting better \u2014 fish it but keep searching','Good conditions \u2014 fish it hard','Excellent \u2014 deploy spread and commit!'];
  document.getElementById('score-label').textContent = labels[Math.min(Math.floor(on / total * 5), 5)];
  var numEl = document.getElementById('score-num');
  numEl.style.color = on >= 7 ? '#10b981' : on >= 5 ? '#f59e0b' : '#ef4444';
}

// === LEAFLET MAP ===
document.addEventListener('DOMContentLoaded', function() {
  var map = L.map('fmap', {
    center: [-27.5, 154.15],
    zoom: 8,
    zoomControl: true,
    scrollWheelZoom: false
  });

  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 16
  }).addTo(map);

  // Enable scroll zoom on click
  map.on('click', function(){ map.scrollWheelZoom.enable(); });

  // Approximate depth contours (indicative, not for navigation)
  var c200 = L.polyline([[-26.5,153.65],[-26.8,153.72],[-27.0,153.76],[-27.25,153.82],[-27.5,153.88],[-27.75,153.9],[-28.0,153.87],[-28.3,153.8],[-28.5,153.72]], {color:'rgba(200,200,200,0.5)',weight:1.5,dashArray:'4,3'}).bindTooltip('~200m contour (indicative)',{sticky:true});
  var c500 = L.polyline([[-26.5,153.9],[-26.8,153.98],[-27.0,154.05],[-27.25,154.12],[-27.5,154.2],[-27.75,154.22],[-28.0,154.18],[-28.3,154.1],[-28.5,154.0]], {color:'rgba(6,182,212,0.7)',weight:2,dashArray:'5,3'}).bindTooltip('~500m contour (indicative)',{sticky:true});
  var c1000 = L.polyline([[-26.5,154.2],[-26.8,154.3],[-27.0,154.38],[-27.25,154.46],[-27.5,154.52],[-27.75,154.52],[-28.0,154.46],[-28.3,154.35],[-28.5,154.22]], {color:'rgba(245,158,11,0.8)',weight:2.5}).bindTooltip('~1000m contour (indicative)',{sticky:true});
  var c2000 = L.polyline([[-26.5,154.55],[-26.8,154.65],[-27.0,154.72],[-27.25,154.78],[-27.5,154.82],[-27.75,154.8],[-28.0,154.72],[-28.3,154.6],[-28.5,154.45]], {color:'rgba(139,92,246,0.6)',weight:1.5,dashArray:'6,4'}).bindTooltip('~2000m contour (indicative)',{sticky:true});

  var depthGroup = L.layerGroup([c200, c500, c1000, c2000]).addTo(map);

  // Contour labels
  L.marker([-28.4, 153.72], {icon: L.divIcon({className:'', html:'<div style="color:rgba(200,200,200,0.6);font-size:9px;font-weight:700;background:rgba(0,0,0,0.5);padding:1px 4px;border-radius:3px;white-space:nowrap;">200m</div>', iconAnchor:[15,8]})}).addTo(depthGroup);
  L.marker([-28.4, 154.0], {icon: L.divIcon({className:'', html:'<div style="color:rgba(6,182,212,0.8);font-size:9px;font-weight:700;background:rgba(0,0,0,0.5);padding:1px 4px;border-radius:3px;white-space:nowrap;">500m</div>', iconAnchor:[15,8]})}).addTo(depthGroup);
  L.marker([-28.4, 154.3], {icon: L.divIcon({className:'', html:'<div style="color:rgba(245,158,11,0.9);font-size:9px;font-weight:700;background:rgba(0,0,0,0.5);padding:1px 4px;border-radius:3px;white-space:nowrap;">1000m</div>', iconAnchor:[20,8]})}).addTo(depthGroup);
  L.marker([-28.4, 154.6], {icon: L.divIcon({className:'', html:'<div style="color:rgba(139,92,246,0.7);font-size:9px;font-weight:700;background:rgba(0,0,0,0.5);padding:1px 4px;border-radius:3px;white-space:nowrap;">2000m</div>', iconAnchor:[20,8]})}).addTo(depthGroup);

  // EAC flow arrows
  var eacArrowIcon = function(label) { return L.divIcon({className:'', html:'<div style="color:rgba(6,182,212,0.7);font-size:11px;font-weight:700;background:rgba(6,18,32,0.7);padding:2px 6px;border-radius:4px;border:1px solid rgba(6,182,212,0.3);white-space:nowrap;">\u2193 ' + label + '</div>', iconAnchor:[40,12]}); };
  var eacGroup = L.layerGroup([
    L.polyline([[-26.0,154.4],[-26.5,154.42],[-27.0,154.45],[-27.5,154.5],[-28.0,154.45],[-28.5,154.3]], {color:'rgba(6,182,212,0.5)',weight:3,dashArray:'8,4'}).bindTooltip('East Australian Current (indicative)',{sticky:true}),
    L.marker([-26.8,154.44], {icon: eacArrowIcon('EAC')}),
    L.marker([-27.4,154.48], {icon: eacArrowIcon('EAC')}),
    L.marker([-28.1,154.4],  {icon: eacArrowIcon('EAC')})
  ]).addTo(map);

  // Hotspot zones
  var hsIcon = function(label, color) { return L.divIcon({className:'', html:'<div style="color:' + color + ';font-size:10px;font-weight:800;background:rgba(6,18,32,0.85);padding:3px 8px;border-radius:6px;border:1px solid ' + color + ';white-space:nowrap;">\u2605 ' + label + '</div>', iconAnchor:[50,12]}); };
  var zonesGroup = L.layerGroup([
    L.circle([-27.0, 154.1], {radius: 18000, color:'rgba(245,158,11,0.4)', fillColor:'rgba(245,158,11,0.06)', fillOpacity:1, weight:1.5, dashArray:'4,3'}).bindTooltip('Yellowfin Hotspot Zone (indicative)',{sticky:true}),
    L.circle([-27.5, 154.35], {radius: 22000, color:'rgba(245,158,11,0.4)', fillColor:'rgba(245,158,11,0.06)', fillOpacity:1, weight:1.5, dashArray:'4,3'}).bindTooltip('Yellowfin Hotspot Zone (indicative)',{sticky:true}),
    L.circle([-27.85,154.0],  {radius: 15000, color:'rgba(245,158,11,0.35)', fillColor:'rgba(245,158,11,0.05)', fillOpacity:1, weight:1.5, dashArray:'4,3'}).bindTooltip('Barwon Banks area (indicative)',{sticky:true}),
    L.marker([-27.0,  154.08], {icon: hsIcon('Hutchinson Shoal area', 'rgba(245,158,11,0.8)')}),
    L.marker([-27.5,  154.33], {icon: hsIcon('The Trench zone', 'rgba(245,158,11,0.8)')}),
    L.marker([-27.85, 153.98], {icon: hsIcon('Barwon Banks', 'rgba(245,158,11,0.7)')})
  ]).addTo(map);

  // Place markers
  var placeIcon = function(label, color) { return L.divIcon({className:'', html:'<div style="color:' + color + ';font-size:10px;font-weight:700;background:rgba(0,0,0,0.7);padding:2px 6px;border-radius:4px;white-space:nowrap;">' + label + '</div>', iconAnchor:[0,8]}); };
  L.marker([-27.47, 153.02], {icon: placeIcon('Brisbane', '#94a3b8')}).addTo(map);
  L.marker([-27.03, 153.47], {icon: placeIcon('Cape Moreton', '#94a3b8')}).addTo(map);
  L.marker([-27.15, 153.38], {icon: placeIcon('Moreton Island', '#64748b')}).addTo(map);
  L.marker([-27.47, 153.53], {icon: placeIcon('N. Stradbroke', '#64748b')}).addTo(map);
  L.marker([-27.87, 153.47], {icon: placeIcon('S. Stradbroke', '#475569')}).addTo(map);

  // Layer toggle state
  window._mapLayers = { depths: depthGroup, eac: eacGroup, zones: zonesGroup };
});

window.toggleMapLayer = function(key, btn) {
  if (!window._mapLayers) return;
  var layer = window._mapLayers[key];
  if (!layer) return;
  var mapEl = document.getElementById('fmap');
  if (!mapEl || !mapEl._leaflet_id) return;
  var lmap = null;
  for (var id in L.Map._instances || {}) { lmap = L.Map._instances[id]; break; }
  // Simpler: toggle via btn state
  btn.classList.toggle('on');
  if (btn.classList.contains('on')) { layer.addTo(window._leafletMap || window._mapLayers._map); }
};

// Store map ref
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(function() {
    document.querySelectorAll('.leaflet-container').forEach(function(el) {
      if (el._leaflet_id && window.L) {
        window._leafletMap = L.Map._instance;
      }
    });
  }, 500);
});

// Simpler toggle approach: re-init layer toggles after map is ready
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(function() {
    window.toggleMapLayer = function(key, btn) {
      if (!window._mapLayers) return;
      var layer = window._mapLayers[key];
      if (!layer) return;
      btn.classList.toggle('on');
      var fmap = document.getElementById('fmap');
      if (!fmap) return;
      // Find Leaflet map instance from the container
      var mapObj = null;
      if (window._theMap) mapObj = window._theMap;
      if (!mapObj) return;
      if (btn.classList.contains('on')) {
        mapObj.addLayer(layer);
      } else {
        mapObj.removeLayer(layer);
      }
    };
  }, 200);
});

// Override DOMContentLoaded map init to expose map instance
var _origInit = null;
(function() {
  var oldFn = document.addEventListener.bind(document);
  document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function(){
      var containers = document.querySelectorAll('.leaflet-container');
      containers.forEach(function(c) {
        if (c._leaflet_map) window._theMap = c._leaflet_map;
      });
    }, 600);
  });
})();

// === NAV ACTIVE STATE ===
(function() {
  var sections = document.querySelectorAll('section[id]');
  var navLinks = document.querySelectorAll('.nlink[href^="#"]');
  var observer = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting) {
        navLinks.forEach(function(link) {
          link.classList.toggle('active', link.getAttribute('href') === '#' + entry.target.id);
        });
      }
    });
  }, { threshold: 0.3 });
  sections.forEach(function(s) { observer.observe(s); });
})();
</script>

</main>
</body>
</html>
"""


def build_yellowfin_tips_html() -> str:
    """Return the complete HTML for the Yellowfin Tips guide page."""
    return _HTML
