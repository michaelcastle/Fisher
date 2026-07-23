"""
Standalone "Moon & Tides" detail page for a single date.

Follows the same rendering convention as visualize.py::build_folium_map()
(a plain Python string template producing a complete, self-contained HTML
document -- no Jinja, no build step), but is NOT a Folium map: it's a small
dark glass-panel/bento-grid dashboard styled after Michael's mockup
(Tailwind CDN utility classes, Material Symbols icons, JetBrains Mono for
data readouts), reusing the same navy/cyan palette and "Yellowfin Tuna /
Bite Score Intelligence" branding already established in visualize.py's
sidebar.

Only three sections are backed by real data today:
  - Lunar Cycle (phase name, illumination %, phase age) -- from
    GET /api/moon-phase/<date> (webapp.py), which reads the
    `moon_phase.json` side-file main.py writes per date
    (see moon_phase.py::moon_phase_details()).
  - Bite Score multiplier -- recomputed client-side from the same
    illumination_fraction using the exact formula/bounds already used by
    overlay.py::apply_moon_phase_multiplier() / config.MOON_MULTIPLIER_MIN/MAX
    (mirrors the existing bsq-moon-stat readout in visualize.py).
  - Moonrise / moonset -- also from the same JSON payload; Ripley's
    `moon_phase_details()` computes these via `astral.moon.moonrise()`/
    `moonset()` for the AOI centroid (confirmed real, not a common
    misconception -- astral does compute actual moon transit times, just
    not tides). Shown in UTC since there's no per-observer timezone/GPS
    picker; astral genuinely returns no rise or no set for some
    dates/locations (moon already up / stays below the horizon all day),
    reported as "Does not rise/set today" rather than omitted or faked.
  - Solunar Peak Windows -- also from the same JSON payload's
    `solunar_periods` field (Ripley's `moon_phase_details()`, real
    elevation-extrema/moonrise/moonset based windows, see
    `.squad/decisions/inbox/ripley-solunar-peak-windows.md`). Rendered as
    4 cards (2 "major" ~2hr windows around moon transit/antitransit, 2
    "minor" ~1hr windows around moonrise/moonset), each shown as a UTC
    start-end range, or the sibling `note` text when a minor period's
    underlying moonrise/moonset genuinely doesn't occur that day. Solunar
    theory is a fishing heuristic, not exact science -- a short caveat is
    shown under the section header.
  - Tidal Dynamics -- REAL data (as of 2026-07-22, supersedes the earlier
    permanent-"not available" placeholder -- see
    `.squad/decisions/inbox/ripley-tide-data-ingestion.md`): current tide
    state (Flooding/Ebbing/Slack) plus next High/Low turning point times,
    for BOTH Tangalooma (Moreton Island) and Maroochydore (adjacent to
    Mooloolaba, Sunshine Coast), from `GET /api/tide-state/<date>`
    (webapp.py), which calls `data_ingestion.fetch_tide_data()` +
    `tide.classify_tide_state()`/`tide.next_tide_events()`. The underlying
    QLD DES feed is a live ~7-day ROLLING window (not tied to the archived
    date this page otherwise shows), so this section is always evaluated
    at each site's own latest fetched sample, not the local system clock
    (a sandboxed/demo clock can drift out of sync with the feed's
    real-world anchor time) -- viewing an older archived date will
    correctly show "not available" for this section rather than
    mislabeling today's tide state as that old date's. Current
    velocity/stream-speed is still NOT available in this feed (only water
    level/state/timing) -- explicitly labeled as such rather than
    fabricated.
  - Location -- real `config.AOI` bounding box + centroid (no named
    sub-regions exist in config.py, so plain bounds/centroid coordinates
    are shown rather than invented city names). There's no interactive
    GPS picker or minimap graphic -- illumination/multiplier/solunar
    values are identical across the whole AOI.
"""
import html

from . import config

