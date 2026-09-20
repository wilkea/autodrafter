// Interfața de draft. Toată logica de joc stă pe server; aici doar afișăm
// starea primită și trimitem acțiunile jucătorului.

const $ = (id) => document.getElementById(id);
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};

const S = {
  heroes: [], byIdx: new Map(), algorithms: [],
  side: "FP", algo: "mcts",
  state: null, selected: null, hints: [],
  query: "", showHints: true,
  tick: null, deadline: 0,
};

const SIDE_NAME = { FP: "First Pick", FB: "Second Pick" };
const ALGO_LABEL = { greedy: "Greedy", alphabeta: "Alfa-beta", mcts: "MCTS" };
const ALGO_TAG = { greedy: "GRD", alphabeta: "A-B", mcts: "MCTS" };

// algoritmul care joacă o parte, sau null dacă o joacă omul
function sideAlgo(side) {
  const st = S.state;
  return st.players?.[side] || (side === st.bot ? st.algorithm : null);
}

// ordinea secțiunilor ca în selectorul de eroi din joc; "all" = universal
const ATTR_GROUPS = [
  { key: "str", label: "Forță" },
  { key: "agi", label: "Agilitate" },
  { key: "int", label: "Inteligență" },
  { key: "all", label: "Universal" },
];

// ---------------------------------------------------------------- pornire

async function boot() {
  const meta = await api("/api/meta");
  S.heroes = meta.heroes;
  S.algorithms = meta.algorithms;
  meta.heroes.forEach((h) => S.byIdx.set(h.idx, h));

  if (meta.placeholder) {
    const w = $("modelWarn");
    w.hidden = false;
    w.textContent =
      "Model placeholder: numerele sunt inventate, deci recomandările nu au " +
      "încă sens pentru un jucător. Rulează scriptul de colectare OpenDota " +
      "pentru datele reale.";
  }

  bindChoice("sideChoice", "side", (v) => (S.side = v));
  bindChoice("algoChoice", "algo", (v) => (S.algo = v));
  $("start").onclick = start;
  $("instant").onclick = startInstant;
}

const optsFor = (algo) => algo === "mcts" ? { iterations: 800 }
                        : algo === "alphabeta" ? { depth: 4, k: 10 } : {};

function bindChoice(containerId, attr, set) {
  const box = $(containerId);
  box.querySelectorAll(".opt").forEach((b) => {
    b.onclick = () => {
      box.querySelectorAll(".opt").forEach((x) => x.classList.remove("selected"));
      b.classList.add("selected");
      set(b.dataset[attr]);
    };
  });
}

async function start() {
  $("start").disabled = true;
  $("start").textContent = "Se pregătește…";
  try {
    const st = await api("/api/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ side: S.side, algorithm: S.algo, options: optsFor(S.algo) }),
    });
    $("setup").hidden = true;
    $("app").hidden = false;
    wireDraftUI();
    await apply(st);
  } catch (e) {
    alert("Nu am putut porni draftul: " + e.message);
    $("start").disabled = false;
    $("start").textContent = "Începe draftul";
  }
}

// Draft instant: serverul joacă toate cele 24 de acțiuni și răspunde abia la final.
async function startInstant() {
  const fp = $("algoFP").value, fb = $("algoFB").value;
  const btn = $("instant");
  $("start").disabled = btn.disabled = true;
  btn.textContent = "Se calculează draftul…";
  try {
    const st = await api("/api/instant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fp: { algorithm: fp, options: optsFor(fp) },
        fb: { algorithm: fb, options: optsFor(fb) },
      }),
    });
    $("setup").hidden = true;
    $("app").hidden = false;
    wireDraftUI();
    await apply(st);
  } catch (e) {
    alert("Draftul instant a eșuat: " + e.message);
    $("start").disabled = btn.disabled = false;
    btn.textContent = "Draft instant — algoritmii joacă ambele părți";
  }
}

function wireDraftUI() {
  $("seeDraft").onclick = openDraft;
  $("dmClose").onclick = closeDraft;
  $("draftModal").onclick = (e) => { if (e.target === e.currentTarget) closeDraft(); };
  document.onkeydown = (e) => { if (e.key === "Escape") closeDraft(); };
  $("search").oninput = (e) => { S.query = e.target.value.toLowerCase(); renderGrid(); };
  $("showHints").onchange = (e) => { S.showHints = e.target.checked; renderHints(); renderGrid(); };
  $("lock").onclick = lockIn;
  // "Top 1": joacă direct prima recomandare, fără să mai selectezi nimic
  $("top1").onclick = () => {
    if (!S.hints.length) return;
    S.selected = S.hints[0].hero;
    lockIn();
  };
}

