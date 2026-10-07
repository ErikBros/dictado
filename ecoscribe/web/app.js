/* Ecoscribe window logic. Talks to Python through window.pywebview.api (see ecoscribe/window.py).
   ?demo=1 swaps in a fake API so the page can be screenshotted and smoke-tested anywhere. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const params = new URLSearchParams(location.search);
const LANG_LABEL = { en: "English", "en,es": "English and Spanish", es: "Spanish", sv: "Swedish", el: "Greek" };
// macOS (WKWebView): ?mac=1 forces it for screenshots. Windows wording stays the default everywhere else.
const MAC = /Mac/.test(navigator.platform || "") || new URLSearchParams(location.search).get("mac") === "1";
const HOTKEY_LABEL = { rctrl: MAC ? "Right Control" : "Right Ctrl", scrolllock: "Scroll Lock", pause: "Pause", rcmd: "Right Command", fn: "Fn" };
const DEFAULT_MIC = MAC ? "System default" : "Windows default";
const hotkeyLabel = (k) => HOTKEY_LABEL[k] || (k ? k.split("+").map((p) => (p.length > 1 && !/^f\d/.test(p) ? p[0].toUpperCase() + p.slice(1) : p.toUpperCase())).join("+") : (MAC ? "Right Command" : "Right Ctrl"));

/* ---------------------------------------------------------------- demo API */
function demoInsights(days) {  // invented numbers and text for the demo and screenshots
  const k = days === 7 ? 0.3 : days === 30 ? 0.8 : 1;
  const hours = [0, 0, 0, 0, 0, 0, 1, 3, 8, 12, 10, 6, 4, 9, 14, 11, 7, 4, 2, 3, 2, 1, 0, 0].map((v) => Math.round(v * k));
  const today = new Date();
  const dayList = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(today); d.setDate(today.getDate() - 13 + i);
    return { date: d.toISOString().slice(0, 10), words: [210, 480, 0, 350, 620, 0, 0, 390, 530, 270, 0, 440, 710, 380][i] };
  });
  return {
    days, first: "2026-09-14",
    totals: { dictations: Math.round(240 * k), words: Math.round(11800 * k), talk_s: Math.round(5530 * k), wpm: 128, saved_s: Math.round(12170 * k), typing_wpm: 40 },
    rhythm: { hours, days: dayList, streak: 2 },
    languages: [{ lang: "en", words: Math.round(8200 * k) }, { lang: "sv", words: Math.round(2900 * k) }, { lang: "de", words: Math.round(500 * k) }, { lang: "mixed", words: Math.round(200 * k) }],
    apps: [{ app: "slack.exe", dictations: 96 }, { app: "code.exe", dictations: 71 }, { app: "outlook.exe", dictations: 44 }, { app: "chrome.exe", dictations: 29 }],
    habits: [{ lang: "en", words: 8200, per_100: 3.1, top: [{ word: "like", count: 120 }, { word: "you know", count: 61 }, { word: "basically", count: 40 }, { word: "kind of", count: 33 }] },
      { lang: "sv", words: 2900, per_100: 1.4, top: [{ word: "typ", count: 25 }, { word: "liksom", count: 16 }] }],
    phrases: [{ phrase: "at the end of", count: 18 }, { phrase: "let me check", count: 14 }, { phrase: "as soon as", count: 11 }, { phrase: "on the other hand", count: 9 }],
    suggestions: [{ heard: "Ecoskribe", count: 5, suggest: "Ecoscribe" }, { heard: "Klaude", count: 3, suggest: "Claude" }, { heard: "Kristineberg", count: 3, suggest: "Kristineberg" }],
    clarity: { dictations: Math.round(90 * k), clarity: 91, since: "2026-09-20",
      weeks: [null, null, null, null, 86, 89, 90, 93].map((c, i) => {
        const d = new Date(today); d.setDate(today.getDate() - today.getDay() + 1 - 7 * (7 - i));
        return { week: d.toISOString().slice(0, 10), clarity: c, dictations: c ? 20 : 0 };
      }),
      words: [{ lang: "en", words: [{ word: "particularly", unsure: 4, said: 6 }, { word: "Kristineberg", unsure: 3, said: 3 }, { word: "rural", unsure: 2, said: 5 }] },
        { lang: "sv", words: [{ word: "sjuksköterska", unsure: 2, said: 2 }] }] },
    coach: { people: Math.round(64 * k), days: 14 },
    markers: { words: Math.round(3100 * k), dictations: Math.round(64 * k), fillers_per_100: 1.2, hedges_per_100: 2.4,
      weeks: [null, null, 3.6, 3.1, 2.9, null, 2.2, 1.8].map((h, i) => {
        const d = new Date(today); d.setDate(today.getDate() - today.getDay() + 1 - 7 * (7 - i));
        return { week: d.toISOString().slice(0, 10), words: h ? 400 : 20, hedges_per_100: h, fillers_per_100: h ? 1.1 : null };
      }),
      top_fillers: [{ word: "like", count: 22 }, { word: "basically", count: 9 }],
      top_hedges: [{ word: "maybe", count: 31 }, { word: "i think", count: 24 }, { word: "kind of", count: 12 }] },
    meetings: { meetings: 4, talk_share: 41, monologues: 2, questions: 17, hedges_per_100: 1.9, top_hedges: [{ word: "i think", count: 14 }],
      list: [{ created: "2026-10-06T10:00", title: "Weekly planning", talk_share: 38, monologues: 0, questions: 6, longest_s: 70 },
        { created: "2026-10-03T14:30", title: "Design review", talk_share: 57, monologues: 2, questions: 3, longest_s: 140 },
        { created: "2026-10-01T09:00", title: "Intro call", talk_share: 29, monologues: 0, questions: 8, longest_s: 45 }] },
    pace: { people: { dictations: Math.round(64 * k), wpm: 148, pauses: 22, in_range: 58 }, ai: { dictations: Math.round(150 * k), wpm: 163, pauses: 31, in_range: 35 },
      range: [130, 160], histogram: [0, 1, 1, 3, 5, 8, 12, 14, 9, 5, 3, 2, 1, 0, 0].map((n, i) => ({ from: 80 + 10 * i, dictations: n })) },
  };
}

