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
  attr: "all", query: "", showHints: true,
  tick: null, deadline: 0,
};

const SIDE_NAME = { FP: "First Pick", FB: "First Ban" };

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
}

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
    const opts = S.algo === "mcts" ? { iterations: 800 }
              : S.algo === "alphabeta" ? { depth: 4, k: 10 } : {};
    const st = await api("/api/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ side: S.side, algorithm: S.algo, options: opts }),
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

function wireDraftUI() {
  $("attrs").querySelectorAll(".attr").forEach((b) => {
    b.onclick = () => {
      $("attrs").querySelectorAll(".attr").forEach((x) => x.classList.remove("selected"));
      b.classList.add("selected");
      S.attr = b.dataset.attr;
      renderGrid();
    };
  });
  $("search").oninput = (e) => { S.query = e.target.value.toLowerCase(); renderGrid(); };
  $("showHints").onchange = (e) => { S.showHints = e.target.checked; renderHints(); };
  $("lock").onclick = lockIn;
}

// ---------------------------------------------------------------- stare

async function apply(st) {
  S.state = st;
  S.selected = null;
  renderAll();
  if (!st.terminal && st.current?.is_human) await loadHints();
  else { S.hints = []; renderHints(); }
  startClock();
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
  if (S.selected == null || !S.state?.current?.is_human) return;
  $("lock").disabled = true;
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
    $("lock").textContent = "Confirmă";
  }
}

// ---------------------------------------------------------------- randare

function renderAll() {
  renderTeams();
  renderGrid();
  renderSequence();
  renderHeader();
  renderWinbar();
}

function renderHeader() {
  const st = S.state, cur = st.current;
  if (st.terminal) {
    $("phaseLabel").textContent = "Draft încheiat";
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
      `<span class="tc-name" style="color:var(--${side === "FP" ? "radiant" : "dire"})">
         ${SIDE_NAME[side]}</span>
       ${mine ? '<span class="tc-you">TU</span>' : ""}
       <span class="tc-time">rezervă ${Math.round(c.reserve)}s</span>`;
  }
}

function renderWinbar() {
  const p = S.state.win_probability.FP;
  $("winFill").style.width = (p * 100).toFixed(1) + "%";
  $("winLeft").textContent = Math.round(p * 100) + "%";
  $("winRight").textContent = Math.round((1 - p) * 100) + "%";
}

function renderTeams() {
  const st = S.state;
  // echipa ta apare mereu în stânga
  paintTeam($("teamLeft"), st.human);
  paintTeam($("teamRight"), st.bot);
}

function paintTeam(el, side) {
  const st = S.state;
  const picks = st.picks[side] || [];
  const myBans = st.log.filter((l) => l.action === "ban" && l.side === side)
                       .map((l) => l.hero);
  el.className = "team " + side.toLowerCase();
  const slots = Array.from({ length: 5 }, (_, i) => {
    const h = picks[i] != null ? S.byIdx.get(picks[i]) : null;
    return h
      ? `<div class="slot filled"><img src="${h.img}" alt=""><span>${h.name}</span></div>`
      : `<div class="slot"></div>`;
  }).join("");
  const banImgs = myBans.map((i) => {
    const h = S.byIdx.get(i);
    return `<img src="${h.img}" title="${h.name}" alt="">`;
  }).join("");
  el.innerHTML =
    `<h3>${SIDE_NAME[side]}${side === st.human ? " · tu" : ""}</h3>${slots}
     <div class="bans"><h4>Ban-uri (${myBans.length}/7)</h4>
       <div class="ban-row">${banImgs}</div></div>`;
}

function renderGrid() {
  const st = S.state;
  const used = new Set([...(st.picks.FP || []), ...(st.picks.FB || []), ...st.banned]);
  const banned = new Set(st.banned);
  const rank = new Map(S.showHints ? S.hints.map((h, i) => [h.hero, i + 1]) : []);

  const list = S.heroes.filter(
    (h) => (S.attr === "all" || h.attr === S.attr) &&
           (!S.query || h.name.toLowerCase().includes(S.query))
  );

  $("grid").innerHTML = list.map((h) => {
    const isUsed = used.has(h.idx);
    const cls = ["hero"];
    if (isUsed) cls.push("used");
    if (banned.has(h.idx)) cls.push("banned");
    if (S.selected === h.idx) cls.push("sel");
    const r = rank.get(h.idx);
    return `<div class="${cls.join(" ")}" data-idx="${h.idx}" title="${h.name}">
        <img src="${h.img}" alt="" loading="lazy">
        ${r ? `<span class="rank">${r}</span>` : ""}
        <span class="nm">${h.name}</span>
      </div>`;
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
  const can = !st.terminal && cur?.is_human && S.selected != null;
  $("lock").disabled = !can;
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
  $("lock").textContent = !st.terminal && cur?.action === "ban" ? "Confirmă ban" : "Confirmă pick";
}

function renderHints() {
  const box = $("hints");
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

function renderSequence() {
  const st = S.state;
  $("sequence").innerHTML = st.schedule.map((t) => {
    const cls = ["step", t.side.toLowerCase(), t.action];
    if (t.index < st.turn) cls.push("done");
    if (t.index === st.turn) cls.push("now");
    return `<div class="${cls.join(" ")}" title="${SIDE_NAME[t.side]} · ${t.action} · faza ${t.phase}">
        ${t.action === "ban" ? "B" : "P"}</div>`;
  }).join("");
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