// ---------------------------------------------------------------- stare

async function apply(st) {
  S.state = st;
  S.selected = null;
  renderAll();
  if (!st.terminal && st.current?.is_human) await loadHints();
  else { S.hints = []; renderHints(); }
  startClock();
  // la draftul instant, rezultatul e tot ce te interesează: îl arătăm direct
  if (st.mode === "instant" && st.terminal) openDraft();
}

async function loadHints() {
  try {
    const r = await api(`/api/suggest/${S.state.session}?top_k=6`);
    S.hints = r.suggestions || [];
    S.hintMeta = r;
  } catch { S.hints = []; }
  renderHints();
  renderGrid();
}

async function lockIn() {
  if (S.state?.terminal) { location.reload(); return; }   // "Draft nou"
  if (S.selected == null || !S.state?.current?.is_human) return;
  $("lock").disabled = true;
  $("top1").disabled = true;
  $("lock").textContent = "Adversarul gândește…";
  stopClock();
  try {
    const st = await api("/api/act", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: S.state.session, hero: S.selected }),
    });
    await apply(st);
  } catch (e) {
    alert(e.message);
  } finally {
    updateConfirm();     // reface butoanele după succes sau eroare
  }
}

// ---------------------------------------------------------------- randare

function renderAll() {
  renderGrid();
  renderOrder();
  renderHeader();
  renderWinbar();
  if (!$("draftModal").hidden) renderDraftModal();
}

// ---------------------------------------------------------------- vezi draftul

function openDraft() { renderDraftModal(); $("draftModal").hidden = false; }
function closeDraft() { $("draftModal").hidden = true; }

// Ca pe Liquipedia: pick-urile și ban-urile fiecărei echipe pornesc de la margine
// spre centru, în ordinea draftului; ban-urile stau dedesubt. Fiecare casetă poartă
// numărul turei, deci ordinea se vede și când ai doar imaginea în față.
function renderDraftModal() {
  const st = S.state;
  const heroAt = new Map(st.log.map((l) => [l.turn, l.hero]));

  const slot = (t) => {
    const id = heroAt.get(t.index);
    const h = id != null ? S.byIdx.get(id) : null;
    const cls = ["dm-slot", t.action];
    if (!h) cls.push("empty");
    if (t.index === st.turn && !st.terminal) cls.push("now");
    return `<div class="${cls.join(" ")}" title="${h ? h.name : ""}">
        <div class="dm-img">${h ? `<img src="${h.img}" alt="">` : ""}
          <span class="dm-n">${t.index + 1}</span></div>
        ${t.action === "pick" ? `<span class="dm-name">${h ? h.name : "—"}</span>` : ""}
      </div>`;
  };
  const half = (side, action) =>
    `<div class="dm-half ${side.toLowerCase()}">${
      st.schedule.filter((t) => t.side === side && t.action === action).map(slot).join("")}</div>`;
  const pair = (action) =>
    `<div class="dm-pair">${half("FP", action)}<div class="dm-mid"></div>${half("FB", action)}</div>`;

  const team = (side) => {
    const algo = sideAlgo(side);
    const who = side === st.human ? "tu" : algo ? ALGO_LABEL[algo] : "";
    return `<div class="dm-team ${side.toLowerCase()}"><b>${SIDE_NAME[side]}</b>
              ${who ? `<small>${who}</small>` : ""}</div>`;
  };
  const p = Math.round(st.win_probability.FP * 100);

  $("dmBody").innerHTML =
    `<div class="dm-pair">${team("FP")}
       <div class="dm-mid dm-vs"><span>${p}%</span><small>vs</small><span>${100 - p}%</span></div>
       ${team("FB")}</div>
     <h5 class="dm-title pick">Pick-uri</h5>${pair("pick")}
     <h5 class="dm-title ban">Ban-uri</h5>${pair("ban")}`;
}

function renderHeader() {
  const st = S.state, cur = st.current;
  if (st.terminal) {
    $("phaseLabel").textContent = st.mode === "instant" ? "Draft instant încheiat" : "Draft încheiat";
    $("phaseSub").textContent = "";
    $("timer").textContent = "—";
  } else {
    $("phaseLabel").textContent =
      `${cur.action === "ban" ? "BAN" : "PICK"} · faza ${cur.phase}`;
    $("phaseSub").textContent = cur.is_human
      ? "Rândul tău" : `Adversarul (${st.algorithm})`;
  }
  for (const side of ["FP", "FB"]) {
    const c = st.clocks[side], mine = side === st.human;
    $(`clock${side}`).innerHTML =
      `<span class="tc-name" style="color:var(--${side.toLowerCase()})">
         ${SIDE_NAME[side]}</span>
       ${mine ? '<span class="tc-you">TU</span>' : ""}
       <span class="tc-time">${st.mode === "instant"
         ? ALGO_LABEL[sideAlgo(side)] : `rezervă ${Math.round(c.reserve)}s`}</span>`;
  }
}