function demoApi() {
  const now = new Date();
  const iso = (mins) => new Date(now - mins * 60000).toISOString().slice(0, 19);
  let settings = {
    values: { hotkey: "rctrl", mic: "Anker PowerConf", languages: "en", sounds: true, overlay: true, live_text: true, insights: params.get("insights") === "1", speech_feedback: false, unmute: true, startup: true,
      meet_mode: "prompt", meet_lang: "sv", on_demand: true, speakers: true, vocabulary: "Göteborg\npyannote", voice_commands: false, screen_names: true, hold_to_talk: false, numpad_enter: false, voice_memory: true,
      snippets: [{ trigger: "my email", text: "alex@example.com" }] },
    options: {
      hotkeys: [{ value: "rctrl", label: "Right Ctrl (recommended)" }, { value: "scrolllock", label: "Scroll Lock" }, { value: "pause", label: "Pause" }, { value: "f13", label: "F13" }],
      mics: [{ value: "", label: DEFAULT_MIC }, { value: "Headset (Zone Vibe 100)", label: "Zone Vibe 100" }, { value: "Anker PowerConf", label: "Anker PowerConf C20" }],
      languages: [{ value: "en", label: "English" }, { value: "sv", label: "Swedish" }],
      base_languages: ["en", "sv"],
      all_languages: [{ value: "el", label: "Greek" }, { value: "de", label: "German" }, { value: "es", label: "Spanish" }, { value: "fr", label: "French" }],
      meet_modes: [{ value: "prompt", label: "Ask" }, { value: "auto", label: "Start by itself" }, { value: "off", label: "Don't detect" }],
      meet_langs: [{ value: "en", label: "English" }, { value: "sv", label: "Swedish" }, { value: "en,sv", label: "English + Swedish" }, { value: "auto", label: "Detect" }],
    },
    can_startup: true,
    speakers_addon: params.get("addon") !== "0",
    voice_command_list: [{ what: "Paragraph break", en: '"new paragraph"', es: '"nuevo párrafo", "punto y aparte"', sv: '"nytt stycke"' },
      { what: "Line break", en: '"new line"', es: '"nueva línea"', sv: '"ny rad"' },
      { what: "Press Enter after the text (at the very end only)", en: '"send it", "press enter"', es: '"envíalo", "enviar"', sv: '"skicka"' }],
  };
  const history = [
    { ts: iso(2), text: "Can you check why the deploy failed last night and send me the logs before the standup? ", target: "WindowsTerminal.exe", pasted: true },
    { ts: iso(14), text: "Sounds good, let's do Thursday at six. I'll bring the new shoes. ", target: "slack.exe", pasted: true },
    { ts: iso(41), text: "Remind me to book the climbing gym for the weekend. ", target: "chrome.exe", pasted: false },
    { ts: iso(60 * 26), text: "The quick brown fox jumps over the lazy dog, then runs back to the barn. ", target: "notepad.exe", pasted: true },
  ];
  let t = 0;
  const S = (name, title, mins, status, extra = {}) => ({ name, title, created: iso(mins), status, lang: "sv", lang_name: "Swedish",
    duration_s: 1860, source: "meeting", pct: null, error: null, slow: false, ...extra });
  const rec = params.get("rec") !== "0";
  const sess = [
    ...(rec ? [S("2026-10-05_1400_retro", "Sprint retro", 12, "recording", { duration_s: null })] : []),
    S("2026-10-05_1130_podcast", "Super Easy Greek 12", 40, "running", { lang: "el", lang_name: "Greek", source: "import", pct: 42, duration_s: 412 }),
    S("2026-10-05_0915_planering", "Planering vecka 41", 60 * 5, "done"),
    S("2026-10-04_1600_kund", "Client call", 60 * 22, "done", { lang: "en", lang_name: "English", duration_s: 2710, speakers: "done", speaker_names: { "Speaker 2": "Ana" } }),
    S("2026-10-03_1000_fallo", "Meeting", 60 * 50, "failed", { error: "CUDA out of memory", duration_s: 300 }),
  ];
  const SEGS = [
    { t0: 4.2, t1: 9.8, text: "Okej, ska vi köra? Jag tänkte att vi börjar med det som inte gick bra.", speaker: "Me" },
    { t0: 10.1, t1: 16.4, text: "Ja, deployen i torsdags tog nästan två timmar och ingen visste varför.", speaker: "Others" },
    { t0: 16.9, t1: 22.0, text: "Det var cachen. Vi glömde att rensa den efter migreringen.", speaker: "Others" },
    { t0: 22.6, t1: 28.3, text: "Bra, då skriver vi in det som en åtgärd till nästa sprint.", speaker: "Me" },
  ];
  const SEGS_MULTI = [
    { t0: 3.1, t1: 8.0, text: "Thanks for joining, everyone. Shall we start with the timeline?", speaker: "Me" },
    { t0: 8.6, t1: 15.2, text: "Yes. The data team needs two more weeks for the export.", speaker: "Speaker 1" },
    { t0: 15.8, t1: 21.0, text: "Two weeks works for us if the format stays the same.", speaker: "Speaker 2" },
    { t0: 21.4, t1: 26.9, text: "I can confirm that on Friday after I talk to legal.", speaker: "Speaker 3" },
    { t0: 27.3, t1: 31.0, text: "Great, then we lock the plan today.", speaker: "Me" },
  ];
  let liveN = 2;
  const notes = { "2026-10-05_1400_retro": "- Is the export date firm?\n- Ask legal about the format" };
  const find = (n) => sess.find((s) => s.name === n);
  const mstate = () => ({ meeting: rec && find("2026-10-05_1400_retro")?.status === "recording"
    ? { name: "2026-10-05_1400_retro", app: "ms-teams", lang: "sv", started: iso(12), status: "recording" } : null, job: null, queue: [] });
  return {
    list_sessions: async (q) => ({ items: sess.filter((s) => !q || s.title.toLowerCase().includes(q.toLowerCase())), state: mstate() }),
    get_session: async (n) => ({ session: find(n), segments: find(n)?.status !== "done" ? [] : n.endsWith("kund") ? SEGS_MULTI : SEGS,
      exports: ["transcript.txt"], notes: notes[n] || "" }),
    voices_info: async () => window.__noVoices ? { count: 0, names: [], on: true } : { count: 2, names: ["Ana", "Tom"], on: true },
    crashes: async () => (params.get("crash") === "1" ? { items: [{ name: "2026-10-06_140325", when: "2026-10-06 140325", exit: MAC ? "unknown" : "0xC0000005 (access violation)" }], gave_up: false } : { items: [], gave_up: false }),
    copy_crash_report: async () => ({ ok: true }), dismiss_crash: async () => ({ ok: true }),
    copy_debug_info: async () => ({ ok: true }), open_logs_folder: async () => ({ ok: true }),
    test_calendar: async (u) => (u ? { ok: true, today: 4, now: "Sprint retro" } : { ok: false, error: "Paste the secret address in iCal format first." }),
    forget_voices: async () => { window.__noVoices = true; return { ok: true }; },
    claude_app: async () => ({ connected: !!window.__claude, frozen: true }),
    connect_claude_app: async () => { window.__claude = true; return { ok: true, files: ["C:/x/claude_desktop_config.json"] }; },
    save_notes: async (n, text) => { notes[n] = text; window.__notes = notes; return { ok: true }; },
    get_live: async (n, since) => {  // a meeting that keeps talking: the 4 lines again, later on
      liveN += 1;
      const lines = [];
      for (let i = since; i < liveN; i++) { const x = SEGS[i % SEGS.length], k = Math.floor(i / SEGS.length) * 30; lines.push({ ...x, t0: x.t0 + k, t1: x.t1 + k }); }
      return { lines, next: Math.max(since, liveN), session: find(n), notes: notes[n] || "" };
    },
    meetings_state: async () => mstate(),
    start_meeting: async () => ({ ok: true, dir: "C:/x/2026-10-05_1400_retro" }),
    set_meeting_lang: async (lang) => { const s = find("2026-10-05_1400_retro"); if (s) s.lang = lang; window.__lang = lang; return { ok: true }; },
    stop_meeting: async () => { const s = find("2026-10-05_1400_retro"); if (s) s.status = "finalizing"; return { ok: true }; },
    import_files: async (paths) => { window.__imported = paths; return { ok: true, queued: paths.length }; },
    pick_files: async () => ({ paths: [] }),
    rename_session: async (n, title) => { find(n).title = title; return { ok: true }; },
    rename_speaker: async (n, label, name) => { const s = find(n); s.speaker_names = { ...(s.speaker_names || {}) };
      if (name) s.speaker_names[label] = name; else delete s.speaker_names[label]; window.__renamed = [label, name]; return { ok: true, names: s.speaker_names }; },
    delete_session: async (n) => { sess.splice(sess.indexOf(find(n)), 1); return { ok: true }; },
    open_folder: async () => ({ ok: true }),
    copy_transcript: async () => ({ ok: true }),
    save_export: async () => ({ ok: false, cancelled: true }),
    get_status: async () => (params.get("state") === "stopped" ? { state: "stopped", alive: false, version: "1.1.0" }
      : { state: params.get("state") || "ready", alive: true, device: "cuda", model: "large-v3-turbo", mic: "Microphone (Anker PowerConf C20", languages: settings.values.languages.split(","), hotkey: "rctrl", version: "1.1.0" }),
    start_app: async () => ({ ok: true }),
    restart_app: async () => ({ ok: true }),
    get_settings: async () => JSON.parse(JSON.stringify(settings)),
    check_hotkey: async (v) => (/^(ctrl\+[cvxzyasfpwnt]|alt\+tab|[a-z0-9])$/.test(v) ? { ok: false, error: `${v} is not allowed` }
      : { ok: true, value: v, label: hotkeyLabel(v) }),
    save_settings: async (v) => { Object.assign(settings.values, v); return { ok: true, restarting: true }; },
    mic_test_start: async () => ({ device: "Microphone (Anker PowerConf C20", fell_back: false }),
    mic_test_level: async () => { t += 1; return Math.abs(Math.sin(t / 3)) * 0.08; },
    mic_test_stop: async () => ({ ok: true }),
    get_history: async (limit, q) => {
      const items = history.filter((r) => !q || r.text.toLowerCase().includes(q.toLowerCase()));
      return { items, stats: { total: 312, total_words: 4210, today_words: 152 } };
    },
    copy_text: async () => ({ ok: true }),
    get_insights: async (days) => demoInsights(days),
    add_word: async (w) => { settings.values.vocabulary += "\n" + w; window.__added = w; return { ok: true }; },
    insights_for_claude: async () => ({ ok: true, chars: 5120 }),
    coach_me: async () => ({ ok: true, chars: 3900 }),
    clear_history: async () => { history.length = 0; return { ok: true }; },
    open_log: async () => ({ ok: true }),
    get_welcome: async () => ({ done: params.get("welcome") !== "1" }),
    finish_welcome: async () => ({ ok: true }),
  };
}

let api = null;
function getApi() {
  if (params.get("demo") === "1" || !window.pywebview) return demoApi();
  return window.pywebview.api;
}

/* ---------------------------------------------------------------- helpers */
function toast(msg, ms = 2600) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), ms);
}
function prettyMic(n) {
  const m = /^[^(]*\((.+?)\)?$/.exec(n || "");
  return m ? m[1].trim() : (n || "");
}
function fmtNum(n) { return Number(n || 0).toLocaleString("en-GB"); }
function appName(exe) {
  const m = { "windowsterminal.exe": "Terminal", "slack.exe": "Slack", "chrome.exe": "Chrome", "msedge.exe": "Edge",
    "code.exe": "VS Code", "teams.exe": "Teams", "ms-teams.exe": "Teams", "notepad.exe": "Notepad", "firefox.exe": "Firefox",
    "obsidian.exe": "Obsidian", "outlook.exe": "Outlook", "python.exe": "Python", "pythonw.exe": "Python" };
  if (!exe) return "";
  return m[exe.toLowerCase()] || exe.replace(/\.exe$/i, "");
}
function when(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d)) return "";
  const today = new Date();
  const hm = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `Today, ${hm}`;
  const y = new Date(today); y.setDate(today.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `Yesterday, ${hm}`;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + `, ${hm}`;
}
async function copy(text, btn) {
  await api.copy_text(text);
  if (btn) {
    const old = btn.textContent;
    btn.textContent = "Copied";
    btn.classList.add("done");
    setTimeout(() => { btn.textContent = old; btn.classList.remove("done"); }, 1400);
  }
}

/* ---------------------------------------------------------------- navigation */
const PAGES = ["inicio", "reuniones", "historial", "insights", "ajustes"];
let current = null;
async function show(page) {
  if (page && page.startsWith("reuniones/")) { r.open = page.slice("reuniones/".length); r.next = 0; r.status = null; $("#r-segs").innerHTML = ""; page = "reuniones"; }
  if (!PAGES.includes(page)) page = "inicio";
  if (current === "ajustes" && page !== "ajustes") await stopMicTest();
  current = page;
  for (const p of PAGES) $(`#page-${p}`).hidden = p !== page;
  for (const b of $$(".nav-item")) b.classList.toggle("active", b.dataset.page === page);
  if (page === "inicio") await renderInicio();
  if (page === "reuniones") await renderReuniones();
  if (page === "historial") await renderHistory();
  if (page === "insights") await renderInsights();
  if (page === "ajustes") await renderSettings();
}

