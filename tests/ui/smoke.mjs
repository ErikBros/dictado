// jsdom smoke test of the Ecoscribe window in demo mode: every page renders and the
// main interactions work. Run from WSL: node tests/ui/smoke.mjs
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const here = path.dirname(fileURLToPath(import.meta.url));
const web = path.resolve(here, "../../ecoscribe/web");
// jsdom: ECOSCRIBE_JSDOM (path to jsdom/lib/api.js) if set, else Node's normal lookup from this folder up
// (a node_modules here, in the repo, or in any parent folder), else the global install.
async function loadJsdom() {
  if (process.env.ECOSCRIBE_JSDOM) return import(pathToFileURL(process.env.ECOSCRIBE_JSDOM).href);
  const { createRequire } = await import("module");
  for (const base of [import.meta.url, pathToFileURL(path.join(process.env.NODE_PATH || "", "x")).href]) {
    try { return import(pathToFileURL(createRequire(base).resolve("jsdom")).href); } catch {}
  }
  try {
    const { execSync } = await import("child_process");
    const root = execSync("npm root -g").toString().trim();
    return import(pathToFileURL(createRequire(path.join(root, "x")).resolve("jsdom")).href);
  } catch {}
  throw new Error("jsdom not found: npm install jsdom (here or globally) or set ECOSCRIBE_JSDOM");
}
const { JSDOM } = await loadJsdom();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (cond, msg) => { if (!cond) { failed++; console.log("FAIL", msg); } else console.log("ok  ", msg); };