function renderWinbar() {
  const p = S.state.win_probability.FP;
  $("winFill").style.width = (p * 100).toFixed(1) + "%";
  $("winLeft").textContent = Math.round(p * 100) + "%";
  $("winRight").textContent = Math.round((1 - p) * 100) + "%";
}

function renderGrid() {
  const st = S.state;
  const picked = new Set([...(st.picks.FP || []), ...(st.picks.FB || [])]);
  const banned = new Set(st.banned);
  const rank = new Map(S.showHints ? S.hints.map((h, i) => [h.hero, i + 1]) : []);

  const card = (h) => {
    const cls = ["hero"];
    if (picked.has(h.idx)) cls.push("used", "picked");
    if (banned.has(h.idx)) cls.push("used", "banned");
    if (S.selected === h.idx) cls.push("sel");
    if (S.query && !h.name.toLowerCase().includes(S.query)) cls.push("dim");
    const r = rank.get(h.idx);
    return `<div class="${cls.join(" ")}" data-idx="${h.idx}" title="${h.name}">
        <img src="${h.img}" alt="" loading="lazy">
        ${r ? `<span class="rank">${r}</span>` : ""}
        <span class="nm">${h.name}</span>
      </div>`;
  };

  // patru coloane, câte una per atribut, toate vizibile; căutarea doar estompează
  $("grid").innerHTML = ATTR_GROUPS.map((g) => {
    const list = S.heroes.filter((h) => h.attr === g.key);
    return `<section class="attr-group ${g.key}">
        <h4>${g.label} <small>${list.length}</small></h4>
        <div class="grid">${list.map(card).join("")}</div>
      </section>`;
  }).join("");

  $("grid").querySelectorAll(".hero:not(.used)").forEach((el) => {
    el.onclick = () => select(Number(el.dataset.idx));
  });
  updateConfirm();
}

function select(idx) {
  if (!S.state.current?.is_human) return;
  S.selected = idx;
  renderGrid();
}

function updateConfirm() {
  const st = S.state, cur = st.current;
  const mine = !st.terminal && cur?.is_human;
  $("lock").disabled = !(st.terminal || (mine && S.selected != null));
  $("top1").disabled = !mine || !S.hints.length;
  $("top1").hidden = st.terminal;
  if (st.terminal) {
    $("selectedInfo").textContent = "Draftul s-a încheiat.";
  } else if (!cur.is_human) {
    $("selectedInfo").textContent = "Adversarul alege…";
  } else if (S.selected == null) {
    $("selectedInfo").textContent =
      `Selectează un erou pentru ${cur.action === "ban" ? "BAN" : "PICK"}`;
  } else {
    const h = S.byIdx.get(S.selected);
    $("selectedInfo").innerHTML =
      `<b>${h.name}</b> — ${cur.action === "ban" ? "va fi interzis" : "va fi ales"}`;
  }
  $("lock").textContent = st.terminal ? "Draft nou"
    : cur?.action === "ban" ? "Confirmă ban" : "Confirmă pick";
}

// La final, în locul recomandărilor: cine a câștigat pe hârtie și cât a costat fiecare parte.
function renderSummary() {
  const st = S.state;
  const p = st.win_probability.FP;
  const rows = ["FP", "FB"].map((side) => {
    const moves = st.log.filter((l) => l.side === side && l.elapsed_ms != null);
    const algo = sideAlgo(side);
    const who = algo ? ALGO_LABEL[algo] : "tu";
    const cost = moves.length
      ? `${moves.length} mutări · ${(moves.reduce((a, l) => a + l.elapsed_ms, 0) / 1000)
          .toFixed(1)} s · ${moves.reduce((a, l) => a + l.evals, 0).toLocaleString("ro")} evaluări`
      : "—";
    return `<div class="summary-row"><span><b>${SIDE_NAME[side]}</b> (${who})</span>
              <span>${cost}</span></div>`;
  }).join("");
  $("hints").innerHTML =
    `<div class="summary-head">Șanse estimate de câștig: <b>${SIDE_NAME.FP} ${Math.round(p * 100)}%</b>
       – <b>${SIDE_NAME.FB} ${Math.round((1 - p) * 100)}%</b></div>${rows}`;
}