/* ---------------------------------------------------------------- insights (dictado-3je) */
let iDays = null;
const SVGNS = "http://www.w3.org/2000/svg";
const langName = (c) => {
  if (c === "mixed") return "Mixed";
  try { return new Intl.DisplayNames(["en"], { type: "language" }).of(c); } catch { return c; }
};
function svgEl(tag, attrs) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  return e;
}
function tip(e, lines) {
  const t = $("#i-tip");
  if (!lines) { t.hidden = true; return; }
  t.textContent = "";
  const b = document.createElement("strong"); b.textContent = lines[0]; t.append(b);
  if (lines[1]) t.append(document.createTextNode(" " + lines[1]));
  t.hidden = false;
  const r = e.target.getBoundingClientRect();
  const x = e.clientX || r.left + r.width / 2, y = e.clientY || r.top;
  t.style.left = `${Math.min(window.innerWidth - t.offsetWidth - 8, x + 12)}px`;
  t.style.top = `${y - t.offsetHeight - 10}px`;
}
/* Columns, one series: thin bars (<= 24 px), 4 px rounded tops square at the baseline, a hairline
   baseline, a few tick labels, and a hover / focus readout per column (dataviz). */
function columns(el, data, tickEvery) {
  el.textContent = "";
  const W = 320, H = 118, top = 6, base = 96, slot = W / data.length;
  const bw = Math.min(24, slot * 0.62), max = Math.max(1, ...data.map((d) => d.value));
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": el.dataset.label || "" });
  data.forEach((d, i) => {
    const x = i * slot + (slot - bw) / 2, h = d.value ? Math.max(2, (base - top) * d.value / max) : 0;
    const hit = svgEl("rect", { x: i * slot, y: top, width: slot, height: base - top, class: "hit", tabindex: 0 });
    const show = (e) => tip(e, [d.tipValue, d.tipLabel]);
    hit.addEventListener("pointermove", show); hit.addEventListener("focus", show);
    hit.addEventListener("pointerleave", () => tip(null)); hit.addEventListener("blur", () => tip(null));
    svg.append(hit);
    if (h > 0) {
      const r = Math.min(4, bw / 2, h);
      svg.append(svgEl("path", { class: d.dim ? "bar dim" : "bar",
        d: `M${x},${base}V${base - h + r}Q${x},${base - h} ${x + r},${base - h}H${x + bw - r}Q${x + bw},${base - h} ${x + bw},${base - h + r}V${base}Z` }));
    } else svg.append(svgEl("g"));
    if (tickEvery(i)) {
      const t = svgEl("text", { x: i * slot + slot / 2, y: base + 16, "text-anchor": "middle", class: "tick" });
      t.textContent = d.label; svg.append(t);
    }
  });
  svg.append(svgEl("line", { x1: 0, x2: W, y1: base + 0.5, y2: base + 0.5, class: "base" }));
  el.append(svg);
}
function hbars(el, items, scale) {  // scale: the full bar's value (100 for a share); default the biggest
  el.textContent = "";
  const box = document.createElement("div"); box.className = "i-hbars";
  const max = scale || Math.max(1, ...items.map((x) => x.value));
  for (const it of items) {
    const row = document.createElement("div"); row.className = "i-hbar";
    const name = document.createElement("span"); name.className = "i-hbar-name"; name.textContent = it.name; name.title = it.name;
    const track = document.createElement("span"); track.className = "i-hbar-track";
    const fill = document.createElement("span"); fill.className = "i-hbar-fill"; fill.style.display = "block";
    fill.style.width = `${Math.max(1.5, 100 * it.value / max)}%`; track.append(fill);
    const val = document.createElement("span"); val.className = "i-hbar-val"; val.textContent = it.label;
    row.append(name, track, val); box.append(row);
  }
  el.append(box);
}
function iChip(text, count, title) {
  const c = document.createElement("span"); c.className = "i-chip";
  c.append(document.createTextNode(text));
  if (count != null) { const b = document.createElement("b"); b.textContent = `×${count}`; c.append(b); }
  if (title) c.title = title;
  return c;
}
function renderMarkers(m) {  // dictado-9jc.3: fillers and hedges in messages to people
  const has = !!(m && m.words);
  $("#i-markers-empty").hidden = has; $("#i-markers-body").hidden = !has;
  if (!has) return;
  $("#i-hedges").textContent = String(m.hedges_per_100);
  $("#i-fillers").textContent = String(m.fillers_per_100);
  const day = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const n = m.weeks.length;
  columns($("#i-markers-weeks"), m.weeks.map((w, i) => {
    const v = w.hedges_per_100 == null ? 0 : w.hedges_per_100 + w.fillers_per_100;
    return { value: v, dim: i !== n - 1, label: i === n - 1 ? "This week" : day(w.week),
      tipValue: w.hedges_per_100 == null ? "Too few words to say" : `${w.hedges_per_100} hedges · ${w.fillers_per_100} fillers per 100`,
      tipLabel: `week of ${day(w.week)}` };
  }), (i) => i === 0 || i === n - 1);
  const chips = $("#i-top-hedges"); chips.textContent = "";
  for (const h of m.top_hedges) chips.append(iChip(h.word, h.count));
  if (!m.top_hedges.length) chips.append(iChip("None so far"));
}
function renderMeetings(m) {  // dictado-9jc.5
  const has = !!(m && m.meetings);
  $("#i-meet-empty").hidden = has; $("#i-meet-body").hidden = !has;
  if (!has) return;
  $("#i-meet-share").textContent = `${m.talk_share}%`;
  $("#i-meet-mono").textContent = fmtNum(m.monologues);
  $("#i-meet-q").textContent = fmtNum(m.questions);
  $("#i-meet-hedges").textContent = String(m.hedges_per_100);
  hbars($("#i-meet-list"), m.list.map((x) => {
    const extra = [x.monologues ? `${x.monologues} long ${x.monologues === 1 ? "turn" : "turns"}` : "",
      x.questions ? `${x.questions} ${x.questions === 1 ? "question" : "questions"}` : ""].filter(Boolean);
    return { name: x.title, value: x.talk_share, label: [`${x.talk_share}%`, ...extra].join(" · ") };
  }), 100);
}
function renderPace(p) {  // dictado-9jc.4
  const has = !!(p && (p.people || p.ai));
  $("#i-pace-empty").hidden = has; $("#i-pace-body").hidden = !has;
  if (!has) return;
  const rows = $("#i-pace-rows"); rows.textContent = "";
  for (const [key, who] of [["people", "to people"], ["ai", "to AI apps"]]) {
    const g = p[key]; if (!g) continue;
    const row = document.createElement("div"); row.className = "i-habit";
    const num = document.createElement("span"); num.className = "i-habit-num"; num.textContent = String(g.wpm);
    const lab = document.createElement("span"); lab.className = "muted";
    lab.textContent = `words a minute ${who}, ${g.pauses}% of the time pausing (${fmtNum(g.dictations)} ${g.dictations === 1 ? "dictation" : "dictations"})`;
    row.append(num, lab); rows.append(row);
  }
  const [lo, hi] = p.range, last = p.histogram.length - 1;
  $("#i-pace-hist").hidden = !p.histogram.length;
  columns($("#i-pace-hist"), p.histogram.map((b, i) => {
    const name = i === 0 ? `under ${b.from + 10}` : i === last ? `${b.from}+` : `${b.from}-${b.from + 9}`;
    return { value: b.dictations, dim: b.from < lo || b.from >= hi, label: i === last ? `${b.from}+` : String(b.from),
      tipValue: `${b.dictations} ${b.dictations === 1 ? "message" : "messages"}`, tipLabel: `${name} words a minute` };
  }), (i) => i === 0 || i === last || p.histogram[i].from === lo || p.histogram[i].from === hi);
}
function renderClarity(c) {  // dictado-9jc.1
  const has = !!(c && c.dictations);
  $("#i-clarity-empty").hidden = has; $("#i-clarity-body").hidden = !has;
  if (!has) return;
  const day = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  $("#i-clarity").textContent = `${c.clarity}%`;
  $("#i-clarity-how").textContent = `of your words heard clearly, over ${fmtNum(c.dictations)} ${c.dictations === 1 ? "dictation" : "dictations"} since ${day(c.since)}`;
  const n = c.weeks.length;
  columns($("#i-clarity-weeks"), c.weeks.map((w, i) => ({ value: w.clarity || 0, dim: i !== n - 1,
    label: i === n - 1 ? "This week" : day(w.week),
    tipValue: w.clarity == null ? "No dictations" : `${w.clarity}% heard clearly`, tipLabel: `week of ${day(w.week)}` })),
    (i) => i === 0 || i === n - 1);
  const box = $("#i-unsure"); box.textContent = "";
  for (const l of c.words) {
    const row = document.createElement("div"); row.className = "i-habit";
    const lab = document.createElement("span"); lab.className = "muted"; lab.textContent = langName(l.lang);
    const chips = document.createElement("span"); chips.className = "i-chips";
    for (const w of l.words) chips.append(iChip(w.word, w.unsure, `Unsure ${w.unsure} of the ${w.said} times you said it`));
    row.append(lab, chips); box.append(row);
  }
  if (!c.words.length) box.textContent = "None so far: every word came through clearly.";
}
async function renderInsights() {
  for (const b of $$("#i-range .seg")) b.setAttribute("aria-checked", String((b.dataset.days || null) === iDays));
  const d = await api.get_insights(iDays ? Number(iDays) : null);
  const t = d.totals;
  $("#i-empty").hidden = t.dictations > 0;
  $("#i-body").hidden = t.dictations === 0;
  if (!t.dictations) return;
  $("#i-saved").textContent = fmtDur(t.saved_s);
  $("#i-saved-how").textContent = t.wpm
    ? `You talk at ${t.wpm} words a minute; typing runs about ${t.typing_wpm}. ${fmtNum(t.words)} words took ${fmtDur(t.talk_s)} to say.`
    : `Typing ${fmtNum(t.words)} words at ${t.typing_wpm} a minute takes longer than saying them.`;
  $("#i-words").textContent = fmtNum(t.words);
  $("#i-dictations").textContent = fmtNum(t.dictations);
  $("#i-talk").textContent = fmtDur(t.talk_s);
  $("#i-streak").textContent = `${d.rhythm.streak} ${d.rhythm.streak === 1 ? "day" : "days"}`;
  const peak = Math.max(...d.rhythm.hours);
  columns($("#i-hours"), d.rhythm.hours.map((v, h) => ({ value: v, label: String(h).padStart(2, "0"), dim: v < peak,
    tipValue: `${v} ${v === 1 ? "dictation" : "dictations"}`, tipLabel: `${String(h).padStart(2, "0")}:00-${String((h + 1) % 24).padStart(2, "0")}:00` })),
    (i) => i % 6 === 0);
  const n = d.rhythm.days.length;
  columns($("#i-days"), d.rhythm.days.map((x, i) => {
    const dt = new Date(x.date + "T12:00:00");
    return { value: x.words, dim: i !== n - 1,
      label: i === n - 1 ? "Today" : dt.toLocaleDateString("en-GB", { day: "numeric", month: "short" }),
      tipValue: `${fmtNum(x.words)} words`, tipLabel: dt.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }) };
  }), (i) => i === 0 || i === n - 1 || i === Math.floor((n - 1) / 2));
  const lw = d.languages.reduce((a, x) => a + x.words, 0) || 1;
  hbars($("#i-langs"), d.languages.map((x) => ({ name: langName(x.lang), value: x.words,
    label: `${fmtNum(x.words)} · ${Math.round(100 * x.words / lw)}%` })));
  hbars($("#i-apps"), d.apps.map((x) => ({ name: appName(x.app), value: x.dictations, label: fmtNum(x.dictations) })));
  const hab = $("#i-habits"); hab.textContent = "";
  for (const h of d.habits) {
    const row = document.createElement("div"); row.className = "i-habit";
    const num = document.createElement("span"); num.className = "i-habit-num"; num.textContent = String(h.per_100);
    const lab = document.createElement("span"); lab.className = "muted"; lab.textContent = `filler words per 100 in ${langName(h.lang)}`;
    const chips = document.createElement("span"); chips.className = "i-chips";
    for (const f of h.top) chips.append(iChip(f.word, f.count));
    row.append(num, lab, chips); hab.append(row);
  }
  if (!d.habits.length) hab.textContent = "A few more dictations and your filler words show up here.";
  renderClarity(d.clarity);
  renderMarkers(d.markers);
  renderPace(d.pace);
  renderMeetings(d.meetings);
  const people = d.coach ? d.coach.people : 0;  // dictado-9jc.2
  $("#i-coach").disabled = !people;
  $("#i-coach").title = people ? `${people} ${people === 1 ? "message" : "messages"} to people in the last ${d.coach.days} days`
    : "Nothing dictated to people (messages, email) in the last two weeks yet";
  const ph = $("#i-phrases"); ph.textContent = "";
  for (const p of d.phrases) ph.append(iChip(p.phrase, p.count));
  if (!d.phrases.length) ph.append(iChip("Nothing repeated three times yet"));
  const sl = $("#i-suggest"); sl.textContent = "";
  $("#i-suggest-card").hidden = !d.suggestions.length;
  for (const s of d.suggestions) {
    const li = document.createElement("li");
    const heard = document.createElement("span");
    heard.textContent = s.heard === s.suggest ? `“${s.heard}”, ${s.count} times` : `Heard “${s.heard}” ${s.count} times`;
    const input = document.createElement("input"); input.value = s.suggest; input.setAttribute("aria-label", `Add ${s.suggest} to Your words`);
    const btn = document.createElement("button"); btn.type = "button"; btn.className = "btn btn-ghost btn-sm"; btn.textContent = "Add";
    btn.onclick = async () => {
      const r = await api.add_word(input.value);
      if (r.ok) { li.remove(); toast(`Added “${input.value.trim()}” to Your words.`); }
    };
    li.append(heard, input, btn); sl.append(li);
  }
  $("#i-foot").textContent = `Worked out on this computer from your dictation history${d.first ? ` since ${new Date(d.first + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long" })}` : ""}; nothing is sent anywhere.`;
}

/* ---------------------------------------------------------------- status */
const STATE_TEXT = {
  ready: ["Running", "Ready to dictate"],
  loading: ["Loading", "Loading the model…"],
  restarting: ["Restarting", "Applying your settings…"],
  error: ["Error", "Something failed at startup"],
  stopped: ["Stopped", "Ecoscribe isn't running"],
};
let lastStatus = null;
async function refreshStatus() {
  let s;
  try { s = await api.get_status(); } catch (e) { return; }
  lastStatus = s;
  const state = STATE_TEXT[s.state] ? s.state : "loading";
  const [short, long] = STATE_TEXT[state];
  const side = $("#side-status");
  side.dataset.state = state;
  $(".side-status-text", side).textContent = state === "ready" ? `Ready · ${hotkeyLabel(s.hotkey)}` : short;
  $("#ver").textContent = `v${s.version || ""}`;
  if (current === "inicio") paintHero(s, state, short, long);
}
function paintHero(s, state, short, long) {
  $("#hero-badge").dataset.state = state;
  $("#hero-badge-text").textContent = short;
  $("#hero-title").textContent = long;
  const actions = $("#hero-actions");
  actions.innerHTML = "";
  if (state === "stopped") {
    const b = document.createElement("button");
    b.className = "btn btn-primary"; b.textContent = "Start Ecoscribe";
    b.onclick = async () => { b.disabled = true; await api.start_app(); toast("Starting Ecoscribe…"); };
    actions.append(b);
  } else if (state === "error") {
    const b = document.createElement("button");
    b.className = "btn btn-ghost"; b.textContent = "Open the log";
    b.onclick = () => api.open_log();
    actions.append(b);
  }
  if (s.hotkey && s.hotkey.includes("+")) {  // a combo: no tap, and no Esc cancel (tray > Cancel recording)
    $("#hero-how").textContent = `Press ${hotkeyLabel(s.hotkey)}, talk, and press it again. The text appears wherever the cursor is.`;
    $("#tip-cancel").hidden = true;
  }
  const none = state === "stopped" ? "—" : "…";
  $("#fact-mic").textContent = s.mic ? (s.fell_back ? DEFAULT_MIC : prettyMic(s.mic)) : none;
  $("#fact-mic").title = s.mic || "";
  const langs = s.languages || [];
  $("#fact-lang").textContent = !langs.length ? none
    : langs.length === 1 ? (DICT_LANGS[langs[0]] || langs[0]) : langs.map((l) => l.toUpperCase()).join(" · ") + " (auto)";
  $("#fact-lang").title = langs.map((l) => DICT_LANGS[l] || l).join(", ");
  $("#fact-engine").textContent = s.device ? (s.device === "cuda" ? "GPU · fast" : "CPU · slow") : none;
}

// dictation languages (dictado-bvf): any mix, auto-detected among them; set in Settings
const DICT_LANGS = { en: "English", es: "Spanish", sv: "Swedish", el: "Greek" };

/* ---------------------------------------------------------------- inicio */
async function crashCard() {  // t0u.37: a crash is never silent
  const c = await api.crashes().catch(() => ({ items: [] }));
  const card = $("#crash-card"), x = c.items[0];
  card.hidden = !x && !c.gave_up;
  if (card.hidden) return;
  const more = c.items.length > 1 ? ` (${c.items.length} crashes)` : "";
  $("#crash-title").textContent = c.gave_up ? "Ecoscribe crashed 3 times and stopped" : `Ecoscribe crashed${x ? " " + x.when.slice(11, 13) + ":" + x.when.slice(13, 15) : ""} and restarted${more}`;
  $("#crash-sub").textContent = c.gave_up ? (MAC ? "Open it again from Applications." : "Start it again from the Start menu.") + " The reports say where it failed."
    : `${x.exit && x.exit !== "unknown" ? x.exit + ". " : ""}A report with everything needed to find the cause was saved.`;  // macOS: no exit code
  $("#crash-copy").hidden = !x;
  $("#crash-copy").onclick = async () => { await api.copy_crash_report(x.name); toast("Copied. Paste it to Claude."); crashCard(); };
  $("#crash-dismiss").onclick = async () => { for (const i of c.items) await api.dismiss_crash(i.name); crashCard(); };
}

async function renderInicio() {
  crashCard();
  await refreshStatus();
  const h = await api.get_history(1, "");
  $("#stat-today").textContent = fmtNum(h.stats.today_words);
  $("#stat-total").textContent = `${fmtNum(h.stats.total_words)} words in total`;
  const last = h.items[0];
  const copyBtn = $("#last-copy");
  if (last) {
    $("#last-text").textContent = last.text.trim();
    $("#last-meta").textContent = [when(last.ts), last.pasted === false ? "not pasted: copy it from here" : appName(last.target)]
      .filter(Boolean).join(" · ");  // dictado-bhe: no text box under the cursor at the stop
    copyBtn.hidden = false;
    copyBtn.onclick = () => copy(last.text, copyBtn);
  } else {
    $("#last-text").innerHTML = '<span class="muted">You haven\'t dictated anything yet.</span>';
    $("#last-meta").textContent = "";
    copyBtn.hidden = true;
  }
}

/* ---------------------------------------------------------------- reuniones */
const SPEAKER = { Yo: "Me", Otros: "Others" };
// Meeting / file languages: English + Swedish built in, plus added ones (dictado-ehs); boot() loads the real list.
let R_LANGS = [["en", "English"], ["sv", "Swedish"], ["en,sv", "English + Swedish"], ["auto", "Detect"]];
const R_STATUS = {
  recording: "Recording", finalizing: "Saving", stopping: "Saving", queued: "Queued", new: "Queued",
  running: "Transcribing", downloading: "Downloading model", done: "Ready", failed: "Failed",
};
const r = { open: null, next: 0, timer: null, status: null, segs: 0, busy: false, speakers: null, names: {} };
const ACTIVE = new Set(["recording", "finalizing", "stopping", "queued", "new", "running", "downloading"]);
function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
function rLang() { return $("#r-lang").value || "sv"; }
function fmtDur(s) {
  if (!s && s !== 0) return "";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h} h ${m} min` : m ? `${m} min` : `${x} s`;
}
function fmtT(s) {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`;
}
function statusText(row) {
  const t = R_STATUS[row.status] || row.status || "";
  if (row.status === "running" && row.pct != null) return `${t} ${row.pct} %`;
  return t;
}
function chip(el, row) {
  el.textContent = statusText(row);
  el.dataset.status = row.status || "";
}
async function renderReuniones() {
  if (r.open) return renderDetail(r.open);
  $("#r-list-view").hidden = false; $("#r-detail-view").hidden = true;
  let out;
  try { out = await api.list_sessions($("#r-search").value); } catch (e) { return; }
  paintNow(out.state);
  const list = $("#r-list");
  list.innerHTML = "";
  for (const row of out.items) {
    const li = document.createElement("li");
    li.className = "h-item r-row"; li.tabIndex = 0; li.dataset.name = row.name;
    const title = document.createElement("p");
    title.className = "h-text r-row-title"; title.textContent = row.title || "Untitled";
    const st = document.createElement("span");
    st.className = "r-chip"; chip(st, row);
    const meta = document.createElement("div");
    meta.className = "h-meta";
    meta.textContent = [when(row.created), row.lang_name, fmtDur(row.duration_s), row.source === "import" ? "file" : "meeting"]
      .filter(Boolean).join(" · ");
    li.append(title, st, meta);
    li.onclick = () => openSession(row.name);
    li.onkeydown = (e) => { if (e.key === "Enter") openSession(row.name); };
    list.append(li);
  }
  const q = $("#r-search").value;
  $("#r-empty").hidden = out.items.length > 0;
  $("#r-empty-text").textContent = q ? `Nothing matches "${q}".` : "Your meetings and the audio you import will show up here.";
}
function paintNow(state) {
  const m = state && state.meeting;
  $("#r-now").hidden = !m;
  $("#r-start").disabled = !!m;
  if (!m) return;
  const stopping = m.status === "stopping" || m.status === "finalizing";
  $("#r-now-title").textContent = stopping ? "Saving the meeting" : "Recording";
  const lang = (R_LANGS.find(([c]) => c === m.lang) || [null, m.lang])[1];
  $("#r-now-meta").textContent = [m.app ? appName(m.app + ".exe") : "", lang, m.started ? `since ${when(m.started)}` : ""].filter(Boolean).join(" · ");
  $("#r-now-stop").hidden = stopping;
  $("#r-now-open").onclick = () => openSession(m.name);
}
function atBottom(el) { return el.scrollHeight - el.scrollTop - el.clientHeight < 40; }
function renameSpeaker(el) {
  if (el.querySelector("input")) return;
  const label = el.dataset.label, input = document.createElement("input");
  input.className = "r-who-input"; input.value = whoName(label); input.maxLength = 40;
  input.setAttribute("aria-label", "Speaker name");
  el.textContent = ""; el.append(input); input.focus(); input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return; done = true;
    const v = input.value.trim();
    if (save && v !== whoName(label)) {
      const out = await api.rename_speaker(r.open, label, v);
      if (out.ok) r.names = out.names; else toast(out.error || "Couldn't rename.");
    }
    for (const w of document.querySelectorAll(".r-who-edit")) if (w.dataset.label === label) w.textContent = whoName(label);
  };
  input.onkeydown = (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); e.stopPropagation(); };
  input.onblur = () => finish(true);
  input.onclick = (e) => e.stopPropagation();
}
async function openSession(name) {
  r.open = name; r.next = 0; r.status = null; r.segs = 0; r.speakers = null; r.names = {};
  r.notesLoaded = false; clearTimeout(r.notesTimer);
  $("#r-notes-text").value = "";
  $("#r-segs").innerHTML = "";
  $("#r-jump").hidden = true;
  await renderDetail(name);
}
function whoName(label) { return r.names[label] || SPEAKER[label] || label || ""; }  // transcripts before 1.2.1 say Yo / Otros
function segLi(s, editable) {
  const li = document.createElement("li");
  li.className = "r-seg";
  const t = document.createElement("span");
  t.className = "r-t"; t.textContent = fmtT(s.t0);
  const who = document.createElement("span");
  const sp = SPEAKER[s.speaker] || s.speaker || "";
  who.className = "r-who"; who.textContent = whoName(s.speaker);
  who.dataset.who = sp.startsWith("Speaker") ? "Others" : sp;
  if (editable && s.speaker) {
    who.dataset.label = s.speaker; who.tabIndex = 0; who.classList.add("r-who-edit");
    who.title = "Click to name this speaker";
    who.onclick = () => renameSpeaker(who);
    who.onkeydown = (e) => { if (e.key === "Enter") renameSpeaker(who); };
  }
  const p = document.createElement("p");
  p.className = "r-text"; p.textContent = s.text;
  li.append(t, who, p);
  return li;
}
async function renderDetail(name) {
  $("#r-list-view").hidden = true; $("#r-detail-view").hidden = false;
  const live = r.status === null || r.status === "recording" || r.status === "stopping" || r.status === "finalizing";
  let s, segs = null;
  try {
    if (live) {
      const out = await api.get_live(name, r.next);
      s = out.session;
      notesIn(out.notes);
      if (s.status === "recording" || s.status === "finalizing" || s.status === "stopping") {
        const list = $("#r-segs"), follow = atBottom(list);  // scrolled up to read: stay there
        for (const l of out.lines) list.append(segLi(l, false));
        r.next = out.next;
        r.segs += out.lines.length;
        if (out.lines.length) { if (follow) list.scrollTop = list.scrollHeight; else $("#r-jump").hidden = false; }
      }
    }
    if (!s || !(s.status === "recording" || s.status === "finalizing" || s.status === "stopping")) {
      const out = await api.get_session(name);
      s = out.session; segs = out.segments;
      notesIn(out.notes);
    }
  } catch (e) {
    if (!/FileNotFound|not found/i.test(String(e && (e.message || e)))) { console.error(e); return; }  // a hiccup: next poll retries
    toast("That session no longer exists."); r.open = null; return renderReuniones();
  }
  const changed = s.status !== r.status || (s.speakers || null) !== r.speakers;  // a finished speakers pass relabels the lines
  r.status = s.status; r.speakers = s.speakers || null; r.names = s.speaker_names || {};
  if (document.activeElement !== $("#r-d-title")) $("#r-d-title").value = s.title || "";
  chip($("#r-d-status"), s);
  $("#r-d-meta").textContent = [when(s.created), s.lang_name, fmtDur(s.duration_s),
    s.source === "import" ? "imported file" : "mic and the computer's audio",
    s.recovered ? `recovered (${s.recovered}): the text ends where the recording stopped` : "",
    s.speakers === "pending" || s.speakers === "running" ? "identifying speakers…" : "",
    s.speakers === "failed" ? "couldn't tell the speakers apart" : "",
    s.recognised?.length ? `recognised by voice: ${s.recognised.join(", ")}` : ""].filter(Boolean).join(" · ");
  const recording = s.status === "recording";
  if (recording && document.activeElement !== $("#r-d-lang")) $("#r-d-lang").value = s.lang || "sv";
  $("#r-d-live-actions").hidden = !recording;
  if (!recording) $("#r-jump").hidden = true;
  $("#r-d-done-actions").hidden = s.status !== "done";
  const working = s.status === "running" || s.status === "queued" || s.status === "new" || s.status === "downloading";
  $("#r-d-progress").hidden = !working;
  if (working) {
    $("#r-d-progress-fill").style.width = `${s.pct || 0}%`;
    $("#r-d-progress-text").textContent = s.status === "queued" || s.status === "new" ? "Queued: starts when the previous one finishes."
      : s.status === "downloading" ? "Downloading this language's model (first time only)." : `${s.pct || 0} %${s.slow ? " · on CPU, slow" : ""}`;
  }
  if (segs && (changed || $("#r-segs").childElementCount !== segs.length)) {
    const list = $("#r-segs");
    list.innerHTML = "";
    for (const x of segs) list.append(segLi(x, s.status === "done"));
  }
  const n = $("#r-segs").childElementCount;
  $("#r-segs-empty").hidden = n > 0;
  $("#r-segs-empty-text").textContent = s.status === "failed" ? `Failed: ${s.error || "unknown error"}`
    : recording ? "Listening: the first text arrives in a few seconds." : working ? "The text appears when it finishes." : "This session has no text.";
}
function notesIn(text) {  // once per open: polls must never overwrite what the user is typing
  if (r.notesLoaded) return;
  r.notesLoaded = true;
  $("#r-notes-text").value = text || "";
}
function notesWire() {
  const box = $("#r-notes-text"), state = $("#r-notes-state");
  box.addEventListener("input", () => {
    clearTimeout(r.notesTimer);
    const name = r.open;
    state.textContent = "Saving…";
    r.notesTimer = setTimeout(async () => {
      const out = await api.save_notes(name, box.value).catch(() => ({ ok: false }));
      state.textContent = out.ok ? "Saved." : "Couldn't save the notes.";
    }, 600);
  });
}
function rPoll() {
  clearInterval(r.timer);
  r.timer = setInterval(async () => {
    if (current !== "reuniones" || r.busy) return;  // a slow call must not run twice and append lines twice
    r.busy = true;
    try {
      if (r.open) { if (ACTIVE.has(r.status) || r.status === null || r.speakers === "pending" || r.speakers === "running") await renderDetail(r.open); }
      else if (document.activeElement !== $("#r-search")) await renderReuniones();
    } finally { r.busy = false; }
  }, 1000);
}
async function rStart() {
  $("#r-start").disabled = true;
  const out = await api.start_meeting(rLang());
  if (!out.ok) { $("#r-start").disabled = false; toast(out.error || "Couldn't start."); return; }
  toast("Taking notes.");
  if (out.dir) openSession(out.dir.split(/[\\/]/).pop());
  else renderReuniones();
}
async function rStop() {
  const out = await api.stop_meeting();
  if (!out.ok) { toast(out.error || "Couldn't stop."); return; }
  toast("Stopping: saving the transcript.");
  if (r.open) renderDetail(r.open); else renderReuniones();
}
async function rImport(paths) {
  if (!paths || !paths.length) return;
  const out = await api.import_files(paths, rLang());
  if (!out.ok) { toast(out.error || "Couldn't import."); return; }
  toast(paths.length === 1 ? "Queued for transcription." : `${paths.length} files queued.`);
  r.open = null;
  setTimeout(renderReuniones, 600);
}
async function rDropped(paths) {  // from Python's drop handler: full paths of the dropped files
  $("#r-drop").hidden = true;
  if (current !== "reuniones") await show("reuniones");
  const ok = (paths || []).filter(Boolean);
  if (!ok.length) { toast(MAC ? "Drag the file from Finder." : "Drag the file from Windows Explorer."); return; }
  await rImport(ok);
}
function rWire() {
  const sel = $("#r-lang");
  for (const [c, n] of R_LANGS) { const o = document.createElement("option"); o.value = c; o.textContent = n; sel.append(o); }
  sel.value = store("ecoscribe.r-lang") || "sv";
  if (!sel.value) sel.value = R_LANGS[0][0];  // a stored language that was removed
  sel.onchange = () => store("ecoscribe.r-lang", sel.value);
  $("#r-start").onclick = rStart;
  $("#r-now-stop").onclick = rStop;
  $("#r-d-stop").onclick = rStop;
  $("#r-segs").addEventListener("scroll", () => { if (atBottom($("#r-segs"))) $("#r-jump").hidden = true; });
  $("#r-jump").onclick = () => { const l = $("#r-segs"); l.scrollTop = l.scrollHeight; $("#r-jump").hidden = true; };
  const dl = $("#r-d-lang");
  for (const [c, n] of R_LANGS) { const o = document.createElement("option"); o.value = c; o.textContent = n; dl.append(o); }
  dl.onchange = async () => {
    const out = await api.set_meeting_lang(dl.value);
    toast(out.ok ? `Now transcribing in ${dl.selectedOptions[0].textContent}. The final transcript uses it for the whole meeting.` : out.error || "Couldn't change the language.");
  };
  $("#r-import").onclick = async () => { const out = await api.pick_files(); rImport(out.paths); };
  $("#r-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(renderReuniones, 120); });
  $("#r-back").onclick = () => { r.open = null; renderReuniones(); };
  $("#r-d-title").addEventListener("change", async () => {
    const out = await api.rename_session(r.open, $("#r-d-title").value);
    if (!out.ok) toast(out.error); else toast("Title saved.");
  });
  $("#r-copy").onclick = async () => { await api.copy_transcript(r.open, "text"); toast("Copied."); };
  $("#r-copy-claude").onclick = async () => { await api.copy_transcript(r.open, "claude"); toast("Copied with date, app and language, ready to paste into Claude."); };
  $("#r-copy-summary").onclick = async () => { await api.copy_transcript(r.open, "summary"); toast("Summary prompt copied: paste it into Claude."); };
  for (const b of $$("[data-fmt]")) b.onclick = async () => {
    const out = await api.save_export(r.open, b.dataset.fmt);
    if (out.ok) toast(`In Downloads: ${out.name}`); else toast(out.error || "Couldn't export.");
  };
  $("#r-folder").onclick = () => api.open_folder(r.open);
  $("#r-delete").onclick = async () => {
    if (!confirm("Delete this transcript and its audio? This can't be undone.")) return;
    const out = await api.delete_session(r.open);
    if (!out.ok) { toast(out.error); return; }
    r.open = null; toast("Deleted."); renderReuniones();
  };
  // drag and drop: the page shows where to drop; Python reads the full paths (pywebview DOM drop event)
  let depth = 0;
  const dragging = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files");
  document.addEventListener("dragenter", (e) => { if (!dragging(e)) return; depth++; $("#r-drop").hidden = false; });
  document.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) $("#r-drop").hidden = true; });
  document.addEventListener("dragover", (e) => { if (dragging(e)) e.preventDefault(); });
  document.addEventListener("drop", (e) => {
    e.preventDefault(); depth = 0; $("#r-drop").hidden = true;
    if (!window.pywebview) rDropped([...(e.dataTransfer?.files || [])].map((f) => f.path || f.name));  // demo / tests
  });
  rPoll();
}