async function load(query) {
  const html = fs.readFileSync(path.join(web, "index.html"), "utf8").replace('<script src="app.js"></script>', "");
  const dom = new JSDOM(html, { url: `file:///x/index.html?demo=1&${query}`, runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  window.confirm = () => true;
  const errors = [];
  window.addEventListener("error", (e) => errors.push(e.message));
  window.eval(fs.readFileSync(path.join(web, "app.js"), "utf8"));
  for (let i = 0; i < 50 && window.document.body.dataset.ready !== "1"; i++) await sleep(20);
  return { window, doc: window.document, errors };
}

{ // ajustes: your words (market deep dive 2026-10-05)
  const { window, doc } = await load("page=ajustes");
  const v = doc.querySelector("#f-vocabulary");
  check(v && v.value === "Göteborg\npyannote", "Your words shows the saved list");
  check(doc.querySelector("#f-voice-commands") && !doc.querySelector("#f-voice-commands").checked, "voice commands off by default");
  check(doc.querySelector("#f-screen-names")?.checked === true, "names on your screen on by default");
  check(doc.querySelector("#f-hold") && !doc.querySelector("#f-hold").checked && !doc.querySelector("#f-hold").disabled, "hold to talk off by default, available for Right Ctrl");
  v.value = "Göteborg\npyannote\n  Kristineberg  \n"; v.dispatchEvent(new window.Event("input", { bubbles: true }));
  check(!doc.querySelector("#savebar").hidden, "typing a word shows the savebar");
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (x) => { sent = x; return orig(x); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && sent.vocabulary === "Göteborg\npyannote\nKristineberg" && Object.keys(sent).length === 1, "saves only the word list, trimmed: " + JSON.stringify(sent));
}
{ // ajustes: voice memory (t0u.32)
  const { window, doc } = await load("page=ajustes");
  await sleep(50);
  check(doc.querySelector("#f-voice-memory")?.checked === true, "remember voices on by default");
  check(!doc.querySelector("#voices-row").hidden && doc.querySelector("#voices-known").textContent === "Knows 2 voices: Ana, Tom", "known voices listed");
  doc.querySelector("#voices-forget").click(); await sleep(100);
  check(doc.querySelector("#voices-row").hidden, "forget all voices empties the list");
}
{ // ajustes: Claude app (t0u.31)
  const { window, doc } = await load("page=ajustes");
  await sleep(50);
  const b = doc.querySelector("#claude-connect");
  check(b && b.textContent === "Connect" && !b.disabled, "Claude app: Connect offered");
  b.click(); await sleep(100);
  check(b.textContent === "Connected" && b.disabled, "Claude app: connected after the click");
}
{ // ajustes: snippets (t0u.29)
  const { window, doc } = await load("page=ajustes");
  check(doc.querySelectorAll(".snip").length === 1 && doc.querySelector(".snip-trigger").value === "my email", "saved snippet shown");
  doc.querySelector("#snip-add").click();
  const rows = doc.querySelectorAll(".snip");
  rows[1].querySelector(".snip-trigger").value = "  My  Signature ";
  rows[1].querySelector(".snip-text").value = "Best,\nAlex";
  rows[1].querySelector(".snip-text").dispatchEvent(new window.Event("input", { bubbles: true }));
  check(!doc.querySelector("#savebar").hidden, "a new snippet shows the savebar");
  let sent = null;
  const api = window.__ecoscribe.api, orig = api.save_settings;
  api.save_settings = async (x) => { sent = x; return orig(x); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && Object.keys(sent).length === 1 && sent.snippets?.[1]?.trigger === "my signature" && sent.snippets[1].text === "Best,\nAlex",
        "saves the snippets: " + JSON.stringify(sent));
  rows[0].querySelector(".snip-del").click();
  check(doc.querySelectorAll(".snip").length === 1, "remove drops the row");
}
{ // inicio: the dictation languages, read-only (dictado-bvf: set them in Settings)
  const { doc } = await load("page=inicio");
  check(doc.querySelector("#fact-lang").textContent === "English", "Home shows the dictation language: " + doc.querySelector("#fact-lang").textContent);
}
{ // ajustes: speakers toggle follows the add-on (t0u.22)
  const on = await load("page=ajustes");
  check(!on.doc.querySelector("#f-speakers").disabled && on.doc.querySelector("#f-speakers").checked, "speakers toggle on with the add-on");
  const off = await load("page=ajustes&addon=0");
  check(off.doc.querySelector("#f-speakers").disabled && /isn't installed/.test(off.doc.querySelector("#f-speakers-help").textContent), "no add-on: toggle off and says why");
}
{ // insights (dictado-3je): off by default, a Settings switch adds the tab
  const off = await load("page=inicio");
  check(off.doc.querySelector("#nav-insights").hidden, "Insights tab hidden by default");
  check(off.doc.querySelector("#f-insights") && !off.doc.querySelector("#f-insights").checked, "Insights switch off by default");
  const { window, doc, errors } = await load("page=insights&insights=1");
  await sleep(50);
  check(!doc.querySelector("#nav-insights").hidden && !doc.querySelector("#page-insights").hidden, "Insights tab shown when switched on");
  check(doc.querySelector("#i-saved").textContent === "3 h 22 min", "time saved: " + doc.querySelector("#i-saved").textContent);
  check(doc.querySelectorAll("#i-hours path.bar").length > 5 && doc.querySelectorAll("#i-days .tick").length === 3, "hour and day charts drawn");
  check(doc.querySelectorAll("#i-langs .i-hbar").length === 4 && doc.querySelector("#i-langs .i-hbar-name").textContent === "English", "languages by name");
  check(doc.querySelector("#i-habits").textContent.includes("3.1"), "filler words per 100");
  check(doc.querySelector("#i-clarity").textContent === "91%" && doc.querySelector("#i-clarity-empty").hidden
    && doc.querySelectorAll("#i-clarity-weeks path.bar").length === 4, "clarity: score and the weeks that have one (9jc.1)");
  check(doc.querySelectorAll("#i-unsure .i-chip").length === 4 && doc.querySelector("#i-unsure .i-chip").title === "Unsure 4 of the 6 times you said it", "words it wasn't sure of, per language");
  check(doc.querySelector("#i-hedges").textContent === "2.4" && doc.querySelectorAll("#i-markers-weeks path.bar").length === 5
    && doc.querySelectorAll("#i-top-hedges .i-chip").length === 3, "hedges and fillers in messages to people (9jc.3)");
  check(doc.querySelectorAll("#i-pace-rows .i-habit").length === 2 && doc.querySelector("#i-pace-rows .i-habit-num").textContent === "148"
    && doc.querySelectorAll("#i-pace-hist path.bar:not(.dim)").length === 3, "pace to people and to AI apps, the 130-160 band marked (9jc.4)");
  check(!doc.querySelector("#i-coach").disabled && doc.querySelector("#i-coach").title.startsWith("64 messages to people"), "Coach me ready with messages to people (9jc.2)");
  const add = doc.querySelector("#i-suggest li button");
  add.click(); await sleep(30);
  check(window.__added === "Ecoscribe" && doc.querySelectorAll("#i-suggest li").length === 2, "Add puts the suggested spelling in Your words");
  doc.querySelector('#i-range .seg[data-days="7"]').click(); await sleep(30);
  check(doc.querySelector('#i-range .seg[data-days="7"]').getAttribute("aria-checked") === "true" && doc.querySelector("#i-words").textContent === "3,540", "7 days range");
  check(errors.length === 0, "no errors on Insights: " + errors.join("; "));
}
{ // inicio
  const { doc, errors } = await load("page=inicio");
  check(doc.body.dataset.ready === "1", "boots in demo mode");
  check(!doc.querySelector("#page-inicio").hidden, "inicio visible");
  check(doc.querySelector("#hero-title").textContent === "Ready to dictate", "hero says ready");
  check(doc.querySelector("#fact-mic").textContent === "Anker PowerConf C20", "mic name prettified");
  check(doc.querySelector("#stat-today").textContent === "152", "today stat");
  check(doc.querySelector("#last-text").textContent.startsWith("Can you check"), "last dictation shown");
  check(doc.querySelector(".nav-item.active").dataset.page === "inicio", "nav highlights inicio");
  check(doc.querySelector("#welcome").hidden, "no welcome when done");
  check(errors.length === 0, "no JS errors: " + errors.join("; "));
}
{ // stopped
  const { doc } = await load("page=inicio&state=stopped");
  check(doc.querySelector("#hero-actions button")?.textContent === "Start Ecoscribe", "stopped offers start button");
  check(doc.querySelector("#fact-engine").textContent === "—", "stopped shows no stale facts");
}
{ // historial + search
  const { window, doc } = await load("page=historial");
  check(doc.querySelectorAll(".h-item:not(.h-meeting)").length === 4, "history lists 4 dictations");
  check(doc.querySelectorAll(".h-meeting").length === 5, "and the 5 meeting transcripts");
  const done = [...doc.querySelectorAll(".h-meeting")].find((li) => li.textContent.includes("Planering"));
  check(done && [...done.querySelectorAll("button")].map((b) => b.textContent).join(",") === "Open,Download .md", "a finished meeting: Open + Download .md");
  done.querySelector("button").click(); await sleep(200);
  check(!doc.querySelector("#page-reuniones").hidden && !doc.querySelector("#r-detail-view").hidden, "Open jumps to the transcript");
  doc.querySelector('.nav-item[data-page="historial"]').click(); await sleep(150);
  check(doc.querySelector(".badge")?.textContent === "didn't paste", "not-pasted badge");
  const s = doc.querySelector("#search");
  s.value = "climbing"; s.dispatchEvent(new window.Event("input"));
  await sleep(250);
  check(doc.querySelectorAll(".h-item").length === 1, "search filters");
  s.value = "zzz"; s.dispatchEvent(new window.Event("input"));
  await sleep(250);
  check(!doc.querySelector("#history-empty").hidden && doc.querySelector("#history-empty-text").textContent.includes("zzz"), "empty search state");
  s.value = ""; s.dispatchEvent(new window.Event("input")); await sleep(250);
  doc.querySelector("#history-clear").click(); await sleep(100);
  check(doc.querySelectorAll(".h-item:not(.h-meeting)").length === 0 && doc.querySelectorAll(".h-meeting").length === 5, "clear history removes dictations, keeps meetings");
}
{ // ajustes
  const { window, doc } = await load("page=ajustes");
  check(doc.querySelector("#f-hotkey").value === "rctrl" && doc.querySelector("#hk-label").textContent === "Right Ctrl", "hotkey loaded");
  const key = (type, code, mods = {}) => doc.dispatchEvent(new window.KeyboardEvent(type, { code, bubbles: true, cancelable: true, ...mods }));
  doc.querySelector("#hk-change").click();
  check(doc.querySelector("#hk-label").textContent === "Press it now…", "recorder listens");
  key("keydown", "ControlLeft", { ctrlKey: true }); key("keydown", "KeyL", { ctrlKey: true }); await sleep(50);
  check(doc.querySelector("#f-hotkey").value === "ctrl+l" && doc.querySelector("#hk-label").textContent === "Ctrl+L", "recorder takes a combo");
  check(!doc.querySelector("#savebar").hidden, "a new shortcut marks the form dirty");
  doc.querySelector("#hk-change").click();
  key("keydown", "ControlLeft", { ctrlKey: true }); key("keydown", "KeyC", { ctrlKey: true }); await sleep(50);
  check(doc.querySelector("#f-hotkey").value === "ctrl+l" && doc.querySelector("#hk-hint").classList.contains("hk-bad"), "a taken combo is refused with the reason");
  doc.querySelector("#hk-change").click();
  key("keydown", "ControlRight", { ctrlKey: true }); key("keyup", "ControlRight"); await sleep(50);
  check(doc.querySelector("#f-hotkey").value === "rctrl" && doc.querySelector("#hk-label").textContent === "Right Ctrl", "recorder takes a lone Right Ctrl tap");
  check(doc.querySelector("#f-mic").selectedOptions[0].textContent.includes("Anker"), "mic selected");
  check(doc.querySelector("#savebar").hidden, "no savebar before changes");
  const sounds = doc.querySelector("#f-sounds");
  sounds.checked = false; sounds.dispatchEvent(new window.Event("change", { bubbles: true }));
  check(!doc.querySelector("#savebar").hidden, "savebar appears on change");
  sounds.checked = true; sounds.dispatchEvent(new window.Event("change", { bubbles: true }));
  check(doc.querySelector("#savebar").hidden, "savebar hides when change undone");
  // languages as add-ons (dictado-ehs): English + Swedish built in, Spanish added from the picker
  check([...doc.querySelectorAll("#f-languages input")].map((i) => i.value).join(",") === "en,sv", "built in: English + Swedish");
  check(!doc.querySelector("#f-languages .lang-x"), "built-in languages can't be removed");
  const add = doc.querySelector("#lang-add");
  check([...add.options].some((o) => o.value === "es") && ![...add.options].some((o) => o.value === "sv"), "the picker offers the rest, not the built-in ones");
  add.value = "es"; add.dispatchEvent(new window.Event("change", { bubbles: true }));
  const es = doc.querySelector('#f-languages input[value="es"]');
  check(es && es.checked && doc.querySelector("#f-languages .lang-x"), "Spanish added, ticked, removable");
  check(!doc.querySelector("#savebar").hidden, "language change marks dirty");
  let sent = null;
  const api = window.__ecoscribe.api;
  const orig = api.save_settings;
  api.save_settings = async (v) => { sent = v; return orig(v); };
  doc.querySelector("#save").click(); await sleep(100);
  check(sent && sent.languages === "en,es" && JSON.stringify(sent.extra_languages) === '["es"]' && Object.keys(sent).length === 2,
        "saves the added language and the ticks: " + JSON.stringify(sent));
  check(doc.querySelector("#savebar").hidden && !doc.querySelector("#toast").hidden, "saved: bar gone, toast shown");
  doc.querySelector("#mic-test").click(); await sleep(300);
  check(doc.querySelector("#mic-test").textContent === "Stop" && parseFloat(doc.querySelector("#meter-fill").style.width) > 0, "mic test moves the meter");
  doc.querySelector('.nav-item[data-page="inicio"]').click(); await sleep(100);
  check(doc.querySelector("#mic-test").textContent === "Test", "leaving ajustes stops the mic test");
  // races: count open tests through the fake api
  let open = 0;
  const a2 = window.__ecoscribe.api;
  const s0 = a2.mic_test_start, s1 = a2.mic_test_stop;
  a2.mic_test_start = async (d) => { await sleep(60); open = 1; return s0(d); };
  a2.mic_test_stop = async () => { open = 0; return s1(); };
  doc.querySelector('.nav-item[data-page="ajustes"]').click(); await sleep(150);
  const b = doc.querySelector("#mic-test");
  b.click(); b.click(); await sleep(250);          // double click: start then stop
  check(open === 0 && b.textContent === "Test", "double click leaves no mic open");
  b.click(); await sleep(10);
  doc.querySelector('.nav-item[data-page="historial"]').click(); await sleep(300);  // leave mid-start
  check(open === 0, "leaving during a start leaves no mic open");
}
{ // reuniones: list, live, done, drop, deep link
  const { window, doc, errors } = await load("page=reuniones");
  check(!doc.querySelector("#page-reuniones").hidden, "reuniones visible");
  check(doc.querySelectorAll(".r-row").length === 5, "list shows 5 sessions");
  check(doc.querySelector(".r-row .r-chip").textContent === "Recording", "first row is the recording one");
  check([...doc.querySelectorAll(".r-chip")].some((c) => c.textContent === "Transcribing 42 %"), "job shows its percent");
  check(!doc.querySelector("#r-now").hidden && doc.querySelector("#r-start").disabled, "banner while recording, start disabled");
  check(doc.querySelector("#r-lang").options.length === 4 && doc.querySelector("#r-lang").value === "sv", "meeting languages: English, Swedish, English + Swedish, Detect; Swedish default");
  const s = doc.querySelector("#r-search");
  s.value = "planering"; s.dispatchEvent(new window.Event("input")); await sleep(250);
  check(doc.querySelectorAll(".r-row").length === 1, "search filters sessions");
  s.value = ""; s.dispatchEvent(new window.Event("input")); await sleep(250);
  doc.querySelector(".r-row").click(); await sleep(150);
  check(!doc.querySelector("#r-detail-view").hidden && doc.querySelector("#r-list-view").hidden, "one click opens the session");
  check(!doc.querySelector("#r-d-live-actions").hidden && doc.querySelector("#r-d-stop").textContent === "Stop", "Stop visible while recording");
  const sel = doc.querySelector("#r-d-lang");
  check(sel.value === "sv" && sel.options.length === 4, "live view shows the meeting language");
  sel.value = "en"; sel.dispatchEvent(new window.Event("change")); await sleep(100);
  check(window.__lang === "en" && doc.querySelector("#toast").textContent.includes("English"), "switching the language mid-meeting");
  const first = doc.querySelectorAll(".r-seg").length;
  const firstNode = doc.querySelector(".r-seg");
  await sleep(1150);
  check(doc.querySelectorAll(".r-seg").length > first && doc.querySelector(".r-seg") === firstNode, "live poll appends without re-rendering old lines");
  { // t0u.19: reading back while it records must not yank the list to the bottom
    const list = doc.querySelector("#r-segs");
    Object.defineProperty(list, "scrollHeight", { configurable: true, get: () => 2000 });
    Object.defineProperty(list, "clientHeight", { configurable: true, get: () => 400 });
    list.scrollTop = 300;  // scrolled up
    const n = doc.querySelectorAll(".r-seg").length;
    await sleep(1150);
    check(doc.querySelectorAll(".r-seg").length > n && list.scrollTop === 300, "scrolled up: a new live line keeps the scroll");
    check(!doc.querySelector("#r-jump").hidden, "scrolled up: 'Jump to latest' shows");
    doc.querySelector("#r-jump").click();
    check(list.scrollTop === 2000 && doc.querySelector("#r-jump").hidden, "'Jump to latest' goes to the bottom and hides");
  }
  doc.querySelector("#r-back").click(); await sleep(150);
  check(!doc.querySelector("#r-list-view").hidden, "back to the list");
  [...doc.querySelectorAll(".r-row")].find((li) => li.dataset.name === "2026-10-05_0915_planering").click(); await sleep(150);
  check(!doc.querySelector("#r-d-done-actions").hidden && doc.querySelectorAll(".r-seg").length === 4, "done session: transcript + actions");
  check(doc.querySelector('.r-who[data-who="Others"]') !== null, "speaker labels shown");
  check(doc.querySelector("#r-copy-summary")?.textContent === "Copy summary prompt", "done session offers a summary prompt");
  { // t0u.22: several remote speakers, named and renamed
    doc.querySelector("#r-back").click(); await sleep(150);
    [...doc.querySelectorAll(".r-row")].find((li) => li.dataset.name === "2026-10-04_1600_kund").click(); await sleep(150);
    const whos = () => [...doc.querySelectorAll(".r-who")].map((w) => w.textContent);
    check(JSON.stringify(whos()) === JSON.stringify(["Me", "Speaker 1", "Ana", "Speaker 3", "Me"]), "speakers shown, a named one by its name: " + whos());
    const w = [...doc.querySelectorAll(".r-who-edit")].find((x) => x.dataset.label === "Speaker 1");
    w.click();
    const inp = w.querySelector("input");
    check(inp && inp.value === "Speaker 1", "click a label: an input with the current name");
    inp.value = "Leo"; inp.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter" })); await sleep(50);
    check(window.__renamed?.[0] === "Speaker 1" && window.__renamed?.[1] === "Leo" && whos()[1] === "Leo", "Enter saves and relabels");
  }
  const drop = new window.Event("drop", { bubbles: true, cancelable: true });
  drop.dataTransfer = { files: [{ name: "pod.mp3", path: "C:\\x\\pod.mp3" }], types: ["Files"] };
  doc.dispatchEvent(drop); await sleep(100);
  check(JSON.stringify(window.__imported) === JSON.stringify(["C:\\x\\pod.mp3"]), "drop imports the file paths");
  check(errors.length === 0, "no JS errors on reuniones: " + errors.join("; "));
  const deep = await load("page=reuniones/2026-10-04_1600_kund");
  await sleep(150);
  check(!deep.doc.querySelector("#r-detail-view").hidden && deep.doc.querySelector("#r-d-title").value === "Client call", "deep link opens a session");
}
{ // t0u.30: notes during a call, kept while the live view polls
  const { window, doc } = await load("page=reuniones/2026-10-05_1400_retro");
  await sleep(200);
  const box = doc.querySelector("#r-notes-text");
  check(box && box.value.startsWith("- Is the export date firm?"), "live session shows its saved notes");
  box.value += "\n- budget"; box.dispatchEvent(new window.Event("input", { bubbles: true }));
  await sleep(900);
  check(window.__notes?.["2026-10-05_1400_retro"]?.endsWith("- budget") && doc.querySelector("#r-notes-state").textContent === "Saved.", "typing saves the notes");
  check(box.value.endsWith("- budget"), "a live poll doesn't overwrite the notes");
}
{ // bienvenida
  const { window, doc } = await load("page=bienvenida&welcome=1");
  check(!doc.querySelector("#welcome").hidden, "welcome opens on first run");
  const next = doc.querySelector("#w-next");
  check(doc.querySelector('.wstep.on').dataset.step === "0", "step 1");
  next.click(); await sleep(250);
  check(doc.querySelector('.wstep.on').dataset.step === "1" && doc.querySelector("#w-mic-name").textContent.includes("Anker"), "step 2 shows the mic");
  next.click(); await sleep(100);
  check(next.textContent === "Start", "last step button says Start");
  check(window.__ecoscribe && true, "api reachable");
  next.click(); await sleep(100);
  check(doc.querySelector("#welcome").hidden && !doc.querySelector("#page-inicio").hidden, "welcome closes to inicio");
}
console.log(failed ? `\n${failed} FAILED` : "\nall ok");
process.exit(failed ? 1 : 0);