_BRAND_NAME = "Yellowfin Tuna"
_BRAND_TAGLINE = "Bite Score Intelligence"


def build_moon_tide_page_html(date: str) -> str:
    """Return the complete standalone HTML document for /moon/<date>."""
    safe_date = html.escape(date)
    multiplier_min = config.MOON_MULTIPLIER_MIN
    multiplier_max = config.MOON_MULTIPLIER_MAX
    aoi_centroid_lat = (config.AOI["min_lat"] + config.AOI["max_lat"]) / 2.0
    aoi_centroid_lon = (config.AOI["min_lon"] + config.AOI["max_lon"]) / 2.0
    # config.AOI has no named sub-regions (Sunshine Coast/Brisbane/Gold Coast
    # are just prose in its comment, not separate keys) -- show the real
    # bounding box plainly rather than inventing fake per-city coordinates.
    aoi_lat_range = f'{abs(config.AOI["max_lat"]):.1f}\u00b0S \u2013 {abs(config.AOI["min_lat"]):.1f}\u00b0S'
    aoi_lon_range = f'{config.AOI["min_lon"]:.1f}\u00b0E \u2013 {config.AOI["max_lon"]:.1f}\u00b0E'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Moon &amp; Tides &middot; {safe_date} &middot; {_BRAND_NAME}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=block" rel="stylesheet">
<script src="https://cdn.tailwindcss.com"></script>
<script>
  tailwind.config = {{
    theme: {{
      extend: {{
        colors: {{
          navy: {{ 950: '#0b1326', 900: '#0f1830', 800: '#171f33', 700: '#222a3d' }},
          cyan: {{ 400: '#63f7ff' }},
        }},
        fontFamily: {{
          sans: ['Inter', 'ui-sans-serif', 'system-ui'],
          mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
        }},
      }},
    }},
  }};