/* ---------------------------------------------------------------- historial */
let searchTimer = null;
async function renderHistory() {
  const q = $("#search").value;
  const h = await api.get_history(200, q);
  let meets = [];
  try { meets = (await api.list_sessions(q)).items; } catch (e) { meets = []; }
  const list = $("#history");
  list.innerHTML = "";
  const rows = [...h.items.map((x) => ({ kind: "dict", ts: x.ts, x })), ...meets.map((x) => ({ kind: "meet", ts: x.created, x }))]
    .sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
  for (const row of rows) {
    if (row.kind === "meet") { list.append(meetingHistoryItem(row.x)); continue; }
    const r = row.x;
    const li = document.createElement("li");
    li.className = "h-item";
    const p = document.createElement("p");
    p.className = "h-text"; p.textContent = r.text.trim();
    const meta = document.createElement("div");
    meta.className = "h-meta";
    meta.textContent = [when(r.ts), appName(r.target)].filter(Boolean).join(" · ");
    if (r.pasted === false) {
      const b = document.createElement("span");
      b.className = "badge"; b.textContent = "didn't paste";
      meta.append(b);
    }
    const btn = document.createElement("button");
    btn.className = "btn btn-ghost btn-sm h-copy"; btn.textContent = "Copy";
    btn.onclick = () => copy(r.text, btn);
    li.append(p, btn, meta);
    list.append(li);
  }
  const empty = rows.length === 0;
  $("#history-empty").hidden = !empty;
  $("#history-empty-text").textContent = q ? `Nothing matches "${q}".` : "Everything you dictate will show up here.";
  $("#history-count").textContent = h.stats.total ? `${fmtNum(h.stats.total)} dictations · ${fmtNum(h.stats.total_words)} words` : "";
  $("#history-clear").hidden = !h.stats.total;
}

