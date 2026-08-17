"""
Standalone "Catching Tactics" guide page for yellowfin tuna off Brisbane.

Static HTML page served at GET /tactics.  No dynamic data is fetched -- all
content is hard-coded expert guidance covering time of year, finding best
water (EAC / upwelling / SST), moon & wind, on-water signs, bird
identification, and approach strategy.

FindTunaGraphic.png is served from /static/FindTunaGraphic.png
(place the file in the repo-root static/ folder).
"""

_HTML = """\
<!DOCTYPE html>
<html class="h-full" lang="en">
<head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>TunaTrack SEQ | Catching Tactics</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<style>
  :root { --accent: #00f2ff; --gold: #fbbf24; }
  body { background-color: #0a1118; color: #e2e8f0; font-family: 'Inter', sans-serif; }
  .card { background: linear-gradient(145deg, #162638, #121e2b); border: 1px solid #2d3e50; }
  .text-accent { color: var(--accent); }
  .text-gold  { color: var(--gold); }
  .accent-glow { text-shadow: 0 0 12px rgba(0,242,255,0.5); }
  .sh { border-left: 4px solid var(--accent); padding-left: 12px; }
</style>
</head>
<body class="h-full flex overflow-hidden">

<!-- SIDEBAR -->
<aside class="w-52 shrink-0 bg-slate-900 border-r border-slate-700 flex flex-col">
  <div class="p-5">
    <a href="/" style="text-decoration:none">
      <h1 class="text-xl font-black tracking-tighter flex items-center gap-2 text-accent">
        <svg class="w-7 h-7 shrink-0" fill="currentColor" viewBox="0 0 24 24">
          <path d="M21,12C21,12 18,16 12,16C6,16 3,12 3,12C3,12 6,8 12,8C18,8 21,12 21,12M12,10A2,2 0 0,0 10,12A2,2 0 0,0 12,14A2,2 0 0,0 14,12A2,2 0 0,0 12,10Z"/>
        </svg>
        TunaTrack<span class="text-white">SEQ</span>
      </h1>
    </a>
  </div>
  <nav class="flex-1 px-3 py-2 space-y-1">
    <a href="/" style="text-decoration:none" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-800 transition-colors text-sm text-slate-300">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path d="M9 20l-5.447-2.724A2 2 0 013 15.488V5.111a2 2 0 011.168-1.815l6-2.667a2 2 0 011.664 0l6 2.667A2 2 0 0119 5.111v10.377a2 2 0 01-1.168 1.815L12 20m-3 0l3 1.5m0-1.5v-6" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
      </svg>
      Live Map
    </a>
    <a href="/tactics" style="text-decoration:none" class="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-cyan-900/30 border-r-4 border-cyan-500 text-sm font-semibold text-accent">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
      </svg>
      Catching Tactics
    </a>
    <a href="/tips" style="text-decoration:none" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-800 transition-colors text-sm text-slate-300">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
      </svg>
      Yellowfin Tips
    </a>
    <a href="/conditions" style="text-decoration:none" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-800 transition-colors text-sm text-slate-300">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
      </svg>
      Sea Conditions
    </a>
  </nav>
  <div class="p-4 border-t border-slate-700 text-xs text-slate-500">
    SE Queensland<br/>Noosa &rarr; Gold Coast
  </div>
</aside>

<!-- MAIN -->
<main class="flex-1 overflow-y-auto bg-slate-950">

  <!-- HERO -->
  <section class="relative h-48 overflow-hidden border-b border-cyan-900/40" style="background:linear-gradient(135deg,#0d1f2d 0%,#0a2a3a 50%,#0a1118 100%)">
    <div class="absolute inset-0" style="background:radial-gradient(ellipse at 30% 50%, rgba(0,180,200,0.08) 0%, transparent 70%)"></div>
    <div class="relative z-10 p-8 flex flex-col justify-end h-full">
      <div class="flex items-center gap-3 mb-2">
        <span class="text-accent text-xs font-bold tracking-widest uppercase px-3 py-1 rounded-full" style="background:rgba(0,242,255,0.1);border:1px solid rgba(0,242,255,0.2)">Expert Guide</span>
        <span class="text-slate-400 text-xs tracking-widest">SEP &bull; OCT &bull; NOV &mdash; MAIN SEASON</span>
      </div>
      <h2 class="text-4xl font-black italic tracking-tighter text-white uppercase accent-glow leading-tight">
        Catching Yellowfin Tuna <span class="text-gold">Off Brisbane</span>
      </h2>
      <p class="mt-1 text-slate-400 text-sm">Offshore SEQ &mdash; 60&ndash;80 km out &mdash; 500m to 1000m+ depth</p>
    </div>
  </section>

  <div class="p-6 space-y-6 max-w-6xl mx-auto">

    <!-- ROW 1: TIME OF YEAR + FIND TUNA GRAPHIC -->
    <div class="grid grid-cols-1 lg:grid-cols-5 gap-5">

      <!-- Season card -->
      <div class="card p-5 rounded-xl lg:col-span-2 space-y-3">
        <h3 class="sh text-lg font-bold">Time of Year</h3>
        <div class="space-y-2.5 text-sm">
          <div class="p-3 rounded-lg bg-slate-800/60 border border-slate-700">
            <p class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-1">JUN &bull; JUL &bull; AUG</p>
            <p class="text-slate-300">Off Fraser Island &mdash; tuna further north</p>
          </div>
          <div class="p-3 rounded-lg border" style="background:rgba(0,200,220,0.06);border-color:rgba(0,200,220,0.25)">
            <p class="text-xs font-bold text-accent uppercase tracking-widest mb-1">SEP &bull; OCT &bull; NOV &mdash; Main Season</p>
            <p class="text-slate-300">Tuna move south down the coast to <strong class="text-white">spawn</strong></p>
            <p class="text-slate-400 text-xs mt-1.5">Usually <strong class="text-white">60&ndash;80 km offshore</strong></p>
          </div>
          <ul class="space-y-1.5 text-xs text-slate-400 pt-1">
            <li class="flex gap-2"><span class="text-cyan-500 mt-0.5">&#8226;</span><span>Start of the EAC brings warmer water inshore</span></li>
            <li class="flex gap-2"><span class="text-cyan-500 mt-0.5">&#8226;</span><span>Tuna swim <em>with</em> the current, feed heading north into the wind, move slowly in one direction</span></li>
          </ul>
        </div>
      </div>

      <!-- FindTunaGraphic -->
      <div class="card rounded-xl lg:col-span-3 overflow-hidden flex flex-col min-h-56">
        <div class="px-5 pt-4 pb-2 shrink-0">
          <h3 class="sh text-lg font-bold">Where to Find Them</h3>
        </div>
        <div class="flex-1 bg-slate-900 relative">
          <img src="/static/FindTunaGraphic.png"
               alt="Find Tuna Graphic showing EAC structure, upwelling zones and depth contours"
               class="w-full h-full object-contain"
               onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"/>
          <div style="display:none" class="absolute inset-0 items-center justify-center text-center p-6">
            <p class="text-slate-600 text-xs">Place <strong class="text-slate-400">FindTunaGraphic.png</strong> in the <code class="text-cyan-700">static/</code> folder at the repo root to show the graphic here.</p>
          </div>
        </div>
      </div>

    </div>

    <!-- ROW 2: FINDING THE BEST WATER -->
    <div class="card p-5 rounded-xl space-y-4">
      <h3 class="sh text-lg font-bold">Finding the Best Water</h3>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-5">

        <!-- Upwelling / Downwelling -->
        <div class="space-y-3">
          <p class="text-xs font-bold text-slate-400 uppercase tracking-widest">EAC Currents</p>
          <div class="p-3 rounded-lg" style="background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2)">
            <p class="text-emerald-400 font-bold text-xs uppercase tracking-wider mb-2">&#8593; Upwelling &mdash; Good</p>
            <ul class="text-xs space-y-1 text-slate-300">
              <li>&bull; &minus;10 to Line of Zero is the sweet spot</li>
              <li>&bull; <strong class="text-white">Clockwise</strong> currents</li>
              <li>&bull; Food congregates near the surface</li>
            </ul>
          </div>
          <div class="p-3 rounded-lg" style="background:rgba(249,115,22,0.08);border:1px solid rgba(249,115,22,0.2)">
            <p class="text-orange-400 font-bold text-xs uppercase tracking-wider mb-2">&#8595; Downwelling &mdash; OK short term</p>
            <ul class="text-xs space-y-1 text-slate-300">
              <li>&bull; Good for 2&ndash;4 [readings] before it dies</li>
              <li>&bull; <strong class="text-white">Anti-clockwise</strong> currents</li>
            </ul>
          </div>
        </div>

        <!-- SST Temperature -->
        <div class="space-y-3">
          <p class="text-xs font-bold text-slate-400 uppercase tracking-widest">Sea Surface Temp Breaks</p>
          <div class="h-7 w-full rounded flex items-center justify-between px-2.5 text-[10px] font-bold text-white"
               style="background:linear-gradient(to right,#dc2626,#16a34a,#1d4ed8)">
            <span>HOT &gt;26&deg;C</span>
            <span style="text-shadow:0 1px 2px #000">IDEAL BREAK</span>
            <span>COOL &lt;23&deg;C</span>
          </div>
          <ul class="text-xs space-y-1.5 text-slate-300 pt-1">
            <li>&bull; Best temp: <strong class="text-white">26&ndash;23&deg;C</strong></li>
            <li>&bull; Look for the break on the <strong class="text-white">eastern side of the EAC</strong></li>
            <li>&bull; Target <strong class="text-white">blue &amp; green</strong> water &mdash; avoid brown/murky</li>
            <li>&bull; In warmer months, find the slightly <strong class="text-white">cooler edge</strong></li>
          </ul>
          <div class="p-2.5 rounded-lg bg-slate-800/50 border border-slate-700 text-[11px] text-slate-400 italic mt-1">
            &ldquo;Watch the temp rise then drop off on the sounder. Once off the other side, come back in and find the fish.&rdquo;
          </div>
        </div>

        <!-- EAC Structure + Depth -->
        <div class="space-y-3">
          <p class="text-xs font-bold text-slate-400 uppercase tracking-widest">EAC Structure &amp; Depth</p>
          <ul class="text-xs space-y-2 text-slate-300">
            <li class="flex gap-2"><span class="text-gold shrink-0">&#9733;</span><span>Generally on the <strong class="text-white">eastern (slack) side</strong> of the EAC where it gets slack outside</span></li>
            <li class="flex gap-2"><span class="text-gold shrink-0">&#9733;</span><span>Where current goes <strong class="text-white">east&rarr;west</strong> and hits the EAC &mdash; prime focal point</span></li>
            <li class="flex gap-2"><span class="text-gold shrink-0">&#9733;</span><span>Find the <strong class="text-white">bait feeding lines</strong> &mdash; tuna will be there</span></li>
          </ul>
          <div class="p-3 rounded-lg border border-slate-700 bg-slate-900/60 text-center mt-1">
            <p class="text-[10px] text-gold font-bold uppercase tracking-widest mb-1">Target Depth Zone</p>
            <p class="text-2xl font-black text-white">500m &ndash; 1000m+</p>
            <p class="text-[10px] text-slate-500 mt-0.5">Past 500m; 1000m+ generally ideal</p>
          </div>
        </div>

      </div>
    </div>

    <!-- ROW 3: MOON + WIND -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-5">

      <!-- Moon -->
      <div class="card p-5 rounded-xl space-y-3">
        <h3 class="sh text-lg font-bold">Moon Phase</h3>
        <div class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <div class="flex items-start gap-2 col-span-2 pb-1 border-b border-slate-700">
            <span class="text-red-400 shrink-0 mt-0.5">&#10006;</span>
            <span><strong class="text-white">Full moon day</strong> &mdash; BAD. Avoid.</span>
          </div>
          <div class="flex items-start gap-2">
            <span class="text-emerald-400 shrink-0 mt-0.5">&#10004;</span>
            <span><strong class="text-white">Lead-up</strong> to full moon &mdash; BEST</span>
          </div>
          <div class="flex items-start gap-2">
            <span class="text-emerald-400 shrink-0 mt-0.5">&#10004;</span>
            <span>A couple of days <em>after</em> &mdash; OK</span>
          </div>
          <div class="flex items-start gap-2">
            <span class="text-slate-500 shrink-0 mt-0.5">&#9644;</span>
            <span>Half moon &mdash; slower</span>
          </div>
          <div class="flex items-start gap-2">
            <span class="text-emerald-400 shrink-0 mt-0.5">&#10004;</span>
            <span>Major / minor moon windows &mdash; good</span>
          </div>
        </div>
        <p class="text-[11px] text-slate-500 italic pt-1 border-t border-slate-700/60">Use the Moon &amp; Tides page on the Live Map for solunar peaks and phase for any date.</p>
      </div>

      <!-- Wind -->
      <div class="card p-5 rounded-xl space-y-3">
        <h3 class="sh text-lg font-bold">Wind Direction</h3>
        <div class="space-y-2.5 text-sm">
          <div class="flex items-start gap-2 p-2.5 rounded-lg" style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2)">
            <span class="text-red-400 shrink-0 mt-0.5">&#10006;</span>
            <span><strong class="text-white">Southerly wind</strong> &mdash; BAD. Tuna and birds scatter.</span>
          </div>
          <div class="flex items-start gap-2 p-2.5 rounded-lg" style="background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2)">
            <span class="text-emerald-400 shrink-0 mt-0.5">&#10004;</span>
            <span><strong class="text-white">Northerly wind</strong> &mdash; BEST, especially in spring</span>
          </div>
        </div>
        <div class="p-3 rounded-lg bg-slate-800/50 border border-slate-700 text-xs text-slate-400">
          Both tuna <em>and</em> birds head <strong class="text-white">into the wind</strong>. A northerly pushes bait and fish together making them easier to find and stay on.
        </div>
      </div>

    </div>

    <!-- ROW 4: ON THE WATER SIGNS -->
    <div class="card p-5 rounded-xl space-y-4">
      <h3 class="sh text-lg font-bold">Signs on the Water</h3>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">

        <div class="space-y-2">
          <p class="text-xs font-bold text-accent uppercase tracking-wider pb-1 border-b border-slate-700/60">Visual Signs</p>
          <ul class="text-xs space-y-1.5 text-slate-300">
            <li class="flex gap-2"><span class="text-gold shrink-0">&#9733;</span><span>Birds diving on bait</span></li>
            <li class="flex gap-2"><span class="text-gold shrink-0">&#9733;</span><span>Baitfish schooling on the surface</span></li>
            <li class="flex gap-2"><span class="text-gold shrink-0">&#9733;</span><span>Tuna crashing/breaking the surface</span></li>
            <li class="flex gap-2"><span class="text-gold shrink-0">&#9733;</span><span>Blue &amp; green water &mdash; not brown/murky</span></li>
          </ul>
        </div>

        <div class="space-y-2">
          <p class="text-xs font-bold text-accent uppercase tracking-wider pb-1 border-b border-slate-700/60">Wildlife Signs</p>
          <ul class="text-xs space-y-1.5 text-slate-300">
            <li class="flex gap-2"><span class="text-gold shrink-0">&#9733;</span><span><strong class="text-white">Pilot whales</strong> &mdash; strong tuna indicator</span></li>
            <li class="flex gap-2"><span class="text-gold shrink-0">&#9733;</span><span><strong class="text-white">False killer whales</strong> &mdash; they eat tuna, tuna is close by</span></li>
          </ul>
        </div>

        <div class="space-y-2">
          <p class="text-xs font-bold text-accent uppercase tracking-wider pb-1 border-b border-slate-700/60">Bird Identification</p>
          <ul class="text-xs space-y-2 text-slate-300">
            <li class="flex gap-2"><span class="text-sky-400 shrink-0">&#8226;</span><span><strong class="text-white">Mutton birds</strong> (black) &mdash; follow &amp; dive on the feed. Most reliable indicator.</span></li>
            <li class="flex gap-2"><span class="text-sky-400 shrink-0">&#8226;</span><span><strong class="text-white">Gannets &amp; Terns</strong> &mdash; look down and physically spot the tuna. Fast hunters.</span></li>
            <li class="flex gap-2"><span class="text-sky-400 shrink-0">&#8226;</span><span>Bird <strong class="text-white">tracks</strong> show the direction the school is moving</span></li>
          </ul>
        </div>

        <div class="space-y-2">
          <p class="text-xs font-bold text-accent uppercase tracking-wider pb-1 border-b border-slate-700/60">Tuna Behaviour</p>
          <ul class="text-xs space-y-1.5 text-slate-300">
            <li class="flex gap-2"><span class="text-sky-400 shrink-0">&#8226;</span><span>Swim with the current</span></li>
            <li class="flex gap-2"><span class="text-sky-400 shrink-0">&#8226;</span><span>Feed heading <strong class="text-white">north into the wind</strong> / current</span></li>
            <li class="flex gap-2"><span class="text-sky-400 shrink-0">&#8226;</span><span>Move slowly in <strong class="text-white">one direction</strong> &mdash; track the school</span></li>
          </ul>
        </div>

      </div>
    </div>

    <!-- ROW 5: APPROACH & POSITION -->
    <div class="card p-5 rounded-xl space-y-4">
      <h3 class="sh text-lg font-bold">Approach &amp; Position</h3>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-5">

        <div class="p-4 rounded-xl space-y-2" style="background:rgba(0,200,220,0.06);border:1px solid rgba(0,200,220,0.2)">
          <p class="text-xs font-bold text-accent uppercase tracking-wider">The Wide Approach</p>
          <ul class="text-sm space-y-1.5 text-slate-300">
            <li>&bull; Run <strong class="text-white">wide around</strong> the bust-up</li>
            <li>&bull; <strong class="text-white">Never</strong> come up from behind</li>
            <li>&bull; Get <strong class="text-white">upwind</strong> of and ahead of their feeding direction</li>
            <li>&bull; <strong class="text-white">Cast down</strong> on them as they come through</li>
          </ul>
        </div>

        <div class="p-4 rounded-xl space-y-2 bg-slate-800/40 border border-slate-700">
          <p class="text-xs font-bold text-slate-300 uppercase tracking-wider">Stay Patient</p>
          <ul class="text-sm space-y-1.5 text-slate-400">
            <li>&bull; Let the fish come <strong class="text-slate-300">to you</strong></li>
            <li>&bull; Keep lures in the zone &mdash; don&rsquo;t chase</li>
            <li>&bull; Stay in the area &mdash; the school will come back around</li>
          </ul>
        </div>

        <!-- Schematic -->
        <div class="rounded-xl border border-slate-700 bg-slate-900/60 flex flex-col items-center justify-center p-4 min-h-28">
          <div class="border-2 border-dashed border-cyan-800/40 rounded-full w-28 h-28 relative flex items-center justify-center">
            <div class="text-[9px] uppercase text-cyan-700 absolute top-1.5 tracking-widest">UPWIND</div>
            <div class="text-center">
              <div class="w-3 h-3 bg-cyan-400/30 rounded-full mx-auto animate-ping"></div>
              <p class="text-[9px] font-bold text-slate-300 mt-1">BUST UP</p>
            </div>
            <div class="text-[8px] text-slate-600 absolute bottom-1.5">wide arc</div>
          </div>
          <p class="text-[10px] text-slate-500 mt-2 text-center">Approach wide &amp; from upwind.<br/>Cast down onto feeding fish.</p>
        </div>

      </div>
    </div>

    <!-- KEY TAKEAWAYS -->
    <footer class="rounded-2xl p-6" style="background:rgba(0,200,220,0.06);border:2px solid rgba(0,242,255,0.2)">
      <div class="flex flex-col md:flex-row items-start md:items-center gap-6">
        <div class="shrink-0">
          <h4 class="text-gold font-black italic text-xl uppercase tracking-tighter">Key Takeaways</h4>
          <p class="text-accent font-bold mt-0.5">Let the bite come to you!</p>
        </div>
        <div class="flex-1 grid grid-cols-2 lg:grid-cols-4 gap-4 md:border-l md:border-cyan-800/50 md:pl-6">
          <div>
            <p class="text-xs font-bold text-white uppercase mb-1">Best Water</p>
            <p class="text-[11px] text-slate-400">26&ndash;23&deg;C, temp break on the eastern EAC edge. Blue/green, clear.</p>
          </div>
          <div>
            <p class="text-xs font-bold text-white uppercase mb-1">Depth &amp; Structure</p>
            <p class="text-[11px] text-slate-400">500m+, ideally 1000m+. Where east-to-west current hits the EAC.</p>
          </div>
          <div>
            <p class="text-xs font-bold text-white uppercase mb-1">Moon &amp; Wind</p>
            <p class="text-[11px] text-slate-400">Lead up to full moon &amp; northerly wind. Avoid full moon day &amp; southerlies.</p>
          </div>
          <div>
            <p class="text-xs font-bold text-white uppercase mb-1">Find the Fish</p>
            <p class="text-[11px] text-slate-400">Follow mutton birds (most reliable). Bait &amp; whales = tuna nearby.</p>
          </div>
        </div>
        <div class="shrink-0 text-slate-950 px-5 py-3 rounded-xl font-black italic text-center text-sm leading-snug" style="background:var(--gold)">
          GOOD PLANNING<br/>+ GOOD WATER<br/>= YELLOWFIN ON THE DECK!
        </div>
      </div>
    </footer>

  </div>
</main>

</body>
</html>
"""


def build_catching_tactics_html() -> str:
    """Return the complete HTML for the Catching Tactics guide page."""
    return _HTML