</script>
<style>
  body {{ background: radial-gradient(circle at top left, #101c38 0%, #0b1326 55%, #070c18 100%); }}
  .material-symbols-outlined {{ font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24; vertical-align: middle; }}
  .glass-panel {{
    background: rgba(23, 31, 51, 0.55);
    border: 1px solid rgba(142, 145, 152, 0.18);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
  }}
  .mono {{ font-family: 'JetBrains Mono', monospace; }}
</style>
</head>
<body class="min-h-screen text-slate-200 font-sans">
  <header class="flex items-center justify-between px-6 md:px-10 py-5 border-b border-white/10">
    <div class="flex items-center gap-3">
      <a href="/history/{safe_date}" class="flex items-center gap-2 text-slate-400 hover:text-cyan-400 transition-colors" title="Back to map">
        <span class="material-symbols-outlined text-xl">arrow_back</span>
      </a>
      <div>
        <h1 class="text-lg font-extrabold tracking-tight text-white">{_BRAND_NAME}</h1>
        <p class="text-[11px] uppercase tracking-widest text-cyan-400/80">{_BRAND_TAGLINE} &middot; Moon &amp; Tides</p>
      </div>
    </div>
    <div class="text-right">
      <p class="text-[10px] uppercase tracking-widest text-slate-500">Data date</p>
      <p class="mono text-base text-cyan-400" id="mtp-date">{safe_date}</p>
    </div>
  </header>

  <main class="px-6 md:px-10 py-8 max-w-6xl mx-auto">
    <div id="mtp-unavailable-banner" class="hidden mb-6 glass-panel rounded-xl px-5 py-3 text-sm text-amber-300 flex items-center gap-2">
      <span class="material-symbols-outlined text-lg">warning</span>
      <span>No moon-phase data has been processed for {safe_date} yet. Run the pipeline for this date, then reload.</span>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-5">

      <!-- Lunar Cycle: REAL data (moon_phase.py via astral) -->
      <section class="glass-panel rounded-2xl p-6 md:col-span-2 flex flex-col justify-between">
        <div class="flex items-start justify-between">
          <div>
            <p class="text-[11px] uppercase tracking-widest text-slate-500 mb-1">Lunar Cycle</p>
            <h2 class="text-3xl font-extrabold text-white" id="mtp-phase-name">Loading&hellip;</h2>
          </div>
          <span class="material-symbols-outlined text-5xl text-cyan-400">nightlight</span>
        </div>
        <div class="grid grid-cols-2 gap-4 mt-6">
          <div>
            <p class="text-[11px] uppercase tracking-widest text-slate-500">Illumination</p>
            <p class="mono text-2xl text-cyan-400" id="mtp-illumination">&ndash;</p>
            <div class="mt-2 h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
              <div class="h-full bg-cyan-400 rounded-full" id="mtp-illumination-bar" style="width:0%"></div>
            </div>
          </div>
          <div>
            <p class="text-[11px] uppercase tracking-widest text-slate-500">Phase age</p>
            <p class="mono text-2xl text-cyan-400" id="mtp-phase-age">&ndash;</p>
            <p class="text-[11px] text-slate-500 mt-1">days into the ~29.5-day lunar cycle</p>
          </div>
        </div>
      </section>

      <!-- Bite Score multiplier: REAL, reuses overlay.py's formula/bounds -->
      <section class="glass-panel rounded-2xl p-6 flex flex-col justify-between">
        <div>
          <p class="text-[11px] uppercase tracking-widest text-slate-500 mb-1">Bite Score Multiplier</p>
          <p class="text-[11px] text-slate-500">Applied uniformly to the day's Bite Score</p>
        </div>
        <p class="mono text-5xl font-semibold text-cyan-400 my-4" id="mtp-multiplier">&ndash;</p>
        <p class="text-xs text-slate-500 leading-relaxed">
          Brighter moons suppress baitfish vertical migration, so the multiplier
          ranges {multiplier_min:.1f}&times; (full moon) to {multiplier_max:.1f}&times; (new moon).
        </p>
      </section>

      <!-- Tidal Dynamics: REAL data (QLD DES storm-tide feed, see bite_score/tide.py + data_ingestion.py::fetch_tide_data()) for both configured sites -->
      <section class="glass-panel rounded-2xl p-6 md:col-span-3">
        <div class="flex items-center gap-3 mb-1">
          <span class="material-symbols-outlined text-2xl text-cyan-400">ssid_chart</span>
          <h3 class="font-semibold text-slate-200">Tidal Dynamics</h3>
          <span class="ml-auto text-[10px] uppercase tracking-widest bg-cyan-400/10 text-cyan-400 px-2 py-1 rounded-full">Live &middot; QLD DES</span>
        </div>
        <p class="text-[11px] text-slate-500 mb-4">
          Real water-level state and next High/Low turning points from the Queensland
          Government DES storm-tide feed (10-minute samples, live ~7-day rolling window
          &ndash; not tied to the archived date above, since only the current live window
          exists). Current velocity/stream speed is still <strong>not available</strong>
          in this feed &mdash; only water level, tide state, and turning-point timing are real.
        </p>
        <div id="mtp-tide-unavailable" class="hidden mb-4 rounded-xl bg-amber-400/10 text-amber-300 text-xs px-4 py-3 flex items-center gap-2">
          <span class="material-symbols-outlined text-base">warning</span>
          <span>Tide data temporarily unavailable &mdash; the live feed could not be reached. Try reloading shortly.</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="rounded-xl bg-white/5 p-4" data-tide-site="tangalooma">
            <div class="flex items-start justify-between mb-2">
              <div>
                <p class="text-[10px] uppercase tracking-widest text-slate-500" data-field="feed-name">tangalooma</p>
                <p class="font-semibold text-slate-200" data-field="location-name">Tangalooma, Moreton Island</p>
              </div>
              <span class="material-symbols-outlined text-3xl text-slate-500" data-field="arrow">trending_flat</span>
            </div>
            <p class="mono text-xl text-cyan-400 mb-3" data-field="state">Loading&hellip;</p>
            <div class="grid grid-cols-2 gap-3 text-xs">
              <div>
                <p class="text-[10px] uppercase tracking-widest text-slate-500">Next High</p>
                <p class="mono text-cyan-400" data-field="next-high">&ndash;</p>
              </div>
              <div>
                <p class="text-[10px] uppercase tracking-widest text-slate-500">Next Low</p>
                <p class="mono text-cyan-400" data-field="next-low">&ndash;</p>
              </div>
            </div>
          </div>
          <div class="rounded-xl bg-white/5 p-4" data-tide-site="maroochydore">
            <div class="flex items-start justify-between mb-2">
              <div>
                <p class="text-[10px] uppercase tracking-widest text-slate-500" data-field="feed-name">maroochydore</p>
                <p class="font-semibold text-slate-200" data-field="location-name">Maroochydore (adjacent to Mooloolaba), Sunshine Coast</p>
              </div>
              <span class="material-symbols-outlined text-3xl text-slate-500" data-field="arrow">trending_flat</span>
            </div>
            <p class="mono text-xl text-cyan-400 mb-3" data-field="state">Loading&hellip;</p>
            <div class="grid grid-cols-2 gap-3 text-xs">
              <div>
                <p class="text-[10px] uppercase tracking-widest text-slate-500">Next High</p>
                <p class="mono text-cyan-400" data-field="next-high">&ndash;</p>
              </div>
              <div>
                <p class="text-[10px] uppercase tracking-widest text-slate-500">Next Low</p>
                <p class="mono text-cyan-400" data-field="next-low">&ndash;</p>
              </div>
            </div>
          </div>
        </div>
        <p class="text-[11px] text-slate-500 mt-3">Times shown in Australia/Brisbane local time (AEST, fixed UTC+10 year-round &ndash; Queensland does not observe daylight saving).</p>
      </section>

      <!-- Moonrise / Moonset: REAL data (astral.moon.moonrise/moonset for the AOI centroid) -->
      <section class="glass-panel rounded-2xl p-6">
        <div class="flex items-center gap-3 mb-3">
          <span class="material-symbols-outlined text-2xl text-cyan-400">schedule</span>
          <h3 class="font-semibold text-slate-200">Moonrise / Moonset</h3>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <p class="text-[11px] uppercase tracking-widest text-slate-500">Rise (UTC)</p>
            <p class="mono text-lg text-cyan-400" id="mtp-moonrise">&ndash;</p>
          </div>
          <div>
            <p class="text-[11px] uppercase tracking-widest text-slate-500">Set (UTC)</p>
            <p class="mono text-lg text-cyan-400" id="mtp-moonset">&ndash;</p>
          </div>
        </div>
        <p class="text-[11px] text-slate-500 mt-3">Computed for the AOI centroid (no per-spot GPS picker yet -- see Location below).</p>
      </section>

      <!-- Solunar Peak Windows: REAL data (moon_phase.py::moon_phase_details()'s solunar_periods field -- transit/antitransit elevation extrema + moonrise/moonset, see .squad/decisions/inbox/ripley-solunar-peak-windows.md) -->
      <section class="glass-panel rounded-2xl p-6 md:col-span-3">
        <div class="flex items-center gap-3 mb-1">
          <span class="material-symbols-outlined text-2xl text-cyan-400">timeline</span>
          <h3 class="font-semibold text-slate-200">Solunar Peak Windows</h3>
        </div>
        <p class="text-[11px] text-slate-500 mb-4">
          Solunar theory (major windows around moon transit/antitransit, minor windows
          around moonrise/moonset) is a fishing heuristic used by anglers, not exact
          science &ndash; treat these as rough &ldquo;better odds&rdquo; windows, not precise predictions.
        </p>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div class="rounded-xl bg-white/5 p-4" data-solunar="major_1">
            <p class="text-[10px] uppercase tracking-widest text-cyan-400/80 mb-1">Major</p>
            <p class="text-xs text-slate-400 mb-2" data-field="description">&ndash;</p>
            <p class="mono text-sm text-cyan-400" data-field="range">&ndash;</p>
          </div>
          <div class="rounded-xl bg-white/5 p-4" data-solunar="major_2">
            <p class="text-[10px] uppercase tracking-widest text-cyan-400/80 mb-1">Major</p>
            <p class="text-xs text-slate-400 mb-2" data-field="description">&ndash;</p>
            <p class="mono text-sm text-cyan-400" data-field="range">&ndash;</p>
          </div>
          <div class="rounded-xl bg-white/5 p-4" data-solunar="minor_1">
            <p class="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Minor</p>
            <p class="text-xs text-slate-400 mb-2" data-field="description">&ndash;</p>
            <p class="mono text-sm text-cyan-400" data-field="range">&ndash;</p>
          </div>
          <div class="rounded-xl bg-white/5 p-4" data-solunar="minor_2">
            <p class="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Minor</p>
            <p class="text-xs text-slate-400 mb-2" data-field="description">&ndash;</p>
            <p class="mono text-sm text-cyan-400" data-field="range">&ndash;</p>
          </div>
        </div>
        <p class="text-[11px] text-slate-500 mt-3">Times in UTC (no per-observer timezone conversion yet &ndash; computed for the AOI centroid, see Location below).</p>
      </section>

      <!-- Location: REAL data (config.AOI bounding box/centroid -- no named sub-regions exist in config.py, no interactive GPS picker/minimap implemented) -->
      <section class="glass-panel rounded-2xl p-6 md:col-span-3">
        <div class="flex items-center gap-3 mb-2">
          <span class="material-symbols-outlined text-2xl text-cyan-400">pin_drop</span>
          <h3 class="font-semibold text-slate-200">Location &mdash; Analysis Area</h3>
        </div>
        <p class="text-xs text-slate-500 mb-3">
          There's no interactive per-spot GPS picker implemented &ndash; illumination,
          multiplier, and the solunar windows above apply uniformly across the whole
          area of interest (AOI) below, and are computed for its centroid.
        </p>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <p class="text-[11px] uppercase tracking-widest text-slate-500">Bounding box</p>
            <p class="mono text-base text-cyan-400">{aoi_lat_range} &middot; {aoi_lon_range}</p>
          </div>
          <div>
            <p class="text-[11px] uppercase tracking-widest text-slate-500">Centroid</p>
            <p class="mono text-base text-cyan-400">{aoi_centroid_lat:.3f}, {aoi_centroid_lon:.3f}</p>
          </div>
        </div>
        <p class="text-[11px] text-slate-500 mt-3">Southeast Queensland, Australia &mdash; covers the Sunshine Coast, Moreton Bay/Brisbane, and Gold Coast shelf. See the map for spatial layers.</p>
      </section>

    </div>
  </main>

  <script>
    var mtpDate = {safe_date!r};
    var MULTIPLIER_MIN = {multiplier_min};
    var MULTIPLIER_MAX = {multiplier_max};

    fetch("/api/moon-phase/" + encodeURIComponent(mtpDate), {{cache: "no-store"}})
      .then(function (r) {{ if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }})
      .then(function (data) {{
        var illum = data.illumination_fraction;
        if (typeof illum !== "number") throw new Error("missing illumination_fraction");

        document.getElementById("mtp-illumination").textContent = Math.round(illum * 100) + "%";
        document.getElementById("mtp-illumination-bar").style.width = Math.round(illum * 100) + "%";

        if (typeof data.phase_name === "string") {{
          document.getElementById("mtp-phase-name").textContent = data.phase_name;
        }} else {{
          document.getElementById("mtp-phase-name").textContent = "Illumination " + Math.round(illum * 100) + "%";
        }}

        if (typeof data.phase_age_days === "number") {{
          document.getElementById("mtp-phase-age").textContent = data.phase_age_days.toFixed(1);
        }} else {{
          document.getElementById("mtp-phase-age").textContent = "n/a";
        }}

        // Same formula as overlay.py::apply_moon_phase_multiplier /
        // visualize.py's bsqLoadMoonPhase() -- keep in sync with both if
        // the formula or config.MOON_MULTIPLIER_MIN/MAX ever change.
        var multiplier = MULTIPLIER_MAX - illum * (MULTIPLIER_MAX - MULTIPLIER_MIN);
        document.getElementById("mtp-multiplier").textContent = multiplier.toFixed(2) + "\\u00d7";

        // Real moonrise/moonset (astral.moon.moonrise/moonset for the AOI
        // centroid, see moon_phase.py::moon_phase_details()) -- astral
        // genuinely returns no rise or no set for some dates/locations
        // (moon already up, or stays below the horizon, all day), so a
        // `null` value with a "_note" explanation is a real astronomical
        // outcome, not missing data -- shown as-is rather than omitted.
        function formatMoonTime(iso, note) {{
          if (typeof iso === "string") {{
            var d = new Date(iso);
            return d.toLocaleTimeString("en-GB", {{hour: "2-digit", minute: "2-digit", timeZone: "UTC"}});
          }}
          return note || "Does not occur today";
        }}
        document.getElementById("mtp-moonrise").textContent = formatMoonTime(data.moonrise, data.moonrise_note);
        document.getElementById("mtp-moonset").textContent = formatMoonTime(data.moonset, data.moonset_note);

        // Real solunar peak windows (moon_phase.py::moon_phase_details()'s
        // solunar_periods field, see
        // .squad/decisions/inbox/ripley-solunar-peak-windows.md). major_1/
        // major_2 (transit/antitransit) are geometric elevation extrema and
        // always have a start/center/end; minor_1/minor_2 (moonrise/
        // moonset +/-30min) can be null+"note" on a day the moon genuinely
        // doesn't rise/set -- shown as the note text rather than a blank
        // range, same convention as the top-level moonrise/moonset above.
        var SOLUNAR_KEYS = ["major_1", "major_2", "minor_1", "minor_2"];
        var periods = (data.solunar_periods && typeof data.solunar_periods === "object") ? data.solunar_periods : {{}};
        SOLUNAR_KEYS.forEach(function (key) {{
          var card = document.querySelector('[data-solunar="' + key + '"]');
          if (!card) return;
          var period = periods[key];
          var descEl = card.querySelector('[data-field="description"]');
          var rangeEl = card.querySelector('[data-field="range"]');
          if (!period) {{
            descEl.textContent = "\\u2013";
            rangeEl.textContent = "\\u2013";
            return;
          }}
          descEl.textContent = period.description || key;
          if (typeof period.start === "string" && typeof period.end === "string") {{
            rangeEl.textContent = formatMoonTime(period.start, null) + " \\u2013 " + formatMoonTime(period.end, null);
          }} else {{
            rangeEl.textContent = period.note || "Does not occur today";
          }}
        }});
      }})
      .catch(function (e) {{
        console.warn("Moon phase unavailable for " + mtpDate, e);
        document.getElementById("mtp-unavailable-banner").classList.remove("hidden");
        document.getElementById("mtp-phase-name").textContent = "No data";
        document.getElementById("mtp-multiplier").textContent = "\\u2013";
        document.getElementById("mtp-moonrise").textContent = "\\u2013";
        document.getElementById("mtp-moonset").textContent = "\\u2013";
        ["major_1", "major_2", "minor_1", "minor_2"].forEach(function (key) {{
          var card = document.querySelector('[data-solunar="' + key + '"]');
          if (!card) return;
          card.querySelector('[data-field="description"]').textContent = "\\u2013";
          card.querySelector('[data-field="range"]').textContent = "\\u2013";
        }});
      }});

    // Real Tidal Dynamics data (QLD DES storm-tide feed, see
    // bite_score/tide.py + data_ingestion.py::fetch_tide_data(), served
    // via GET /api/tide-state/<date> with a server-side in-memory cache
    // -- see webapp.py::_get_tide_dataframe()). The feed is a live ~7-day
    // rolling window, always evaluated at each site's own latest fetched
    // sample (not the local system clock), so this section can
    // legitimately show "not available" for archived dates outside that
    // window -- that's a real/honest outcome, not a bug.
    var TIDE_ARROW_ICON = {{Flooding: "arrow_upward", Ebbing: "arrow_downward", Slack: "trending_flat"}};
    var TIDE_ARROW_COLOR = {{Flooding: "text-emerald-400", Ebbing: "text-rose-400", Slack: "text-slate-500"}};

    function formatTideTime(iso) {{
      if (typeof iso !== "string") return "\\u2013";
      var d = new Date(iso);
      return d.toLocaleString("en-AU", {{
        weekday: "short", hour: "2-digit", minute: "2-digit",
        timeZone: "Australia/Brisbane",
      }});
    }}

    function renderTideSiteUnavailable(card, message) {{
      card.querySelector('[data-field="state"]').textContent = message || "Not available";
      card.querySelector('[data-field="next-high"]').textContent = "\\u2013";
      card.querySelector('[data-field="next-low"]').textContent = "\\u2013";
      var arrowEl = card.querySelector('[data-field="arrow"]');
      arrowEl.textContent = "trending_flat";
      arrowEl.className = "material-symbols-outlined text-3xl text-slate-500";
    }}

    fetch("/api/tide-state/" + encodeURIComponent(mtpDate), {{cache: "no-store"}})
      .then(function (r) {{ if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }})
      .then(function (data) {{
        var sites = (data.sites && typeof data.sites === "object") ? data.sites : {{}};
        ["tangalooma", "maroochydore"].forEach(function (siteCode) {{
          var card = document.querySelector('[data-tide-site="' + siteCode + '"]');
          if (!card) return;
          var site = sites[siteCode];
          if (!site) {{
            renderTideSiteUnavailable(card, "No data");
            return;
          }}
          if (site.location_name) {{
            card.querySelector('[data-field="location-name"]').textContent = site.location_name;
          }}
          if (!site.available) {{
            renderTideSiteUnavailable(card, "Not available for " + mtpDate);
            return;
          }}
          card.querySelector('[data-field="state"]').textContent = site.state;
          var arrowEl = card.querySelector('[data-field="arrow"]');
          arrowEl.textContent = TIDE_ARROW_ICON[site.state] || "trending_flat";
          arrowEl.className = "material-symbols-outlined text-3xl " + (TIDE_ARROW_COLOR[site.state] || "text-slate-500");

          var nextHigh = site.next_high;
          var nextLow = site.next_low;
          card.querySelector('[data-field="next-high"]').textContent = nextHigh
            ? formatTideTime(nextHigh.time) + " (" + nextHigh.height_m.toFixed(2) + "m)"
            : "\\u2013";
          card.querySelector('[data-field="next-low"]').textContent = nextLow
            ? formatTideTime(nextLow.time) + " (" + nextLow.height_m.toFixed(2) + "m)"
            : "\\u2013";
        }});
      }})
      .catch(function (e) {{
        console.warn("Tide state unavailable for " + mtpDate, e);
        document.getElementById("mtp-tide-unavailable").classList.remove("hidden");
        ["tangalooma", "maroochydore"].forEach(function (siteCode) {{
          var card = document.querySelector('[data-tide-site="' + siteCode + '"]');
          if (card) renderTideSiteUnavailable(card, "Unavailable");
        }});
      }});
  </script>
</body>
</html>
"""