function meetingHistoryItem(m) {  // a meeting transcript in History: opens in Meetings, .md to Downloads
  const li = document.createElement("li");
  li.className = "h-item h-meeting";
  const p = document.createElement("p");
  p.className = "h-text"; p.textContent = m.title || "Untitled";
  const st = document.createElement("span"); st.className = "r-chip"; chip(st, m);
  const meta = document.createElement("div");
  meta.className = "h-meta";
  meta.textContent = [when(m.created), m.source === "import" ? "Imported file" : "Meeting", m.lang_name, fmtDur(m.duration_s)].filter(Boolean).join(" · ");
  meta.prepend(st);
  const btns = document.createElement("div");
  btns.className = "h-btns";
  const open = document.createElement("button");
  open.className = "btn btn-ghost btn-sm"; open.textContent = "Open";
  open.onclick = () => show("reuniones/" + m.name);
  btns.append(open);
  if (m.status === "done") {
    const dl = document.createElement("button");
    dl.className = "btn btn-ghost btn-sm"; dl.textContent = "Download .md";
    dl.onclick = async () => { const out = await api.save_export(m.name, "md"); toast(out.ok ? `In Downloads: ${out.name}` : out.error || "Couldn't export."); };
    btns.append(dl);
  }
  li.append(p, btns, meta);
  return li;
}

