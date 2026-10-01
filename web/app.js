/* Free Food Map front end: day tabs, event cards, Leaflet map, audience filter, shared Going/Skip votes.
   Works as an installable app (see manifest.webmanifest and sw.js). Runs in three homes:
   the local serve.py, a static web host such as GitHub Pages (votes via Supabase, see config.js),
   and a claude.ai Artifact (votes in the page's own database). */
(function () {
  "use strict";

  const TZ = "America/New_York";
  const TYPE_CLASS = {
    Lunch: "lunch", Dinner: "dinner", Breakfast: "breakfast", Pizza: "pizza", Reception: "reception",
    Snacks: "snacks", Coffee: "coffee", Sweets: "sweets", Food: "food",
  };
  const TYPE_LABEL = { Snacks: "Snacks", Coffee: "Coffee & tea", Food: "Food" };
  const REG_LABEL = { required: "Registration required", recommended: "RSVP recommended", none: "No registration", unknown: "Registration not stated" };
  const MOBILE = window.matchMedia("(max-width: 899px)");

  const store = {   // localStorage can be unavailable (private mode): never let that break the page
    get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* ignore */ } },
  };

  const state = {
    data: null, day: null, cert: "all", aud: "open", types: new Set(), skipReg: false, hideDone: true,
    popular: false, q: "", sel: null, view: "list", votes: {}, voteApi: false,
    device: deviceId(), name: store.get("ffm_name", ""),
  };
  let map, markerLayer, homeMarker, markersById = {}, installEvent = null;

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const typeColor = (t) => `var(--t-${TYPE_CLASS[t] || "food"})`;
  const ICON = {
    check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    x: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17"/></svg>',
  };

  function deviceId() {
    let id = store.get("ffm_device");
    if (!id) {
      const b = new Uint8Array(12);
      crypto.getRandomValues(b);                     // works on plain http too, unlike randomUUID
      id = "d" + Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
      store.set("ffm_device", id);
    }
    return id;
  }

  // ---------- time (always Eastern Time) ----------
  const dayKey = (d) => new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  const fmtTime = (iso) => new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" }).format(new Date(iso));
  const fmtDay = (key, opts) => new Intl.DateTimeFormat("en-US", { timeZone: "UTC", ...opts }).format(new Date(key + "T12:00:00Z"));
  function timeRange(ev) {
    if (ev.all_day) return "All day";
    const s = fmtTime(ev.start);
    if (!ev.end) return s;
    const e = fmtTime(ev.end), [sn, sp] = s.split(" "), [en, ep] = e.split(" ");
    return sp === ep ? `${sn}–${en} ${ep}` : `${s}–${e}`;
  }
  function isOver(ev) {
    const end = ev.end ? new Date(ev.end) : new Date(new Date(ev.start).getTime() + 3600e3);
    return end < new Date();
  }

  // ---------- data ----------
  async function load() {
    const r = await fetch("events.json?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error("No data yet. The first scan may still be running.");
    state.data = await r.json();
    const days = dayList(), today = dayKey(new Date());
    if (!state.day || !days.includes(state.day)) state.day = days.includes(today) ? today : days[0];
    renderAll();
    offlineBanner();
    if (state.view === "suggest") renderSuggestions();
    if (backend === "db") tallyDb();          // event aliases are known now
    else if (backend === "supabase") loadVotes();
  }

  // ---------- votes ----------
  // Two homes for the same Going/Skip votes:
  //   "server": the local serve.py (/api/votes), fellows identified by a device id and optional name
  //   "db":     hosted on claude.ai, the page's shared database; one document per person at
  //             votes/<their id> = {v: {eventId: {v: "going"|"skip", t}}}, names from their Claude profile
  let backend = null;
  const dbv = { db: null, user: null, uid: null, docs: [], mine: null, readOnly: false, queue: Promise.resolve() };

  async function initVotes() {
    if (window.claude && typeof window.claude.use === "function") {
      const [db, user] = await Promise.all([window.claude.use("db"), window.claude.use("user")]);
      if (db) {
        Object.assign(dbv, { db, user, uid: user ? await user.id() : null });
        // Viewers may read votes; voting needs Editor access (a refused write also switches this on)
        const canWrite = user ? await user.can("data.write") : null;
        dbv.readOnly = !dbv.uid || canWrite === false;
        backend = "db";
        state.voteApi = true;
        $(".namefield").hidden = true;                    // names come from Claude accounts here
        db.collection("votes").onSnapshot((snap) => { dbv.docs = snap.docs; tallyDb(); },
          () => { backend = null; state.voteApi = false; if (state.data) renderList(); });
        return;
      }
    }
    backend = sbOn() ? "supabase" : "server";
    await loadVotes();
  }

  // "supabase": the static web host (GitHub Pages) keeps votes in a free Supabase table, one row per
  // device and event, configured in config.js (hosting/supabase.sql creates the table)
  const SB = window.FFM_CONFIG || {};
  const sbOn = () => !!(SB.supabaseUrl && SB.supabaseAnonKey);
  function sbFetch(path, opts = {}) {
    return fetch(SB.supabaseUrl.replace(/\/+$/, "") + "/rest/v1/" + path, {
      ...opts,
      // legacy "anon" keys are JWTs and go in both headers; new "sb_publishable_…" keys only in apikey
      headers: { apikey: SB.supabaseAnonKey, ...(SB.supabaseAnonKey.startsWith("eyJ") ? { Authorization: "Bearer " + SB.supabaseAnonKey } : {}),
        "Content-Type": "application/json", ...(opts.headers || {}) },
    });
  }
  function aliasCanon() {
    const canon = {};
    (state.data ? state.data.events : []).forEach((e) => [e.id, ...(e.aliases || [])].forEach((a) => (canon[a] = e.id)));
    return canon;
  }
  async function loadVotesSb() {
    const since = new Date(Date.now() - 30 * 864e5).toISOString();         // votes expire after 30 days
    const r = await sbFetch("votes?select=event_id,device_id,vote,name&updated_at=gte." + encodeURIComponent(since), { cache: "no-store" });
    if (!r.ok) throw new Error("votes " + r.status);
    const canon = aliasCanon(), t = {};
    for (const row of await r.json()) {
      if (row.vote !== "going" && row.vote !== "skip") continue;
      const id = canon[row.event_id] || row.event_id;
      const e = (t[id] = t[id] || { going: 0, skip: 0, names: [], mine: null });
      e[row.vote] += 1;
      if (row.vote === "going" && row.name) e.names.push(row.name);
      if (row.device_id === state.device) e.mine = row.vote;
    }
    state.votes = t;
    state.voteApi = true;
  }
  async function voteSb(id, next) {
    const ev = state.data.events.find((e) => e.id === id);
    const ids = [id, ...((ev && ev.aliases) || [])].map(encodeURIComponent).join(",");
    const del = await sbFetch(`votes?device_id=eq.${encodeURIComponent(state.device)}&event_id=in.(${ids})`, { method: "DELETE" });
    if (!del.ok) throw new Error("delete " + del.status);
    if (next) {
      const r = await sbFetch("votes", { method: "POST", headers: { Prefer: "return=minimal" },
        body: JSON.stringify({ device_id: state.device, event_id: id, vote: next, name: state.name || null,
          updated_at: new Date().toISOString() }) });
      if (!r.ok) throw new Error("insert " + r.status);
    }
  }

  async function loadVotes() {
    if (backend === "supabase") {
      try { await loadVotesSb(); } catch (_) { state.voteApi = false; }
      if (state.data) renderList();
      return;
    }
    if (backend !== "server") return;
    try {
      const r = await fetch("api/votes?device=" + encodeURIComponent(state.device), { cache: "no-store" });
      if (!r.ok) throw 0;
      const j = await r.json();
      state.votes = j.votes || {};
      if (j.name && !state.name) { state.name = j.name; store.set("ffm_name", j.name); }
      state.voteApi = true;
    } catch (_) {
      state.voteApi = false;                           // static hosting or offline: hide vote buttons
    }
    if (state.data) renderList();
  }

  async function tallyDb() {
    const canon = aliasCanon(), t = {};
    for (const d of dbv.docs) {
      const votes = (d.data() || {}).v || {};
      if (d.id === dbv.uid && !dbv.pending) dbv.mine = { ...votes };
      for (const [eid, x] of Object.entries(votes)) {
        if (!x || (x.v !== "going" && x.v !== "skip")) continue;
        const id = canon[eid] || eid;
        const e = (t[id] = t[id] || { going: 0, skip: 0, ids: [], names: [], mine: null });
        e[x.v] += 1;
        if (x.v === "going") e.ids.push(d.id);
        if (d.id === dbv.uid) e.mine = x.v;
      }
    }
    const ids = [...new Set(Object.values(t).flatMap((e) => e.ids))];
    const ps = ids.length && dbv.user ? await dbv.user.profiles(ids) : {};
    Object.values(t).forEach((e) => { e.names = e.ids.map((i) => (ps[i] && ps[i].name) || "").filter(Boolean); });
    state.votes = t;
    if (state.data) renderList();
  }

  function voteDb(id, next) {
    // one write at a time to this person's document, each built from the latest local copy
    dbv.queue = dbv.queue.catch(() => {}).then(async () => {       // a failed write must not block later ones
      dbv.pending = true;
      const mine = { ...(dbv.mine || {}) };
      const ev = state.data.events.find((e) => e.id === id);
      [id, ...((ev && ev.aliases) || [])].forEach((a) => delete mine[a]);
      if (next) mine[id] = { v: next, t: new Date().toISOString() };
      const cutoff = Date.now() - 30 * 864e5;                       // votes expire after 30 days
      Object.keys(mine).forEach((k) => { if (!mine[k] || Date.parse(mine[k].t) < cutoff) delete mine[k]; });
      try {
        await dbv.db.doc("votes/" + dbv.uid).set({ v: mine });
        dbv.mine = mine;
      } finally {
        dbv.pending = false;
      }
    });
    return dbv.queue;
  }

  function dayList() {
    const out = [], w = state.data.window;
    for (let d = new Date(w.start + "T12:00:00Z"); d <= new Date(w.end + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + 1)) out.push(d.toISOString().slice(0, 10));
    return out;
  }

  const isFood = (ev) => ev.food.status === "confirmed" || ev.food.status === "reported" ||
    (state.cert === "all" && ev.food.status === "likely");
  // hidden in the default "Open to fellows" view: stated limits and "probably only …" guesses alike
  const restricted = (ev) => ev.audience && (ev.audience.level === "restricted" || ev.audience.level === "likely");

  function matches(ev, { ignoreTypes = false, ignoreDay = false, ignoreAud = false } = {}) {
    if (!isFood(ev)) return false;
    if (!ignoreDay && ev.date !== state.day) return false;
    if (!ignoreAud && state.aud === "open" && restricted(ev)) return false;
    if (!ignoreTypes && state.types.size && !ev.food.types.some((t) => state.types.has(t))) return false;
    if (state.skipReg && ev.registration.status === "required") return false;
    if (state.hideDone && isOver(ev)) return false;
    if (state.q) {
      const hay = `${ev.title} ${ev.host} ${ev.location} ${ev.place_name} ${ev.summary}`.toLowerCase();
      if (!state.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  }
  const voteOf = (ev) => state.votes[ev.id] || { going: 0, skip: 0, names: [], mine: null };

  // ---------- rendering ----------
  function renderAll() {
    renderHeader(); renderDays(); renderChips(); renderList(); renderSources(); renderFilterCount(); measure();
  }

  function renderHeader() {
    const d = state.data, when = new Date(d.generated_at);
    const stamp = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", hour: "numeric", minute: "2-digit" }).format(when);
    $("#updated").textContent = `Updated ${stamp}`;
    $("#updated").title = `${d.stats.events} events scanned from ${d.sources.filter((s) => s.ok).length}/${d.sources.length} sources`;
  }

  function renderDays() {
    const today = dayKey(new Date());
    $("#days").innerHTML = dayList().map((k) => {
      const n = state.data.events.filter((ev) => ev.date === k && matches(ev, { ignoreDay: true })).length;
      const top = k === today ? "Today" : fmtDay(k, { weekday: "short" });
      return `<button type="button" class="day${k === state.day ? " on" : ""}${n ? "" : " empty"}" data-day="${k}" aria-pressed="${k === state.day}">
        <span class="d1">${top}</span><span class="d2">${fmtDay(k, { month: "short", day: "numeric" })}</span><span class="n">${n}</span></button>`;
    }).join("");
    const on = $("#days .day.on");
    if (on) on.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  function renderChips() {
    const counts = {};
    state.data.events.filter((ev) => matches(ev, { ignoreTypes: true })).forEach((ev) => ev.food.types.forEach((t) => (counts[t] = (counts[t] || 0) + 1)));
    const types = Object.keys(TYPE_CLASS).filter((t) => counts[t] || state.types.has(t));
    $("#chips").innerHTML = types.map((t) =>
      `<button type="button" class="chip${state.types.has(t) ? " on" : ""}" data-type="${t}" style="--c:${typeColor(t)}" aria-pressed="${state.types.has(t)}">
        <span class="dot"></span>${esc(TYPE_LABEL[t] || t)} <span class="cnt">${counts[t] || 0}</span></button>`).join("") ||
      '<span class="flabel">none this day</span>';
  }

  function renderFilterCount() {
    const n = (state.cert === "confirmed") + (state.aud === "all") + state.types.size + state.skipReg + !state.hideDone + state.popular + !!state.q;
    const el = $("#filterCount");
    el.hidden = !n; el.textContent = n;
  }

  function audienceBadge(a) {
    const g = esc(a.group || "a specific group");
    const t = esc(a.evidence || "");
    switch (a.level) {
      case "public": return `<span class="badge aud-public" title="${t}">Open to public</span>`;
      case "harvard": return `<span class="badge aud-harvard" title="${t}">Harvard ID holders</span>`;
      case "restricted": return `<span class="badge aud-restricted" title="${t}">Only ${g}</span>`;
      case "likely": return `<span class="badge aud-likely" title="${t}">Probably only ${g}</span>`;
      default: return `<span class="badge aud-unknown">Audience not stated</span>`;
    }
  }

  function placeLine(ev) {
    let loc = ev.location || "";
    const tail = loc.includes(",") ? loc.slice(loc.lastIndexOf(",") + 1).trim() : "";
    if (tail && ev.place_name && ev.place_name.includes(tail)) loc = loc.slice(0, loc.lastIndexOf(",")).trim();
    const place = ev.place_name && loc && !loc.toLowerCase().startsWith(ev.place_name.toLowerCase().slice(0, 6))
      ? `${esc(loc)} <span class="soft">· ${esc(ev.place_name)}</span>` : esc(loc || ev.place_name || "See event page");
    const walk = ev.walk_min != null ? ` <span class="soft">· ${ev.walk_min} min walk</span>` : "";
    const approx = ev.geo_method === "host" ? ` <span class="soft">(map shows the organizer's building)</span>`
      : ev.geo_method === "text" ? ` <span class="soft">(place read from the event text)</span>` : "";
    return place + walk + approx;
  }

  function voteButtons(ev) {
    if (!state.voteApi) return "";
    const v = voteOf(ev);
    const shown = v.names.slice(0, 3), others = v.going - shown.length;
    const who = !v.going ? "" : shown.length ? `${shown.join(", ")}${others > 0 ? ` +${others}` : ""} going` : `${v.going} going`;
    if (backend === "db" && dbv.readOnly) {                 // can read the votes but not cast one
      const tally = [v.going ? who : "", v.skip ? `${v.skip} say probably no access/food` : ""].filter(Boolean).join(" · ");
      return `<span class="who">${esc(tally || "No votes yet")} <span class="soft">· voting needs Editor access</span></span>`;
    }
    return `<button type="button" class="vote going" data-vote="going" aria-pressed="${v.mine === "going"}" title="I'm going">${ICON.check}Going <span class="n">${v.going || ""}</span></button>
      <button type="button" class="vote skip" data-vote="skip" aria-pressed="${v.mine === "skip"}" title="Probably no access or no food">${ICON.x}Probably no access/food <span class="n">${v.skip || ""}</span></button>
      ${who ? `<span class="who">${esc(who)}</span>` : ""}`;
  }

  function card(ev, i) {
    const t0 = ev.food.types[0] || "Food", c = typeColor(t0), reg = ev.registration, a = ev.audience;
    const v = voteOf(ev);
    const cert = ev.food.status === "confirmed"
      ? `<span class="badge conf" title="The event text says food is served">Food confirmed</span>`
      : ev.food.status === "reported"
        ? `<span class="badge conf" title="A fellow who suggested this event says there is food">Food reported by a fellow</span>`
        : `<span class="badge likely" title="Only the title suggests food">Food likely</span>`;
    const sugg = ev.suggested ? `<span class="badge sugg">Suggested by ${esc(ev.suggested.by || "a fellow")}</span>` : "";
    const rows = [
      ["Where", placeLine(ev)],
      ev.host ? ["Host", esc(ev.host)] : null,
      (a.level === "restricted" || a.level === "likely") && a.evidence ? ["Who", `<span class="soft">${esc(a.evidence)}</span>`] : null,
      ev.notes ? ["Note", esc(ev.notes)] : null,
    ].filter(Boolean);
    const links = ev.url ? [`<a href="${esc(ev.url)}" target="_blank" rel="noopener">Event page ↗</a>`] : [];
    if (reg.link && reg.link !== ev.url && /^https?:/.test(reg.link)) links.push(`<a href="${esc(reg.link)}" target="_blank" rel="noopener">Register ↗</a>`);
    if (ev.lat != null) {
      links.push(`<a href="https://www.google.com/maps/dir/?api=1&amp;destination=${ev.lat},${ev.lon}&amp;travelmode=walking" target="_blank" rel="noopener">Directions ↗</a>`);
      links.push(`<button type="button" class="mobile-only" data-showmap>Map</button>`);
    }
    const src = ev.also_listed.length
      ? `${esc(ev.source_name)}; also on ${ev.also_listed.map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.source_name)}</a>`).join(", ")}`
      : esc(ev.source_name);
    const skipped = v.skip >= 2 && v.skip > v.going;
    return `<article class="card${isOver(ev) ? " done" : ""}${skipped ? " skipped" : ""}${state.sel === ev.id ? " sel" : ""}" data-id="${ev.id}" style="--c:${c}">
      <div class="kicker"><span class="num${ev.lat != null ? "" : " nomap"}" title="${ev.lat != null ? "Marker " + i + " on the map" : "Not on the map"}">${ev.lat != null ? i : "–"}</span>
        <span class="t">${esc(timeRange(ev))}</span><span class="ft">${esc(ev.food.types.map((t) => TYPE_LABEL[t] || t).join(" · ") || "Food")}</span>${isOver(ev) ? "<span>finished</span>" : ""}</div>
      <h2 class="title"><a href="${esc(ev.url)}" target="_blank" rel="noopener">${esc(ev.title)}</a></h2>
      <div class="badges">${cert}${sugg}${audienceBadge(a)}<span class="badge reg-${reg.status}" title="${esc(reg.evidence)}">${REG_LABEL[reg.status]}</span></div>
      ${ev.food.evidence && (ev.food.status === "confirmed" || ev.food.status === "reported") ? `<p class="evidence">“${esc(ev.food.evidence)}”</p>` : ""}
      ${ev.suggested && ev.suggested.note && ev.suggested.note !== ev.food.evidence ? `<p class="evidence soft">${esc(ev.suggested.by || "A fellow")}: “${esc(ev.suggested.note)}”</p>` : ""}
      <div class="meta">${rows.map(([k, val]) => `<div class="row"><span class="k">${k}</span><span class="v">${val}</span></div>`).join("")}</div>
      <div class="actions">${voteButtons(ev)}<span class="links">${links.join("")}</span></div>
      <div class="src">Source: ${src}</div>
    </article>`;
  }

  function sortedDayEvents() {
    const evs = state.data.events.filter((ev) => matches(ev));
    if (state.popular) evs.sort((x, y) => (voteOf(y).going - voteOf(y).skip) - (voteOf(x).going - voteOf(x).skip) || x.start.localeCompare(y.start));
    return evs;
  }

  function renderList() {
    const evs = sortedDayEvents();
    const dayFood = state.data.events.filter((ev) => ev.date === state.day && isFood(ev));
    const hiddenRestricted = state.aud === "open" ? dayFood.filter((ev) => restricted(ev) && matches(ev, { ignoreAud: true })).length : 0;
    const finished = state.hideDone ? dayFood.filter(isOver).length : 0;
    const today = dayKey(new Date());
    const title = state.day === today ? "Today" : fmtDay(state.day, { weekday: "long" });
    let html = `<div class="dayhead"><h1>${title}</h1><span class="sub">${fmtDay(state.day, { month: "long", day: "numeric" })} · ${evs.length} with food</span></div>`;
    const notes = [];
    if (hiddenRestricted) notes.push(`${hiddenRestricted} for students, Houses or clubs only, hidden · <button type="button" class="link-btn" data-showrestricted>Show</button>`);
    if (finished) notes.push(`${finished} already finished`);
    if (MOBILE.matches) notes.push(esc($("#updated").textContent));
    if (notes.length) html += `<p class="note">${notes.join(" · ")}</p>`;
    if (!evs.length) html += `<div class="empty-state">No food events match for this day.<br>Try another day or loosen the filters.</div>`;
    let n = 0;
    const numbered = evs.map((ev) => ({ ev, i: ev.lat != null ? ++n : null }));
    html += numbered.map(({ ev, i }) => card(ev, i)).join("");
    html += `<p class="disclaimer">Unofficial project for Nieman Fellows. Not affiliated with the Nieman Foundation or Harvard.</p>`;
    $("#list").innerHTML = html;
    renderMap(numbered);
  }

  function renderSources() {
    $("#sources").innerHTML = state.data.sources.map((s) =>
      `<tr><td>${s.homepage ? `<a href="${esc(s.homepage)}" target="_blank" rel="noopener">${esc(s.name)}</a>` : esc(s.name)}</td>
       <td class="${s.ok ? "" : "err"}">${s.ok ? "OK" : "Error"}</td><td>${s.n_events}</td><td>${s.n_food}</td></tr>`).join("");
  }

  // ---------- map ----------
  // The basemap is drawn here from basemap.json (OpenStreetMap data, built by tools/build_basemap.py)
  // instead of loading map tiles, so the page works where outside images are blocked (claude.ai hosting).
  let base = null, baseLayer = null, colors = {};
  const toMerc = (lon, lat) => {
    const s = Math.sin((lat * Math.PI) / 180);
    return [(lon + 180) / 360, 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)];
  };
  function decodeBase(j) {
    const [lon0, lat0] = j.origin, layers = {};
    for (const [name, feats] of Object.entries(j.layers)) {
      layers[name] = feats.map((a) => {
        const pts = new Float64Array(a.length);
        let x = 0, y = 0, x0 = 1, y0 = 1, x1 = 0, y1 = 0;
        for (let i = 0; i < a.length; i += 2) {
          x += a[i]; y += a[i + 1];                          // first pair absolute, then deltas
          const [mx, my] = toMerc(lon0 + x / 1e5, lat0 + y / 1e5);
          pts[i] = mx; pts[i + 1] = my;
          if (mx < x0) x0 = mx; if (mx > x1) x1 = mx; if (my < y0) y0 = my; if (my > y1) y1 = my;
        }
        return { pts, bb: [x0, y0, x1, y1] };
      });
    }
    return layers;
  }
  function readColors() {
    const cs = getComputedStyle(document.documentElement), v = (n) => cs.getPropertyValue(n).trim();
    colors = { land: v("--map-land"), building: v("--map-building"), edge: v("--map-building-edge"), green: v("--map-green"),
      water: v("--map-water"), road: v("--map-road"), casing: v("--map-casing"), path: v("--map-path") };
  }
  // line widths in px per zoom: [major, minor, path]
  const WIDTHS = { 13: [1.6, 0.8, 0], 14: [2.4, 1.3, 0], 15: [4, 2.2, 0.7], 16: [7, 4, 1], 17: [12, 7, 1.4], 18: [20, 11, 2] };
  function drawTile(ctx, c) {
    const n = 2 ** c.z, S = 256 * n, ox = c.x * 256, oy = c.y * 256, pad = 24 / S;
    const tb = [c.x / n - pad, c.y / n - pad, (c.x + 1) / n + pad, (c.y + 1) / n + pad];
    ctx.fillStyle = colors.land; ctx.fillRect(0, 0, 256, 256);
    if (!base) return;
    const seen = (f) => f.bb[2] >= tb[0] && f.bb[0] <= tb[2] && f.bb[3] >= tb[1] && f.bb[1] <= tb[3];
    const trace = (f, close) => {
      const p = f.pts; ctx.beginPath(); ctx.moveTo(p[0] * S - ox, p[1] * S - oy);
      for (let i = 2; i < p.length; i += 2) ctx.lineTo(p[i] * S - ox, p[i + 1] * S - oy);
      if (close) ctx.closePath();
    };
    const fill = (layer, color, edge) => {
      ctx.fillStyle = color; if (edge) { ctx.strokeStyle = edge; ctx.lineWidth = 0.6; }
      for (const f of base[layer]) if (seen(f)) { trace(f, true); ctx.fill(); if (edge) ctx.stroke(); }
    };
    const stroke = (layer, w, color, dash) => {
      if (w <= 0) return;
      ctx.strokeStyle = color; ctx.lineWidth = w; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.setLineDash(dash || []);
      for (const f of base[layer]) if (seen(f)) { trace(f, false); ctx.stroke(); }
      ctx.setLineDash([]);
    };
    const [wMaj, wMin, wPath] = WIDTHS[Math.max(13, Math.min(18, c.z))];
    const metersPerPx = (156543.03 * Math.cos((42.37 * Math.PI) / 180)) / n;
    fill("green", colors.green);
    fill("water", colors.water);
    stroke("river", 170 / metersPerPx, colors.water);                   // the Charles, about 170 m wide here
    fill("building", colors.building, c.z >= 16 ? colors.edge : null);
    stroke("path", wPath, colors.path, c.z >= 17 ? [3, 3] : null);
    stroke("minor", wMin + 1.2, colors.casing);
    stroke("major", wMaj + 1.6, colors.casing);
    stroke("minor", wMin, colors.road);
    stroke("major", wMaj, colors.road);
  }
  const BaseLayer = L.GridLayer.extend({
    createTile(c) {
      const t = document.createElement("canvas"), dpr = Math.min(2, window.devicePixelRatio || 1);
      t.width = t.height = 256 * dpr;
      const ctx = t.getContext("2d"); ctx.scale(dpr, dpr);
      drawTile(ctx, c);
      return t;
    },
  });
  function addLabels(j) {
    const pane = map.createPane("labels");
    pane.style.zIndex = 450; pane.style.pointerEvents = "none";   // above the basemap, below the event pins
    j.labels.forEach(([lon, lat, ang, text, kind]) => {
      L.marker([lat, lon], { pane: "labels", interactive: false, keyboard: false,
        icon: L.divIcon({ className: "", iconSize: [0, 0],
          html: `<span class="lbl lbl-${kind}" style="transform: translate(-50%,-50%) rotate(${ang}deg)">${esc(text)}</span>` }),
      }).addTo(map);
    });
  }
  function zoomClasses() {
    const z = map.getZoom(), el = map.getContainer();
    [15, 16, 17].forEach((k) => el.classList.toggle("z" + k, z >= k));
  }

  function initMap() {
    map = L.map("map", { zoomControl: !MOBILE.matches, minZoom: 13, maxZoom: 18 }).setView([42.3745, -71.1182], 15);
    map.attributionControl.setPrefix(false).addAttribution('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors');
    readColors();
    baseLayer = new BaseLayer({ tileSize: 256, maxZoom: 18, updateWhenZooming: false }).addTo(map);
    map.on("zoomend", zoomClasses); zoomClasses();
    const redraw = () => { readColors(); baseLayer.redraw(); };
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redraw);
    new MutationObserver(redraw).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    fetch("basemap.json").then((r) => r.json()).then((j) => { base = decodeBase(j); baseLayer.redraw(); addLabels(j); }).catch(() => {});
    markerLayer = L.layerGroup().addTo(map);
    map.on("click", () => { $("#peek").hidden = true; });
  }

  function renderMap(numbered) {
    markerLayer.clearLayers();
    markersById = {};
    const home = state.data.home;
    if (home && home.lat != null && !homeMarker) {
      homeMarker = L.marker([home.lat, home.lon], {
        icon: L.divIcon({ className: "", html: '<div class="home-pin" title="Lippmann House">N</div>', iconSize: [30, 30], iconAnchor: [15, 15] }),
        zIndexOffset: -100, keyboard: false,
      }).bindPopup("<b>Lippmann House</b><br>Nieman Foundation, 1 Francis Ave").addTo(map);
    }
    const groups = {};
    numbered.filter((x) => x.i).forEach((x) => { const k = x.ev.lat.toFixed(5) + "," + x.ev.lon.toFixed(5); (groups[k] = groups[k] || []).push(x); });
    const pts = [];
    Object.values(groups).forEach((g) => g.forEach(({ ev, i }, k) => {
      const r = g.length > 1 ? 12 + 2.5 * g.length : 0, ang = (2 * Math.PI * k) / g.length - Math.PI / 2;
      const dx = Math.round(r * Math.cos(ang)), dy = Math.round(r * Math.sin(ang));
      const cls = `pin${ev.food.status === "likely" ? " likely" : ""}${restricted(ev) ? " restricted" : ""}${state.sel === ev.id ? " sel" : ""}`;
      const m = L.marker([ev.lat, ev.lon], {
        icon: L.divIcon({ className: "", html: `<div class="${cls}" style="--c:${typeColor(ev.food.types[0])}">${i}</div>`, iconSize: [26, 26], iconAnchor: [13 - dx, 13 - dy], popupAnchor: [dx, dy - 12] }),
        title: ev.title, riseOnHover: true,
      }).addTo(markerLayer);
      if (!MOBILE.matches) {
        m.bindPopup(`<div>${esc(timeRange(ev))}</div><b>${esc(ev.title)}</b><div>${esc(ev.food.types.join(" · "))} · ${esc(ev.place_name)}</div>
          <a class="pop-link" href="${esc(ev.url)}" target="_blank" rel="noopener">Event page ↗</a>`);
      }
      m.on("click", () => select(ev.id, { fromMap: true }));
      markersById[ev.id] = m;
      pts.push([ev.lat, ev.lon]);
    }));
    fitMap(pts);
  }

  function fitMap(pts) {
    pts = pts || Object.values(markersById).map((m) => m.getLatLng());
    const home = state.data.home;
    if (!pts.length) return;
    if (home && home.lat != null) pts = [...pts, [home.lat, home.lon]];
    map.fitBounds(pts, { padding: [36, 36], maxZoom: 16 });
  }

  function showPeek(ev) {
    const i = [...document.querySelectorAll(".card")].findIndex((c) => c.dataset.id === ev.id);
    const p = $("#peek");
    p.style.setProperty("--c", typeColor(ev.food.types[0]));
    p.innerHTML = `<button type="button" class="close" aria-label="Close">${ICON.x}</button>
      <div class="kicker"><span class="t">${esc(timeRange(ev))}</span><span class="ft">${esc(ev.food.types.join(" · "))}</span></div>
      <div class="title">${esc(ev.title)}</div>
      <div class="badges">${audienceBadge(ev.audience)}</div>
      <div class="row2"><span class="soft">${esc(ev.place_name || ev.location)}${ev.walk_min != null ? " · " + ev.walk_min + " min walk" : ""}</span>
        <button type="button" class="link-btn" data-details="${ev.id}">Details</button></div>`;
    p.hidden = i < 0;
  }

  function select(id, { fromMap = false } = {}) {
    state.sel = id;
    document.querySelectorAll(".card").forEach((el) => el.classList.toggle("sel", el.dataset.id === id));
    document.querySelectorAll(".pin.sel").forEach((el) => el.classList.remove("sel"));
    const m = markersById[id];
    const ev = state.data.events.find((e) => e.id === id);
    if (m) {
      const el = m.getElement();
      if (el && el.firstElementChild) el.firstElementChild.classList.add("sel");
      if (!fromMap) { map.panTo(m.getLatLng()); if (!MOBILE.matches) m.openPopup(); }
    }
    if (MOBILE.matches && ev && (fromMap || state.view === "map")) showPeek(ev);
    if (fromMap && !MOBILE.matches) {
      const cardEl = document.querySelector(`.card[data-id="${id}"]`);
      if (cardEl) cardEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  // ---------- views, filters sheet, layout measuring ----------
  function setView(view) {
    state.view = view;
    $("#layout").dataset.view = view;
    document.querySelectorAll(".tabbar button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
    if (view !== "map") $("#peek").hidden = true;
    if (view === "map") setTimeout(() => { map.invalidateSize(); fitMap(); }, 30);
    if (view === "suggest") loadSuggestions();
    if (MOBILE.matches) window.scrollTo(0, 0);
  }

  function toggleSheet(open) {
    $("#filters").classList.toggle("open", open);
    $("#scrim").hidden = !open;
    $("#filterBtn").setAttribute("aria-expanded", open);
  }

  function measure() {
    document.documentElement.style.setProperty("--bar", $(".appbar").offsetHeight + "px");
    const top = MOBILE.matches
      ? $(".appbar").offsetHeight + $("#days").offsetHeight
      : $("#layout").getBoundingClientRect().top + window.scrollY;
    document.documentElement.style.setProperty("--top", top + "px");
    if (map) map.invalidateSize();
  }

  // ---------- votes ----------
  async function vote(id, v) {
    if (backend === "db" && dbv.readOnly) {
      banner("You can see who is going but can't vote on this copy. Ask the owner to share it with you as an Editor.", 6000);
      return;
    }
    const cur = voteOf({ id });
    const next = cur.mine === v ? null : v;                 // same button again = take the vote back
    const opt = { ...cur, names: [...cur.names], mine: next };
    if (cur.mine) opt[cur.mine] = Math.max(0, opt[cur.mine] - 1);
    if (next) opt[next] += 1;
    state.votes[id] = opt;
    renderList(); renderDays();
    try {
      if (backend === "db") {
        await voteDb(id, next);                             // the snapshot listener re-tallies
      } else if (backend === "supabase") {
        await voteSb(id, next);
        await loadVotes();
      } else {
        const r = await fetch("api/vote", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ event_id: id, device: state.device, vote: next }) });
        if (!r.ok) throw 0;
        state.votes[id] = await r.json();
        renderList();
      }
    } catch (e) {
      state.votes[id] = cur; renderList();
      if (backend === "db" && e && e.code === "invalid_argument") {
        dbv.readOnly = true;
        renderList();
        banner("You can see who is going but can't vote on this copy. Ask the owner to share it with you as an Editor.", 6000);
      } else {
        banner("Could not save your vote. Are you online?", 4000);
      }
      return;
    }
    if (backend !== "db" && next === "going" && !state.name && !store.get("ffm_name_asked")) askName();
  }

  function askName() {
    const dlg = $("#nameDlg");
    store.set("ffm_name_asked", "1");
    if (typeof dlg.showModal !== "function") return;
    $("#dlgName").value = "";
    dlg.showModal();
  }

  async function saveName(name) {
    state.name = name.trim().slice(0, 24);
    store.set("ffm_name", state.name);
    $("#nameInput").value = state.name;
    try {
      if (backend === "supabase") {                       // show the new name on this device's existing votes
        await sbFetch("votes?device_id=eq." + encodeURIComponent(state.device), { method: "PATCH",
          headers: { Prefer: "return=minimal" }, body: JSON.stringify({ name: state.name || null }) });
      } else {
        await fetch("api/name", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ device: state.device, name: state.name }) });
      }
      await loadVotes();
    } catch (_) { /* offline: stays local until next vote */ }
  }

  // ---------- suggestions: fellows send event links, newsletters or calendars (web host + Supabase) ----------
  const suggest = { kind: "event", rows: [] };
  const STATUS_CLASS = { on_map: "ok", scanned: "ok", listed_restricted: "warn", later: "wait", review: "wait" };

  function initSuggest() {
    if (backend === "db" || !sbOn()) return;                 // needs the Supabase table; not on claude.ai
    $("#suggestBtn").hidden = false;
    $("#suggestTab").hidden = false;
    $("#sgName").value = state.name || "";
    const fwd = (SB.newsletterForwardAddress || "").trim();
    if (fwd) {
      $("#forwardHint").hidden = false;
      $("#forwardHint").textContent = `Easiest: forward an issue to ${fwd}.`;
      $("#forwardBox").hidden = false;
      $("#forwardAddr").textContent = fwd;
    }
  }

  async function loadSuggestions() {
    try {
      const r = await sbFetch("suggestions?select=id,kind,url,title,note,name,created_at&order=created_at.desc&limit=15", { cache: "no-store" });
      if (!r.ok) throw 0;
      suggest.rows = await r.json();
    } catch (_) {
      suggest.rows = null;
    }
    renderSuggestions();
  }

  function renderNewsletters() {
    const list = (state.data && state.data.newsletters) || [];
    const withEvents = list.filter((n) => n.items > 0).reverse(), others = list.length - withEvents.length;
    let html = withEvents.map((n) => {
      const when = n.sent ? fmtDay(n.sent, { month: "short", day: "numeric" }) : "";
      return `<li><div class="sg-top"><span class="sg-kind">Newsletter${when ? " · " + esc(when) : ""}</span>
          <span class="sg-status ok">${n.items} event${n.items === 1 ? "" : "s"} found</span></div>
        <div class="sg-what">${esc(n.subject || "")}</div></li>`;
    }).join("");
    if (others) html += `<li class="soft">${others} other email${others === 1 ? "" : "s"} read with no events for this week.</li>`;
    $("#newsList").innerHTML = html || `<li class="soft">None in the last two weeks.</li>`;
  }

  function renderSuggestions() {
    renderNewsletters();
    const ul = $("#suggList");
    if (suggest.rows === null) { ul.innerHTML = `<li class="soft">Couldn't load suggestions right now.</li>`; return; }
    if (!suggest.rows.length) { ul.innerHTML = `<li class="soft">No suggestions yet.</li>`; return; }
    const byId = {};
    ((state.data && state.data.suggestions) || []).forEach((s) => (byId[s.id] = s));
    ul.innerHTML = suggest.rows.map((r) => {
      const st = byId[r.id];
      const label = st ? st.label : "Waiting for the next update";
      const cls = st ? STATUS_CLASS[st.state] || "muted" : "wait";
      const text = r.title || (r.url || "").replace(/^https?:\/\/(www\.)?/, "");
      const what = r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text);
      const when = new Intl.DateTimeFormat("en-US", { timeZone: TZ, month: "short", day: "numeric" }).format(new Date(r.created_at));
      return `<li><div class="sg-top"><span class="sg-kind">${r.kind === "event" ? "Event" : "Newsletter or calendar"}</span>
          <span class="sg-status ${cls}">${esc(label)}</span></div>
        <div class="sg-what">${what}</div>
        <div class="sg-meta">${r.name ? esc(r.name) + " · " : ""}${when}${r.note ? ` · “${esc(r.note)}”` : ""}</div></li>`;
    }).join("");
  }

  async function submitSuggestion(e) {
    e.preventDefault();
    const msg = $("#sgMsg");
    const say = (text, kind) => { msg.textContent = text; msg.className = "form-msg" + (kind ? " " + kind : ""); };
    const fixUrl = (u) => { u = u.trim(); return u && !/^https?:\/\//i.test(u) ? "https://" + u : u; };
    const looksLikeUrl = (u) => /^https?:\/\/[^\s/]+\.[^\s]{2,}/i.test(u);
    const name = $("#sgName").value.trim().slice(0, 24);
    let body;
    if (suggest.kind === "event") {
      const url = fixUrl($("#sgUrl").value);
      if (!looksLikeUrl(url)) { say("Paste the link to the event's page.", "err"); $("#sgUrl").focus(); return; }
      body = { kind: "event", url, note: $("#sgNote").value.trim().slice(0, 400) || null };
    } else {
      const title = $("#sgTitle").value.trim().slice(0, 120), url = fixUrl($("#sgSrcUrl").value);
      if (!title && !url) { say("Give the newsletter or calendar a name or a link.", "err"); $("#sgTitle").focus(); return; }
      if (url && !looksLikeUrl(url)) { say("That link doesn't look complete.", "err"); $("#sgSrcUrl").focus(); return; }
      body = { kind: "source", title: title || null, url: url || null, note: $("#sgSrcNote").value.trim().slice(0, 400) || null };
    }
    body.name = name || null;
    $("#sgSend").disabled = true;
    say("Sending…");
    try {
      const r = await sbFetch("suggestions", { method: "POST", headers: { Prefer: "return=minimal" }, body: JSON.stringify(body) });
      if (!r.ok) throw new Error(String(r.status));
      say(body.kind === "event" ? "Thanks! It will be checked at the next update." : "Thanks! It's on the list.", "ok");
      ["#sgUrl", "#sgNote", "#sgTitle", "#sgSrcUrl", "#sgSrcNote"].forEach((sel) => ($(sel).value = ""));
      if (name && name !== state.name) saveName(name);
      loadSuggestions();
    } catch (_) {
      say("Couldn't send it. Check your connection and try again.", "err");
    } finally {
      $("#sgSend").disabled = false;
    }
  }

  // ---------- banners: install and offline ----------
  let bannerTimer;
  function banner(html, ms) {
    const b = $("#banner");
    b.innerHTML = html; b.hidden = false;
    clearTimeout(bannerTimer);
    if (ms) bannerTimer = setTimeout(() => { b.hidden = true; measure(); }, ms);
    measure();
  }
  function offlineBanner() {
    if (!navigator.onLine && state.data) {
      const when = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", hour: "numeric", minute: "2-digit" }).format(new Date(state.data.generated_at));
      banner(`<span class="grow">Offline: showing the list saved ${esc(when)}.</span>`);
    }
  }
  function installBanner() {
    const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
    if (window.claude || standalone || !MOBILE.matches || store.get("ffm_install_dismissed")) return;   // not inside claude.ai
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
    const close = '<button type="button" class="link-btn" data-dismiss-install>Not now</button>';
    if (installEvent) {
      banner(`<span class="grow">Install Free Food Map as an app on this phone.</span><button type="button" class="btn" data-install>Install</button>${close}`);
    } else if (ios) {
      banner(`<span class="grow">Use it like an app: tap <b>Share</b>, then <b>Add to Home Screen</b>.</span>${close}`);
    }
  }

  // ---------- rescan (only when served by serve.py) ----------
  async function setupRescan() {
    const btn = $("#rescan");
    try {
      const r = await fetch("api/status", { cache: "no-store" });
      if (!r.ok) throw 0;
      if ((await r.json()).scanning) pollScan(btn);
    } catch (_) { btn.hidden = true; return; }
    btn.addEventListener("click", async () => { await fetch("api/scan", { method: "POST" }); pollScan(btn); });
  }
  function pollScan(btn) {
    btn.disabled = true;
    const t = setInterval(async () => {
      try {
        const s = await (await fetch("api/status", { cache: "no-store" })).json();
        if (!s.scanning) { clearInterval(t); btn.disabled = false; load(); loadVotes(); }
      } catch (_) { clearInterval(t); btn.disabled = false; }
    }, 3000);
  }

  // ---------- events ----------
  function refilter() { renderDays(); renderChips(); renderList(); renderFilterCount(); }

  function bind() {
    $("#days").addEventListener("click", (e) => {
      const b = e.target.closest(".day"); if (!b) return;
      state.day = b.dataset.day; state.sel = null; $("#peek").hidden = true;
      renderDays(); renderChips(); renderList();
      if (MOBILE.matches && state.view === "list") window.scrollTo({ top: 0 });
    });
    document.querySelectorAll("[data-cert]").forEach((b) => b.addEventListener("click", () => {
      state.cert = b.dataset.cert;
      document.querySelectorAll("[data-cert]").forEach((x) => x.classList.toggle("on", x === b));
      refilter();
    }));
    document.querySelectorAll("[data-aud]").forEach((b) => b.addEventListener("click", () => {
      state.aud = b.dataset.aud;
      document.querySelectorAll("[data-aud]").forEach((x) => x.classList.toggle("on", x === b));
      refilter();
    }));
    $("#chips").addEventListener("click", (e) => {
      const b = e.target.closest(".chip"); if (!b) return;
      const t = b.dataset.type;
      state.types.has(t) ? state.types.delete(t) : state.types.add(t);
      refilter();
    });
    $("#noreg").addEventListener("change", (e) => { state.skipReg = e.target.checked; refilter(); });
    $("#hidedone").addEventListener("change", (e) => { state.hideDone = e.target.checked; refilter(); });
    $("#popular").addEventListener("change", (e) => { state.popular = e.target.checked; refilter(); });
    $("#q").addEventListener("input", (e) => { state.q = e.target.value.trim(); refilter(); });

    $("#list").addEventListener("click", (e) => {
      const card = e.target.closest(".card");
      if (e.target.closest("[data-showrestricted]")) {
        state.aud = "all";
        document.querySelectorAll("[data-aud]").forEach((x) => x.classList.toggle("on", x.dataset.aud === "all"));
        return refilter();
      }
      if (!card) return;
      const vb = e.target.closest("[data-vote]");
      if (vb) return vote(card.dataset.id, vb.dataset.vote);
      if (e.target.closest("[data-showmap]")) { setView("map"); return setTimeout(() => select(card.dataset.id), 60); }
      if (e.target.closest("a")) return;
      if (!MOBILE.matches) select(card.dataset.id);
    });
    $("#peek").addEventListener("click", (e) => {
      if (e.target.closest(".close")) { $("#peek").hidden = true; return; }
      const d = e.target.closest("[data-details]");
      if (d) {
        setView("list");
        const el = document.querySelector(`.card[data-id="${d.dataset.details}"]`);
        if (el) { el.classList.add("sel"); el.scrollIntoView({ block: "center" }); }
      }
    });

    document.querySelectorAll(".tabbar button").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
    $("#aboutBtn").addEventListener("click", () => setView(state.view === "about" ? "list" : "about"));
    $("#aboutClose").addEventListener("click", () => setView("list"));
    $("#suggestBtn").addEventListener("click", () => setView(state.view === "suggest" ? "list" : "suggest"));
    document.querySelectorAll("[data-close-panel]").forEach((b) => b.addEventListener("click", () => setView("list")));
    document.querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => {
      suggest.kind = b.dataset.kind;
      document.querySelectorAll("[data-kind]").forEach((x) => x.classList.toggle("on", x === b));
      $(".kind-event").hidden = suggest.kind !== "event";
      $(".kind-source").hidden = suggest.kind !== "source";
      $("#sgMsg").textContent = "";
    }));
    $("#suggestForm").addEventListener("submit", submitSuggestion);
    $("#copyAddr").addEventListener("click", async () => {
      const addr = $("#forwardAddr").textContent;
      try { await navigator.clipboard.writeText(addr); $("#copyAddr").textContent = "Copied"; }
      catch (_) {                                            // some in-app browsers refuse the clipboard
        const r = document.createRange(); r.selectNodeContents($("#forwardAddr"));
        const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
        $("#copyAddr").textContent = "Selected, copy it";
      }
      setTimeout(() => ($("#copyAddr").textContent = "Copy address"), 2500);
    });
    $("#filterBtn").addEventListener("click", () => toggleSheet(!$("#filters").classList.contains("open")));
    $("#filtersDone").addEventListener("click", () => toggleSheet(false));
    $("#scrim").addEventListener("click", () => toggleSheet(false));

    $("#nameInput").value = state.name;
    $("#nameSave").addEventListener("click", () => saveName($("#nameInput").value));
    $("#nameDlg").addEventListener("close", () => {
      if ($("#nameDlg").returnValue === "save" && $("#dlgName").value.trim()) saveName($("#dlgName").value);
    });

    $("#banner").addEventListener("click", async (e) => {
      if (e.target.closest("[data-dismiss-install]")) { store.set("ffm_install_dismissed", "1"); $("#banner").hidden = true; measure(); }
      if (e.target.closest("[data-install]") && installEvent) {
        installEvent.prompt(); await installEvent.userChoice; installEvent = null; $("#banner").hidden = true; measure();
      }
    });
    window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installEvent = e; installBanner(); });
    window.addEventListener("offline", offlineBanner);
    window.addEventListener("online", () => { $("#banner").hidden = true; measure(); load().catch(() => {}); loadVotes(); });
    window.addEventListener("resize", measure);
    MOBILE.addEventListener("change", () => { setView("list"); toggleSheet(false); if (state.data) renderList(); measure(); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) { loadVotes(); if (state.data) refilter(); } });
  }

  // ---------- start ----------
  // offline/installable only on its own server; a claude.ai-hosted copy runs in a frame without service workers
  try {
    if (!window.claude && "serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("sw.js").catch(() => {});
  } catch (_) { /* sandboxed frame */ }
  initMap();
  bind();
  setupRescan();
  load().catch((err) => {
    $("#updated").textContent = "No data";
    $("#list").innerHTML = `<div class="empty-state">${esc(err.message)}</div>`;
  }).finally(() => { installBanner(); measure(); });
  initVotes().catch(() => { state.voteApi = false; }).finally(initSuggest);
  setInterval(() => load().catch(() => {}), 10 * 60 * 1000);   // pick up background rescans
  setInterval(loadVotes, 45 * 1000);                           // see other fellows' votes
})();