function renderHints() {
  const box = $("hints");
  if (S.state?.terminal) { renderSummary(); return; }
  if (!S.showHints || !S.hints.length) { box.innerHTML = ""; return; }
  const m = S.hintMeta || {};
  const items = S.hints.map((h, i) => {
    const hero = S.byIdx.get(h.hero);
    return `<button class="hint" data-idx="${h.hero}">
        <img src="${hero.img}" alt="">
        <span><b>${i + 1}. ${hero.name}</b><small>${h.detail}</small></span>
        <span class="val">${(h.value * 100).toFixed(1)}%</span>
      </button>`;
  }).join("");
  box.innerHTML =
    `<div class="hints-head">
       <span>Recomandări pentru tine — <b>${m.algorithm || S.algo}</b></span>
       <span>${m.elapsed_ms ?? "?"} ms · ${(m.evals ?? 0).toLocaleString("ro")} evaluări</span>
     </div><div class="hint-list">${items}</div>`;
  box.querySelectorAll(".hint").forEach((el) => {
    el.onclick = () => select(Number(el.dataset.idx));
  });
}

// Coloana din dreapta: o linie pe fiecare tură, cu tipul acțiunii și eroul ales.
function renderOrder() {
  const st = S.state;
  const heroAt = new Map(st.log.map((l) => [l.turn, l.hero]));

  const rows = st.schedule.map((t, i) => {
    const prev = st.schedule[i - 1];
    const cls = ["ord", t.side.toLowerCase(), t.action];
    if (prev && (prev.phase !== t.phase || prev.action !== t.action)) cls.push("gap");
    if (t.index === st.turn && !st.terminal) cls.push("now");
    const h = heroAt.has(t.index) ? S.byIdx.get(heroAt.get(t.index)) : null;
    if (h) cls.push("done");

    const who = t.side === st.human ? "TU" : ALGO_TAG[sideAlgo(t.side)] || "ADV";
    const hero = h
      ? `<img src="${h.img}" alt=""><b>${h.name}</b>`
      : `<span class="ord-empty">${t.index === st.turn && !st.terminal ? "acum…" : "—"}</span>`;
    return `<div class="${cls.join(" ")}" title="${SIDE_NAME[t.side]} · faza ${t.phase}">
        <span class="ord-n">${t.index + 1}</span>
        <span class="ord-who">${who}</span>
        <span class="ord-type">${t.action === "ban" ? "BAN" : "PICK"}</span>
        <span class="ord-hero">${hero}</span>
      </div>`;
  }).join("");

  const box = $("order");
  box.innerHTML = rows;
  // tura curentă rămâne vizibilă, fără să derulăm toată pagina
  const now = box.querySelector(".now");
  if (now) box.scrollTop = now.offsetTop - box.clientHeight / 2 + now.offsetHeight / 2;
}

// ---------------------------------------------------------------- cronometru

function startClock() {
  stopClock();
  const st = S.state;
  if (st.terminal || !st.current) { $("timer").textContent = "—"; return; }
  const c = st.clocks[st.current.side];
  // ca în joc: întâi se scurge timpul de bază, abia apoi rezerva echipei
  S.actionEnd = Date.now() + c.action_left * 1000;
  S.reserveEnd = S.actionEnd + c.reserve * 1000;
  S.tick = setInterval(paintClock, 200);
  paintClock();
}

function stopClock() { if (S.tick) { clearInterval(S.tick); S.tick = null; } }

function paintClock() {
  const now = Date.now();
  const inReserve = now > S.actionEnd;
  const left = Math.max(0, ((inReserve ? S.reserveEnd : S.actionEnd) - now) / 1000);
  const el = $("timer");
  el.textContent = Math.ceil(left);
  el.classList.toggle("low", inReserve || left < 10);
  $("phaseSub").textContent = inReserve
    ? "REZERVĂ"
    : (S.state.current?.is_human ? "Rândul tău" : `Adversarul (${S.state.algorithm})`);
  if (inReserve && now >= S.reserveEnd) {
    stopClock();
    // ca în joc: dacă timpul expiră, se alege automat prima recomandare
    if (S.state.current?.is_human) {
      S.selected = S.hints[0]?.hero ?? firstFree();
      lockIn();
    }
  }
}

function firstFree() {
  const used = new Set([...(S.state.picks.FP || []), ...(S.state.picks.FB || []),
                        ...S.state.banned]);
  return S.heroes.find((h) => !used.has(h.idx))?.idx ?? 0;
}

boot().catch((e) => alert("Eroare la pornire: " + e.message));