/* ---------------------------------------------------------------- ajustes */
let saved = null;   // values as last loaded/saved
function formValues() {
  return {
    hotkey: $("#f-hotkey").value, mic: $("#f-mic").value,
    languages: $$("#f-languages input:checked").map((i) => i.value).join(",") || "en",
    extra_languages: [...extraLangs],
    sounds: $("#f-sounds").checked, overlay: $("#f-overlay").checked, live_text: $("#f-live-text").checked, insights: $("#f-insights").checked, speech_feedback: $("#f-speech-feedback").checked, unmute: $("#f-unmute").checked, startup: $("#f-startup").checked,
    meet_mode: $("#f-meet-mode").value, meet_lang: $("#f-meet-lang").value, on_demand: $("#f-on-demand").checked,
    speakers: $("#f-speakers").checked, voice_commands: $("#f-voice-commands").checked,
    screen_names: $("#f-screen-names").checked, hold_to_talk: $("#f-hold").checked, numpad_enter: $("#f-numpad-enter").checked,
    voice_memory: $("#f-voice-memory").checked, debug_log: $("#f-debug-log").checked, calendar_url: $("#f-calendar").value.trim(),
    vocabulary: $("#f-vocabulary").value.split("\n").map((w) => w.trim()).filter(Boolean).join("\n"),
    snippets: $$(".snip").map((r) => ({ trigger: $(".snip-trigger", r).value.trim().toLowerCase().replace(/\s+/g, " "),
                                       text: $(".snip-text", r).value }))
      .filter((x) => x.trigger && x.text.trim()),
  };
}
// Languages you dictate in (dictado-ehs): English + Swedish built in; "Add a language" for the rest.
let extraLangs = [], langNames = {}, baseLangs = ["en", "sv"];
function langCard(on) {
  const box = $("#f-languages");
  box.innerHTML = "";
  for (const code of [...baseLangs, ...extraLangs]) {
    const l = document.createElement("label"); l.className = "lang-check";
    const i = document.createElement("input"); i.type = "checkbox"; i.value = code; i.checked = on.has(code);
    i.onchange = () => { if (!$$("#f-languages input:checked").length) i.checked = true; dirty(); };  // at least one
    l.append(i, document.createTextNode(langNames[code] || code));
    if (!baseLangs.includes(code)) {
      const x = document.createElement("button"); x.type = "button"; x.className = "lang-x"; x.textContent = "×";
      x.title = `Remove ${langNames[code] || code}`; x.setAttribute("aria-label", x.title);
      x.onclick = (e) => { e.preventDefault(); extraLangs = extraLangs.filter((c) => c !== code); on.delete(code);
        if (![...on].length) on.add("en"); langCard(currentChecks(on)); dirty(); };
      l.append(x);
    }
    box.append(l);
  }
  const add = $("#lang-add");
  add.innerHTML = '<option value="">Add a language…</option>';
  for (const [code, label] of Object.entries(langNames).sort((a, b) => a[1].localeCompare(b[1]))) {
    if (baseLangs.includes(code) || extraLangs.includes(code)) continue;
    const o = document.createElement("option"); o.value = code; o.textContent = label; add.append(o);
  }
  add.onchange = () => {
    if (!add.value) return;
    extraLangs.push(add.value);
    const checks = currentChecks(on); checks.add(add.value);  // a new language is ticked right away
    langCard(checks); dirty();
  };
}
function currentChecks(fallback) {
  const boxes = $$("#f-languages input");
  return boxes.length ? new Set(boxes.filter((i) => i.checked).map((i) => i.value)) : fallback;
}
function snipRow(trigger = "", text = "") {
  const row = document.createElement("div");
  row.className = "snip";
  row.innerHTML = `<input class="snip-trigger" placeholder="Name you say: my email" maxlength="60" spellcheck="false">
    <textarea class="snip-text vocab" rows="2" placeholder="Text it types"></textarea>
    <button type="button" class="btn btn-ghost btn-sm snip-del" title="Remove this snippet">Remove</button>`;
  $(".snip-trigger", row).value = trigger; $(".snip-text", row).value = text;
  $(".snip-del", row).onclick = () => { row.remove(); dirty(); };
  $("#snips").append(row);
  return row;
}
function fillSelect(sel, options, value) {
  sel.innerHTML = "";
  for (const o of options) {
    const opt = document.createElement("option");
    opt.value = o.value; opt.textContent = o.label;
    sel.append(opt);
  }
  sel.value = value;
}
async function renderSettings() {
  const s = await api.get_settings();
  $("#f-hotkey").value = s.values.hotkey;
  $("#hk-label").textContent = s.values.hotkey_label || hotkeyLabel(s.values.hotkey);
  fillSelect($("#f-mic"), s.options.mics, s.values.mic);
  fillSelect($("#f-meet-mode"), s.options.meet_modes, s.values.meet_mode);
  fillSelect($("#f-meet-lang"), s.options.meet_langs, s.values.meet_lang);
  $("#f-on-demand").checked = s.values.on_demand;
  $("#f-vocabulary").value = s.values.vocabulary || "";
  $("#f-voice-commands").checked = !!s.values.voice_commands;
  $("#f-screen-names").checked = s.values.screen_names !== false;
  $("#f-hold").checked = !!s.values.hold_to_talk; $("#f-numpad-enter").checked = !!s.values.numpad_enter;
  holdFits();
  claudeRow();
  $("#f-voice-memory").checked = s.values.voice_memory !== false;
  voicesRow();
  $("#f-calendar").value = s.values.calendar_url || "";
  $("#f-debug-log").checked = !!s.values.debug_log;
  const vc = $("#vc-rows"); vc.innerHTML = "";
  if (params.get("vc") === "1") $("#vc-list").open = true;  // screenshot
  for (const r of s.voice_command_list || []) {
    const tr = document.createElement("tr");
    for (const k of ["what", "en", "es", "sv"]) { const td = document.createElement("td"); td.textContent = r[k] || ""; tr.append(td); }
    vc.append(tr);
  }
  $("#dbg-copy").onclick = async () => { await api.copy_debug_info(); toast("Copied. Paste it to Claude."); };
  $("#dbg-open").onclick = () => api.open_logs_folder();
  $("#cal-result").textContent = "";
  $("#cal-test").onclick = calendarTest;
  $("#snips").innerHTML = "";
  for (const x of s.values.snippets || []) snipRow(x.trigger, x.text);
  $("#snip-add").onclick = () => { $(".snip-trigger", snipRow()).focus(); };
  $("#f-speakers").checked = s.values.speakers && s.speakers_addon;
  $("#f-speakers").disabled = !s.speakers_addon;
  $("#f-speakers-help").textContent = s.speakers_addon
    ? "After a call, the other side is split into Speaker 1, 2, 3… Click a name in a transcript to rename that person."
    : MAC ? "Needs the speaker add-on (Ecoscribe Speakers, drag it to Applications), which isn't installed." : "Needs the speaker add-on (Ecoscribe-Speakers-Setup), which isn't installed.";
  extraLangs = [...(s.values.extra_languages || [])];
  langNames = Object.fromEntries([...s.options.languages, ...(s.options.all_languages || [])].map((o) => [o.value, o.label]));
  baseLangs = s.options.base_languages || ["en", "sv"];
  langCard(new Set(String(s.values.languages || "en").split(",")));
  $("#lang-key").textContent = hotkeyLabel(s.values.hotkey || "rctrl");
  $("#f-sounds").checked = s.values.sounds; $("#f-overlay").checked = s.values.overlay; $("#f-live-text").checked = s.values.live_text !== false; $("#f-insights").checked = !!s.values.insights; $("#f-speech-feedback").checked = !!s.values.speech_feedback;
  $("#nav-insights").hidden = !s.values.insights;
  $("#f-unmute").checked = s.values.unmute; $("#f-startup").checked = s.values.startup;
  $("#f-startup").disabled = !s.can_startup;
  $("#startup-hint").textContent = s.can_startup ? "Ecoscribe starts by itself when you sign in." : "Available in the installed version.";
  saved = formValues();
  dirty();
}
function dirty() {
  if (!saved) return;
  const changed = JSON.stringify(formValues()) !== JSON.stringify(saved);
  $("#savebar").hidden = !changed;
  $("#savebar-text").textContent = "You have unsaved changes.";
}
async function save() {
  const btn = $("#save");
  btn.disabled = true;
  const v = formValues();
  const changed = Object.fromEntries(Object.entries(v).filter(([k, x]) => JSON.stringify(saved[k]) !== JSON.stringify(x)));
  let r;
  try { r = await api.save_settings(changed); } catch (e) { r = { ok: false, error: String(e) }; }
  finally { btn.disabled = false; }
  if (!r.ok) { toast(`Couldn't save: ${r.error}`); return; }
  saved = v;
  $("#savebar").hidden = true;
  if ("insights" in changed) $("#nav-insights").hidden = !v.insights;
  const needsRestart = Object.keys(changed).some((k) => k !== "startup" && k !== "insights");
  toast(!needsRestart ? "Saved." : r.restarting ? "Saved. Ecoscribe restarts, a few seconds."
    : "Saved. It applies the next time Ecoscribe starts.");
  refreshStatus();
}
/* One mic-test controller for Ajustes and the welcome. `on` flips synchronously so a
   double click or a fast page change can't start two tests; a start that resolves after
   a newer start/stop is stale and gets undone. */
const mic = { on: false, token: 0, timer: null };
async function micStart(device, onLevel) {
  const my = ++mic.token;
  mic.on = true;
  clearInterval(mic.timer); mic.timer = null;
  let r;
  try { r = await api.mic_test_start(device); } catch (e) { r = { error: String(e) }; }
  if (my !== mic.token) {                       // superseded while starting
    if (!mic.on) await api.mic_test_stop();     // ...by a stop: make sure nothing stays open
    return null;
  }
  if (r.error) { mic.on = false; toast("Couldn't open the mic."); return r; }
  mic.timer = setInterval(async () => {
    const lvl = await api.mic_test_level();
    if (my === mic.token && mic.on) onLevel(lvl);
  }, 80);
  return r;
}
async function micStop() {
  if (!mic.on) return;
  mic.token++; mic.on = false;
  clearInterval(mic.timer); mic.timer = null;
  await api.mic_test_stop();
}
const meterWidth = (lvl) => `${Math.min(100, Math.sqrt(lvl) * 260)}%`;

async function startMicTest() {
  $("#mic-test").textContent = "Stop";
  $("#meter").classList.add("live");
  const r = await micStart($("#f-mic").value, (lvl) => { $("#meter-fill").style.width = meterWidth(lvl); });
  if (!mic.on) resetMeter();
  return r;
}
function resetMeter() {
  $("#mic-test").textContent = "Test";
  $("#meter").classList.remove("live");
  $("#meter-fill").style.width = "0";
}
async function stopMicTest() {
  await micStop();
  resetMeter();
}

/* Shortcut recorder: Change, then tap a lone key or press a combo; Python validates it. */
const HK_CODE = MAC ? { MetaRight: "rcmd", ControlRight: "rctrl", Fn: "fn" } : { ControlRight: "rctrl", ScrollLock: "scrolllock", Pause: "pause" };
const HK_HINT = MAC ? "Tap a lone key (Right Command, Fn, F13-F19) or press a combo like Shift+Cmd+D."
  : "Tap a lone key (Right Ctrl, F13-F24, Pause) or press a combo like Ctrl+L.";
const HK_MODS = new Set(["ControlLeft", "ControlRight", "ShiftLeft", "ShiftRight", "AltLeft", "AltRight", "MetaLeft", "MetaRight"]);
const hk = { on: false, other: false };
function hkName(e) {
  const c = e.code;
  if (/^Key[A-Z]$/.test(c)) return c.slice(3).toLowerCase();
  if (/^Digit\d$/.test(c)) return c.slice(5);
  if (/^F\d{1,2}$/.test(c)) return c.toLowerCase();
  return HK_CODE[c] || c.toLowerCase();
}
function hkStop(msg) {
  hk.on = false;
  $("#hk-change").textContent = "Change";
  $("#hk-label").classList.remove("listening");
  $("#hk-hint").textContent = msg || HK_HINT;
}
async function hkTry(value) {
  const r = await api.check_hotkey(value);
  if (!r.ok) { hkStop(r.error); $("#hk-hint").classList.add("hk-bad"); return; }
  $("#hk-hint").classList.remove("hk-bad");
  $("#f-hotkey").value = r.value;
  $("#hk-label").textContent = r.label;
  hkStop(r.value.includes("+") ? `${r.label}: press it to start and again to stop. Save to apply.` : `${r.label}: tap it on its own. Save to apply.`);
  holdFits();
  dirty();
}
async function voicesRow() {
  const v = await api.voices_info().catch(() => ({ count: 0, names: [] }));
  $("#voices-row").hidden = !v.count;
  $("#voices-known").textContent = v.count ? `Knows ${v.count} voice${v.count > 1 ? "s" : ""}: ${v.names.join(", ")}` : "";
  $("#voices-forget").onclick = async () => {
    if (!confirm("Forget every voice Ecoscribe has learned? Names already in transcripts stay.")) return;
    await api.forget_voices(); toast("Voices forgotten."); voicesRow();
  };
}
async function calendarTest() {  // t0u.35: download the link now and say what it found
  const out = $("#cal-result"), b = $("#cal-test");
  b.disabled = true; out.textContent = "Reading the calendar…";
  const r = await api.test_calendar($("#f-calendar").value.trim()).catch(() => ({ ok: false, error: "Couldn't test the link." }));
  b.disabled = false;
  out.textContent = !r.ok ? r.error
    : `Works: ${r.today} event${r.today === 1 ? "" : "s"} today.` + (r.now ? ` Right now: ${r.now}.` : "") + " Save to use it.";
}
async function claudeRow() {
  const st = await api.claude_app().catch(() => ({ connected: false }));
  const b = $("#claude-connect");
  b.textContent = st.connected ? "Connected" : "Connect";
  b.disabled = st.connected;
  b.onclick = async () => {
    const out = await api.connect_claude_app();
    if (!out.ok) { toast(out.error || "Couldn't connect."); return; }
    toast("Done. Quit and reopen the Claude app, then ask it about your meetings.");
    claudeRow();
  };
}
function holdFits() {  // hold-to-talk needs a lone key: a combo fires on its press
  const combo = ($("#f-hotkey").value || "").includes("+");
  $("#f-hold").disabled = combo;
  if (combo) $("#f-hold").checked = false;
  $("#f-hold-help").textContent = combo ? `Needs a lone key like ${MAC ? "Right Command" : "Right Ctrl"}: a combo can't be held.`
    : "Hold the key while you speak and let go to stop. A quick tap still starts hands-free dictation.";
}
function hkWire() {
  $("#hk-change").onclick = () => {
    if (hk.on) { hkStop(); return; }
    hk.on = true; hk.other = false;
    $("#hk-change").textContent = "Cancel";
    $("#hk-label").textContent = "Press it now…";
    $("#hk-label").classList.add("listening");
    $("#hk-hint").textContent = "Esc cancels.";
  };
  document.addEventListener("keydown", (e) => {
    if (!hk.on) return;
    e.preventDefault(); e.stopPropagation();
    if (e.code === "Escape" && !e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey) { hkStop(); $("#hk-label").textContent = hotkeyLabel($("#f-hotkey").value); return; }
    if (HK_MODS.has(e.code)) return;  // wait: a combo or a lone modifier tap
    hk.other = true;
    const mods = [e.ctrlKey && "ctrl", e.altKey && "alt", e.shiftKey && "shift", e.metaKey && (MAC ? "cmd" : "win")].filter(Boolean);
    hkTry([...mods, hkName(e)].join("+"));
  }, true);
  document.addEventListener("keyup", (e) => {
    if (!hk.on) return;
    e.preventDefault();
    if (HK_MODS.has(e.code) && !hk.other) hkTry(hkName(e));  // a lone modifier tap, e.g. Right Ctrl
  }, true);
}

/* ---------------------------------------------------------------- bienvenida */
let wStep = 0, wKeyTimer = null;
async function openWelcome() {
  $("#welcome").hidden = false;
  wStep = 0;
  paintWelcome();
  wKeyTimer = setInterval(() => {
    const k = $("#w-key");
    k.classList.add("press");
    setTimeout(() => k.classList.remove("press"), 160);
  }, 1300);
}
async function paintWelcome() {
  $$(".wstep").forEach((s) => s.classList.toggle("on", Number(s.dataset.step) === wStep));
  $$(".step-dot").forEach((d, i) => d.classList.toggle("on", i === wStep));
  $("#w-next").textContent = wStep === 2 ? "Start" : "Next";
  $("#w-skip").style.visibility = wStep === 2 ? "hidden" : "visible";
  if (wStep === 1) {
    const r = await micStart(null, (lvl) => { $("#w-meter-fill").style.width = meterWidth(lvl); });
    if (r && !r.error) $("#w-mic-name").textContent = r.device ? `${prettyMic(r.device)}${r.fell_back ? " (default)" : ""}` : "Default mic";
  } else {
    await micStop();
  }
}
async function closeWelcome() {
  await micStop();
  clearInterval(wKeyTimer);
  await api.finish_welcome();
  $("#welcome").hidden = true;
  show("inicio");
}

/* ---------------------------------------------------------------- boot */
async function boot() {
  api = getApi();
  if (MAC) macify();
  try { R_LANGS = (await api.get_settings()).options.meet_langs.map((o) => [o.value, o.label]); } catch {}
  for (const b of $$(".nav-item")) b.onclick = () => { if (b.dataset.page === "reuniones") r.open = null; show(b.dataset.page); };
  try { $("#nav-insights").hidden = !(await api.get_settings()).values.insights; } catch {}
  for (const b of $$("#i-range .seg")) b.onclick = () => { iDays = b.dataset.days || null; renderInsights(); };
  $("#i-coach").onclick = async () => {
    const r = await api.coach_me();
    toast(r.ok ? "Copied: paste it into Claude." : "Nothing dictated to people in the last two weeks yet.");
  };
  $("#i-claude").onclick = async () => {
    const r = await api.insights_for_claude();
    if (r.ok) toast("Copied: paste it into Claude.");
  };
  rWire();
  notesWire();
  hkWire();
  $("#search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(renderHistory, 120); });
  $("#history-clear").onclick = async () => {
    if (!confirm("Clear the whole history? A backup copy is kept in the Ecoscribe folder.")) return;
    await api.clear_history(); renderHistory(); toast("History cleared.");
  };
  $("#settings").addEventListener("change", dirty);
  $("#settings").addEventListener("input", (e) => { if (e.target.id === "f-vocabulary" || e.target.id === "f-calendar" || e.target.closest(".snip")) dirty(); });  // savebar while typing words
  $("#settings").addEventListener("submit", (e) => e.preventDefault());
  $("#save").onclick = save;
  $("#discard").onclick = renderSettings;
  $("#mic-test").onclick = () => (mic.on ? stopMicTest() : startMicTest());
  $("#f-mic").addEventListener("change", async () => { if (mic.on) { await micStop(); startMicTest(); } });
  $("#w-next").onclick = async () => { if (wStep < 2) { wStep += 1; paintWelcome(); } else closeWelcome(); };
  $("#w-skip").onclick = closeWelcome;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#welcome").hidden) closeWelcome(); });

  const page = params.get("page");
  await show(page === "bienvenida" ? "inicio" : page || "inicio");
  const w = await api.get_welcome();
  if (page === "bienvenida" || !w.done) openWelcome();
  setInterval(refreshStatus, 1500);
  if (params.get("demo") === "1" && params.get("dirty") === "1") {  // screenshot of the save bar
    $("#f-sounds").checked = !$("#f-sounds").checked; dirty();
  }
  document.body.dataset.ready = "1";
}

/* macOS wording: the same page, Mac keys and places (uat.5) */
function macify() {
  const set = (sel, html) => { const el = $(sel); if (el) el.innerHTML = html; };
  set("#hero-how", 'Tap <kbd class="key key-wide">⌘</kbd> <span class="key-side">(right Command)</span>, talk, and tap it again. The text appears wherever the cursor is.');
  set("#tip-cancel", '<span class="keys"><kbd class="key">⌘</kbd><span class="plus">+</span><kbd class="key">Esc</kbd></span><span>Hold Right Command and press Esc to cancel.</span>');
  set("#hk-label", "Right Command");
  set("#hk-hint", HK_HINT);
  set("#w-key", "⌘");
  for (const el of $$(".tip .keys kbd.key")) if (el.textContent === "Ctrl") el.textContent = "⌘";
  const startup = $("#row-startup .row-label"); if (startup) startup.textContent = "Open at login";
  const unmute = $("#f-unmute"); if (unmute) unmute.closest("label").hidden = true;  // a PC fix (mics muted at 0)
  for (const el of $$("#page-ajustes .muted")) {  // dictado-p7c: Mac words in Settings
    el.innerHTML = el.innerHTML.replaceAll("this PC", "this Mac")
      .replace("(or the tray icon: Next dictation in)", "(or the menu bar icon: Dictation language)");
  }
  for (const p of $$("#welcome p")) {
    p.innerHTML = p.innerHTML.replace("<strong>Right Ctrl</strong>", "<strong>Right Command</strong>")
      .replace("Ecoscribe stays in the system tray, next to the clock, and starts with Windows. Open it any time from the Start menu.",
               "Ecoscribe lives in the menu bar (the mic at the top right) and opens at login. Open this window any time from that menu or from Applications.");
  }
}

if (params.get("demo") === "1") boot();               // screenshots, smoke tests
else if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot, { once: true });
window.__ecoscribe = { show, openWelcome, closeWelcome, formValues, dropped: rDropped, openSession, get api() { return api; } };
