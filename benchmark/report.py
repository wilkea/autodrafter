"""Transformă rezultatul unei evaluări într-un raport Markdown, în română.

    python -m benchmark.report                     # cel mai recent rezultat
    python -m benchmark.report --result benchmark/results/20260920-193000.json

Raportul începe cu verdictul, apoi cifrele, apoi interpretarea lor. Dacă în
results/ există o rulare anterioară, o compară automat cu cea curentă.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from benchmark.evaluate import RESULTS_DIR

LN2 = math.log(2.0)

# pragurile sub care o diferență între două rulări se consideră „neschimbat"
NOISE = {"logloss": 5e-4, "brier": 5e-4, "auc": 2e-3, "accuracy": 2e-3, "slope": 0.05}

AVERTISMENT = (
    "**Avertisment metodologic — rezultatele sunt OPTIMISTE.** Modelul actual este "
    "construit din statistici agregate OpenDota (`heroStats` și `matchups`) dintr-o "
    "fereastră recentă de timp, care se SUPRAPUNE peste meciurile de test: aceleași "
    "meciuri au contribuit și la estimarea lui β și a matricei counter, și la testul "
    "de față. Performanța pe meciuri nevăzute poate fi doar egală sau mai slabă. "
    "Soluția corectă este colectarea de meciuri brute și antrenarea pe o fereastră "
    "**anterioară** celei de test (împărțire cronologică, nu aleatoare)."
)


# ---------------------------------------------------------------- formatare

def pct(x: float, d: int = 1) -> str:
    return f"{100 * x:.{d}f}%"


def ci(lo: float, hi: float, d: int = 3) -> str:
    return f"[{lo:.{d}f}, {hi:.{d}f}]"


def table(head: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def auc_reading(lo: float, hi: float) -> str:
    if lo <= 0.5 <= hi:
        return "nu se distinge de 0.5 (zgomot)"
    return "peste 0.5, semnificativ" if lo > 0.5 else "sub 0.5, semnificativ (semnal inversat)"


# ---------------------------------------------------------------- verdict

def verdict(res: dict) -> tuple[str, str]:
    """(cod, propoziție). Codul: broken | loses_radiant | inconclusive | beats_both."""
    ll = res["metrics"]["model"]["logloss"]
    dc = res["deltas"]["vs_const_0.5"]["logloss"]
    dr = res["deltas"]["vs_radiant_rate"]["logloss"]
    rr = res["radiant_rate"]
    ll_r = res["metrics"]["radiant_rate"]["logloss"]
    nu_are = "deci NU are valoare demonstrată ca predictor al rezultatului"

    if dc["mean"] > 0:
        semn = ("diferență semnificativă statistic" if dc["lo"] > 0
                else "diferență în limita zgomotului, dar sensul e greșit")
        return "broken", (
            f"Modelul este STRICAT, nu doar slab: log-loss {ll:.4f} este mai rău decât al "
            f"predicției constante 0.5 ({LN2:.4f}) — {semn} — {nu_are}.")
    if dr["mean"] >= 0:
        return "loses_radiant", (
            f"Modelul bate predicția constantă 0.5 (log-loss {ll:.4f} față de {LN2:.4f}), dar "
            f"NU bate baza „avantaj Radiant” ({pct(rr)} rată de câștig, log-loss {ll_r:.4f}), "
            f"{nu_are}: tot ce știe despre eroi valorează mai puțin decât a ști cine e Radiant.")
    if dc["hi"] < 0 and dr["hi"] < 0:
        lo, hi = res["metrics"]["model"]["auc_ci"]
        caveat = ("testat pe meciuri nevăzute la antrenare (hold-out cronologic)"
                  if own_holdout(res)
                  else "dar rezultatul este optimist, vezi avertismentul de mai jos")
        return "beats_both", (
            f"Modelul bate ambele baze, cu semnificație statistică: log-loss {ll:.4f} față de "
            f"{LN2:.4f} (constant 0.5) și {ll_r:.4f} (avantaj Radiant); AUC "
            f"{res['metrics']['model']['auc']:.3f} {ci(lo, hi)} — {caveat}.")
    return "inconclusive", (
        f"Modelul are log-loss puțin mai bun decât ambele baze ({ll:.4f} față de {LN2:.4f} și "
        f"{ll_r:.4f}), dar intervalul de încredere include 0: cu {res['data']['n_test']:,} "
        f"meciuri NU se poate demonstra că le bate, {nu_are}.")


# ---------------------------------------------------------------- secțiuni

def own_holdout(res: dict) -> bool:
    """Modelul a fost antrenat cronologic față de hold-out-ul pe care e testat."""
    g = res["data"].get("holdout_guard")
    return bool(g and g.get("own"))


def is_raw_model(res: dict) -> bool:
    """Modelul e construit din meciuri brute de etl/build_model.py (nu din heroStats)."""
    return res["model"]["meta"].get("source") == "publicmatches"


def overlap_note(res: dict) -> str:
    """Avertismentul metodologic: cel de suprapunere pentru un model fără hold-out;
    pentru unul antrenat cronologic, constatarea că suprapunerea a fost evitată."""
    g = res["data"].get("holdout_guard")
    if not g:
        return AVERTISMENT
    if not g.get("own"):
        return (AVERTISMENT + f" Setul de test e restrâns la hold-out-ul altui model ({g['excluded_before_holdout']:,} "
                "meciuri mai vechi excluse), doar ca să se compare pe aceleași meciuri; acest model nu a fost "
                "antrenat cronologic față de ele.")
    m = res["model"]["meta"]
    return (
        "**Împărțire cronologică respectată — testul e pe meciuri nevăzute.** Modelul s-a antrenat pe "
        f"meciuri până la {m.get('train_end_time')} UTC, iar testul folosește doar meciuri de la "
        f"{datetime.fromtimestamp(g['holdout_start_ts'], timezone.utc):%Y-%m-%d %H:%M} UTC încolo "
        f"({g['excluded_before_holdout']:,} meciuri mai vechi au fost excluse, fiindcă ar fi putut "
        "fi în antrenare). Regularizarea s-a ales pe o împărțire cronologică internă a antrenării, deci "
        "hold-out-ul nu a influențat nicio alegere. Rezultatele NU sunt umflate de suprapunere; limita "
        "rămasă e că antrenarea și testul vin din aceeași zi (vezi „Fereastră îngustă”).")


def section_model(res: dict) -> str:
    m, d = res["model"]["meta"], res["data"]
    if is_raw_model(res):
        model_lines = [
            f"- **Model:** meciuri brute OpenDota (`publicmatches`), tranșa `{m.get('bracket')}`, "
            f"{int(m.get('matches', 0)):,} meciuri de antrenare ({m.get('train_start_time')} → "
            f"{m.get('train_end_time')} UTC), construit {m.get('fetched')}",
            f"- **Hold-out cronologic:** {int(m.get('matches_holdout', 0)):,} meciuri nevăzute, de la "
            f"{m.get('holdout_start_time')} UTC; tăiere după match_id {m.get('train_cut_match_id')}",
            f"- **Regularizare** ({m.get('regularization_chosen_by')}): `l2_C` = {m.get('l2_C')}, "
            f"`k_counter` = {m.get('k_counter')}, `k_synergy` = {m.get('k_synergy')}",
            f"- **Avantaj de partidă estimat:** {res['model'].get('side_advantage', 0):+.4f} log-odds "
            f"(Radiant {1 / (1 + math.exp(-res['model'].get('side_advantage', 0))):.1%} la egalitate); "
            "se adaugă doar la predicția meciurilor reale, nu în `score()`",
            f"- **Verificare nivel-de-erou:** corelația dintre sumele pe rânduri și β: counter "
            f"{m.get('counter_beta_corr')} (înainte de centrare {m.get('counter_beta_corr_raw')}), "
            f"synergy {m.get('synergy_beta_corr')} (înainte {m.get('synergy_beta_corr_raw')})",
        ]
    else:
        model_lines = [
            f"- **Model:** sursa `{m.get('source')}`, tranșa `{m.get('bracket')}`, "
            f"{int(m.get('matches', 0)):,} apariții de eroi în date, colectat {m.get('fetched')}",
            f"- **Regularizare:** `k_beta` = {m.get('k_beta')}, `k_counter` = {m.get('k_counter')}; "
            f"sinergie: {m.get('synergy', '—')}",
        ]
    lines = [
        "## Ce a fost testat", "",
        *model_lines,
        f"- **Meciuri de test:** {d['n_test']:,} ({'doar ranked, lobby_type 7' if d['subset'] == 'ranked' else 'toate modurile'}), "
        f"din intervalul {d['start']} → {d['end']} UTC",
        f"- **Filtrare:** {d['loaded']:,} încărcate · {d['unknown_hero_skipped']:,} sărite pentru eroi "
        f"absenți din catalog · {d['excluded_by_subset']:,} excluse de filtrul de mod"
        + (f" · {d['holdout_guard']['excluded_before_holdout']:,} excluse (anterioare hold-out-ului)"
           if d.get("holdout_guard") else ""),
    ]
    return "\n".join(lines)


def section_metrics(res: dict) -> str:
    m = res["metrics"]
    lo, hi = m["model"]["auc_ci"]
    rows = []
    for key, label in (("model", "**model**"), ("const_0.5", "constant 0.5"),
                       ("radiant_rate", f"avantaj Radiant (constant {res['radiant_rate']:.3f})")):
        s = m[key]
        rows.append([label, f"{s['logloss']:.4f}", f"{s['brier']:.4f}",
                     f"{s['auc']:.3f}", f"{s['accuracy']:.3f}"])
    drows = []
    for key, label in (("vs_const_0.5", "constant 0.5"), ("vs_radiant_rate", "avantaj Radiant")):
        a, b = res["deltas"][key]["logloss"], res["deltas"][key]["brier"]
        verdict_txt = ("modelul e mai bun" if a["hi"] < 0
                       else "modelul e mai slab" if a["lo"] > 0 else "în limita zgomotului")
        drows.append([f"vs {label}", f"{a['mean']:+.5f} {ci(a['lo'], a['hi'], 5)}",
                      f"{b['mean']:+.5f} {ci(b['lo'], b['hi'], 5)}", verdict_txt])
    return "\n".join([
        "## Metrici, cu bazele de comparație", "",
        table(["", "log-loss ↓", "Brier ↓", "AUC ↑", "acuratețe ↑"], rows), "",
        f"AUC-ul modelului, interval 95% (bootstrap): {ci(lo, hi)} — {auc_reading(lo, hi)}. "
        "Bazele constante au AUC 0.5 prin construcție; acuratețea unei predicții de exact 0.5 "
        "primește credit 1/2 (nu alege nicio echipă).", "",
        "Diferențele de pierdere se calculează pe aceleași meciuri (perechi), deci intervalul "
        "este mult mai strâns decât la două medii comparate separat; **negativ = modelul e mai bun**.", "",
        table(["diferență medie", "log-loss", "Brier", "concluzie"], drows),
    ])


def section_components(res: dict) -> str:
    comp = res.get("components")
    if not comp:
        return ""
    rows = [[r["name"], f"{r['auc']:.3f}", ci(*r["auc_ci"]), f"{r['logloss']:.4f}", f"{r['std']:.3f}"]
            for r in comp["rows"]]
    diag_note = (" Ultimele două rânduri sunt **diagnostic**, evaluate pe același set de test — arată "
                 "unde e problema, nu sunt un model nou validat."
                 if any("(diagnostic)" in r["name"] for r in comp["rows"]) else "")
    out = ["## Pe componente: unde greșește", "",
           "Scorul modelului este o sumă de termeni, deci fiecare se poate evalua singur: dacă modelul "
           "complet e prost dar un termen singur e bun, vinovatul e alt termen." + diag_note, "",
           table(["componentă", "AUC", "AUC interval 95%", "log-loss", "abatere std a scorului"], rows)]
    if not comp["reproduces"]:
        out += ["", "> ⚠ Descompunerea pe componente NU reproduce predicțiile modelului "
                "(`DraftModel.score` s-a schimbat?); rândurile de mai sus nu sunt de încredere."]
    return "\n".join(out)


def section_calibration(res: dict) -> str:
    c = res["calibration"]
    rows = []
    for r in c["table"]:
        off = abs(r["actual"] - r["mean_pred"]) > r["ci"]
        diff = f"{100 * (r['actual'] - r['mean_pred']):+.1f} pp"
        rows.append([f"{pct(r['lo'])} – {pct(r['hi'])}", pct(r["mean_pred"]),
                     f"{pct(r['actual'])} ± {100 * r['ci']:.1f}", f"{r['n']:,}",
                     f"**{diff}**" if off else diff])
    return "\n".join([
        "## Calibrare", "",
        "Intervale cu același număr de meciuri (decile după predicție): un model regularizat "
        "dă predicții strânse în jurul lui 50%, deci intervale de lățime egală ar rămâne "
        "aproape toate goale. Diferențele **îngroșate** depășesc eroarea de eșantionare a "
        "ratei reale.", "",
        table(["interval de predicție", "predicție medie", "rată reală (±95%)", "meciuri",
               "real − predicție"], rows), "",
        f"Regresie de recalibrare y ~ σ(a + b·logit p): **b (pantă) = {c['slope']:.2f}** "
        f"{ci(*c['slope_ci'], d=2)}, **a (intercept) = {c['intercept']:+.3f}** "
        f"{ci(*c['intercept_ci'], d=3)}. Panta ideală este 1, interceptul ideal 0.",
    ])


def section_ranks(res: dict) -> str:
    rows = []
    for r in res["by_rank"]:
        mark = " ◀ antrenare" if r["in_bracket"] else ""
        rows.append([f"{r['name']}{mark}", f"{r['n']:,}", f"{r['logloss']:.4f}",
                     f"{r['logloss'] - r['logloss_const']:+.4f}", f"{r['auc']:.3f}",
                     f"{r['accuracy']:.3f}"])
    out = ["## Pe tranșe de rang", "",
           "Modelul e construit pe tranșa marcată ◀ și ar trebui să meargă mai bine acolo. "
           "„Δ vs 0.5” este log-loss minus ln 2 (negativ = mai bun decât moneda).", "",
           table(["tranșă", "meciuri", "log-loss", "Δ vs 0.5", "AUC", "acuratețe"], rows)]
    iv = res.get("in_vs_out")
    if iv:
        i, o = iv["in"], iv["out"]
        out += ["", table(
            ["grup", "meciuri", "log-loss", "AUC", "AUC interval 95%"],
            [["pe tranșa de antrenare", f"{i['n']:,}", f"{i['logloss']:.4f}", f"{i['auc']:.3f}", ci(*i["auc_ci"])],
             ["în afara ei", f"{o['n']:,}", f"{o['logloss']:.4f}", f"{o['auc']:.3f}", ci(*o["auc_ci"])]])]
    return "\n".join(out)


def section_modes(res: dict) -> str:
    if not res.get("by_mode"):
        return ""
    rows = [[r["name"], f"{r['n']:,}", f"{r['logloss']:.4f}",
             f"{r['logloss'] - r['logloss_const']:+.4f}", f"{r['auc']:.3f}"] for r in res["by_mode"]]
    return "\n".join([
        "## Pe moduri de joc", "",
        "Toate meciurile încărcate, nu doar setul de test principal. Modelul vine din statistici "
        "de meciuri ranked, deci pe celelalte moduri (Turbo, boți) este în afara domeniului "
        "pentru care a fost construit; nu e un defect, dar arată cât se transferă.", "",
        table(["lobby / mod", "meciuri", "log-loss", "Δ vs 0.5", "AUC"], rows)])


# ---------------------------------------------------------------- interpretare

def reg_knobs(meta: dict) -> str:
    """Parametrii de regularizare ai modelului și unde se reglează."""
    if meta.get("source") == "publicmatches":
        return "`l2_C` / `k_counter` / `k_synergy` (`autodrafter/etl/build_model.py`, opțiunile --c, --k-counter, --k-synergy)"
    return "`k_beta` / `k_counter` (`autodrafter/etl/fetch_opendota.py`)"


def reg_now(meta: dict) -> str:
    if meta.get("source") == "publicmatches":
        return f"acum l2_C = {meta.get('l2_C')}, k_counter = {meta.get('k_counter')}, k_synergy = {meta.get('k_synergy')}"
    return f"acum k_beta = {meta.get('k_beta')}, k_counter = {meta.get('k_counter')}"


def what_to_fix(res: dict) -> str:
    d, c, m = res["data"], res["calibration"], res["model"]["meta"]
    mt, dr = res["metrics"], res["deltas"]
    n = d["n_test"]
    s, s_lo, s_hi = c["slope"], *c["slope_ci"]
    a, a_lo, a_hi = c["intercept"], *c["intercept_ci"]
    auc_lo, auc_hi = mt["model"]["auc_ci"]
    rr = res["radiant_rate"]
    ll, ll_rec = mt["model"]["logloss"], c["logloss_recalibrated"]
    ll_r = mt["radiant_rate"]["logloss"]
    items: list[str] = []

    # 0. cauza rădăcină, dacă descompunerea pe componente o arată
    comp = res.get("components")
    if comp:
        rows = {r["name"]: r for r in comp["rows"]}
        b, k = rows["β — puterea eroilor"], rows["counter"]
        full = next(r for r in comp["rows"] if r["name"].startswith("modelul complet"))
        cent = rows.get("β + counter centrat (diagnostic)")
        if k["auc_ci"][1] < 0.5 and b["auc_ci"][0] > 0.5:
            if is_raw_model(res):
                cause = ("Modelul acesta vine din meciuri brute, cu counter centrat, deci defectul vechi "
                         "(surse diferite) nu explică asta: verifică regularizarea counter-ului și "
                         "dacă hold-out-ul e comparabil cu antrenarea.")
                fix_tail = ""
            else:
                cause = ("Cauza probabilă: în `autodrafter/etl/fetch_opendota.py` counter-ul se calculează ca "
                         "reziduu față de β din `heroStats` (tranșa aleasă), dar din tabelul `/matchups` — alt "
                         "set de meciuri și altă fereastră — iar reziduul absoarbe diferența dintre cele două surse.")
                fix_tail = (" → derivă β și counter din aceeași sursă (`fetch_publicmatches.py` + "
                            "`build_model.py`) și centrează counter-ul (fără componenta de erou).")
            fix = ""
            if cent:
                fix = (f" Diagnostic: scoțând din counter componenta de erou, AUC urcă de la {full['auc']:.3f} "
                       f"la {cent['auc']:.3f} și log-loss de la {full['logloss']:.4f} la {cent['logloss']:.4f}, dar "
                       f"rămâne {'sub' if cent['auc'] < b['auc'] else 'lângă'} β singur ({b['auc']:.3f}, "
                       f"log-loss {b['logloss']:.4f}): interacțiunile pereche-pereche din `/matchups` nu adaugă "
                       "semnal măsurabil. (Varianta centrată a fost evaluată pe acest set; confirm-o pe meciuri "
                       "dintr-o fereastră separată înainte de a o adopta.)")
            items.append(
                f"**Termenul counter strică modelul.** β singur are AUC {b['auc']:.3f} {ci(*b['auc_ci'])}, dar counter "
                f"singur are AUC {k['auc']:.3f} {ci(*k['auc_ci'])} — SUB 0.5, semnificativ: e anti-predictiv. Scorul lui "
                f"are abatere std {k['std']:.2f} față de {b['std']:.2f} la β, deci îl domină pe β: modelul complet "
                f"ajunge la AUC {full['auc']:.3f}. Sumele pe rânduri ale matricei counter au abatere std "
                f"{comp['counter_row_sum_std']:.2f} și corelează {comp['counter_vs_beta_corr']:+.2f} cu β: counter-ul "
                "conține o componentă de nivel de erou, deși ar trebui să conțină doar interacțiuni "
                "pereche-pereche. " + cause + fix + fix_tail)
        elif full["auc_ci"][1] < b["auc_ci"][0]:
            items.append(
                f"**Modelul complet e mai slab decât β singur** (AUC {full['auc']:.3f} față de {b['auc']:.3f}): "
                "termenii adăugați peste β introduc zgomot mai mult decât semnal.")
        if not comp["reproduces"]:
            items.append("**Atenție:** descompunerea pe componente nu reproduce predicțiile modelului; "
                         "`DraftModel.score` pare să fi primit termeni noi pe care banca nu îi cunoaște.")

    # 1. semnal vs scară: decide dacă restul are sens
    if auc_hi < 0.5:
        items.append(
            f"**Semnal inversat.** AUC {mt['model']['auc']:.3f} {ci(auc_lo, auc_hi)} este sub 0.5: predicțiile sunt, "
            "în medie, anti-corelate cu rezultatul — mai rău decât o monedă, nu doar zgomot. Reglarea lui "
            f"regularizarea ({reg_knobs(m)}) nu poate repara un semn greșit.")
    elif auc_lo <= 0.5:
        items.append(
            f"**Modelul nu discriminează.** AUC {mt['model']['auc']:.3f} {ci(auc_lo, auc_hi)} include 0.5: "
            "predicțiile lui nu se disting de zgomot. Aici nu e o problemă de calibrare, deci "
            f"reglarea regularizării ({reg_knobs(m)}) nu o rezolvă; lipsește semnal (jucători, "
            "un model mai bogat în `model.py`) sau datele de antrenare nu se potrivesc cu testul.")
    else:
        items.append(
            f"**Discriminare.** AUC {mt['model']['auc']:.3f} {ci(auc_lo, auc_hi)} — {auc_reading(auc_lo, auc_hi)}.")

    # 2. încredere / regularizare
    if s_hi < 0:
        items.append(
            f"**Panta de calibrare este negativă ({s:.2f}) {ci(s_lo, s_hi, 2)}:** o predicție mai încrezută înseamnă, "
            "în medie, un rezultat mai puțin probabil. Nu e o problemă de scară (regularizarea nu o repară), ci de semn.")
    elif s_lo <= 0 <= s_hi:
        items.append(
            f"**Panta de calibrare ({s:.2f}) nu se distinge de 0** {ci(s_lo, s_hi, 2)}: scorul modelului "
            "nu prezice nimic peste zgomot, oricât l-ai scala. Regularizarea nu este problema.")
    elif s_hi < 1:
        top, bot = c["table"][-1], c["table"][0]
        items.append(
            f"**Predicții sistematic prea încrezute → regularizarea e prea slabă.** Panta este {s:.2f} "
            f"{ci(s_lo, s_hi, 2)} (ideal 1): scorul ar trebui înmulțit cu ≈{max(s, 0):.2f} ca să fie calibrat. "
            f"Exemplu: pe cele mai optimiste 10% predicții pentru Radiant, modelul spune "
            f"{pct(top['mean_pred'])}, real {pct(top['actual'])}; pe cele mai pesimiste, "
            f"{pct(bot['mean_pred'])} față de {pct(bot['actual'])}. → întărește regularizarea: "
            f"{reg_knobs(m)} ({reg_now(m)}); reface `data/model.npz`, apoi verifică "
            "din nou aici că panta se apropie de 1.")
    elif s_lo > 1:
        items.append(
            f"**Predicții prea timide → regularizarea e prea puternică.** Panta este {s:.2f} "
            f"{ci(s_lo, s_hi, 2)} (ideal 1). → slăbește regularizarea: {reg_knobs(m)} ({reg_now(m)}).")
    else:
        items.append(
            f"**Încrederea este compatibilă cu realitatea:** panta {s:.2f} {ci(s_lo, s_hi, 2)} include 1, "
            f"deci regularizarea ({reg_now(m)}) nu are un semn clar de reglat pe baza acestui set.")

    # 3. cât se poate câștiga doar din scară + partidă
    # Interceptul singur recuperează avantajul Radiant (baza constantă). Ce contează
    # pentru model e cât adaugă scorul LUI peste asta, adică ll_r − ll_rec.
    gain_signal = ll_r - ll_rec
    if s_lo > 0 and ll - ll_rec < 0.002:
        concl = (f"Recalibrarea nu aduce nimic material ({ll - ll_rec:.4f}): modelul e deja calibrat. "
                 f"Peste simpla cunoaștere a părții, scorul lui adaugă ≈{gain_signal:.4f} log-loss.")
    elif s_lo > 0 and gain_signal > 0:
        concl = (f"Peste simpla cunoaștere a părții, scorul modelului adaugă ≈{gain_signal:.4f} log-loss: "
                 "există semnal, iar scara lui este reparabilă din regularizare.")
    else:
        concl = (f"Peste simpla cunoaștere a părții, scorul modelului nu adaugă nimic demonstrabil "
                 f"({gain_signal:+.4f}): problema este de semnal, nu de scară, iar regularizarea "
                 "singură nu o repară.")
    items.append(
        f"**Ce ar câștiga o recalibrare.** Cu doi parametri reglați pe acest set (a, b) log-loss ar "
        f"coborî de la {ll:.4f} la {ll_rec:.4f} (constant 0.5: {LN2:.4f}; avantaj Radiant: {ll_r:.4f}). "
        f"{concl} Cifrele sunt calculate pe aceleași date pe care se reglează, deci sunt un plafon optimist.")

    # 4. avantajul de partidă
    side = res["model"].get("side_advantage", 0.0)
    if side:
        fits = a_lo <= 0 <= a_hi
        items.append(
            f"**Avantajul de partidă.** Modelul îl estimează la {side:+.3f} log-odds (Radiant "
            f"{pct(1 / (1 + math.exp(-side)))} la egalitate); pe setul de test Radiant câștigă {pct(rr)}. Interceptul "
            f"de calibrare rămas este {a:+.3f} {ci(a_lo, a_hi)}: "
            + ("compatibil cu 0, deci avantajul estimat se potrivește cu cel observat." if fits else
               "exclude 0, deci avantajul estimat la antrenare nu se potrivește cu cel din meciurile de test "
               "(se poate schimba între zile sau patch-uri)."))
    elif a_lo > 0 or a_hi < 0:
        items.append(
            f"**Lipsește avantajul de partidă.** Radiant câștigă {pct(rr)} din meciurile de test, iar "
            f"modelul nu are niciun termen pentru asta (interceptul {a:+.3f} {ci(a_lo, a_hi)} exclude 0). "
            "Un termen constant „partea” în `score()` (în `model.py`, nu în `search/`) ar corecta "
            "părtinirea; valoarea lui trebuie estimată din meciuri, nu aleasă de mână.")
    else:
        items.append(
            f"**Avantajul de partidă** (Radiant {pct(rr)}) nu se distinge clar de 50% pe acest set "
            f"(intercept {a:+.3f} {ci(a_lo, a_hi)}), deci lipsa lui din model nu costă demonstrabil.")

    # 5. rang
    iv = res.get("in_vs_out")
    if iv:
        i, o = iv["in"], iv["out"]
        d_auc, d_ll = i["auc"] - o["auc"], i["logloss"] - o["logloss"]
        overlap = not (i["auc_ci"][0] > o["auc_ci"][1] or o["auc_ci"][0] > i["auc_ci"][1])
        if overlap:
            txt = ("Intervalele AUC se suprapun, deci diferența dintre tranșe este în limita "
                   "zgomotului; cu atât de puține meciuri pe tranșa de antrenare "
                   f"({i['n']:,}) nu se poate spune dacă modelul chiar merge mai bine acolo.")
        elif d_auc > 0:
            txt = "Diferența e semnificativă și în sensul așteptat: modelul e mai bun acolo unde a fost construit."
        else:
            txt = ("Diferența e semnificativă, dar în sens INVERS față de așteptat — un semn că "
                   "ceva nu se potrivește (date, tranșă sau potrivirea ID-urilor de eroi).")
        items.append(
            f"**Tranșa de antrenare vs restul.** AUC {i['auc']:.3f} (n={i['n']:,}) pe tranșa de antrenare față de "
            f"{o['auc']:.3f} (n={o['n']:,}) în afara ei: ΔAUC = {d_auc:+.3f}, Δlog-loss = {d_ll:+.4f}. {txt}")

    # 6. modurile de joc
    other = [r for r in res.get("by_mode", []) if r.get("lobby_type") != 7]
    if other and res["data"]["subset"] == "ranked":
        worst = min(other, key=lambda r: r["auc"])
        items.append(
            f"**Alte moduri.** Pe {worst['name']} (n={worst['n']:,}) AUC este {worst['auc']:.3f}: statisticile "
            "de rang nu se transferă în afara meciurilor ranked, ceea ce era de așteptat.")

    # 7. eșantion & catalog
    if n < 3000:
        items.append(
            f"**Eșantion mic.** Cu {n:,} meciuri, un AUC are o eroare de ordinul ±"
            f"{(auc_hi - auc_lo) / 2:.3f}: un semnal slab nu se poate confirma. Mărește `--count` la "
            "`benchmark.fetch_matches` (reluabil) sau adaugă `--min-rank 60` ca să obții mai multe "
            "meciuri din tranșa modelului.")
    skipped_frac = d["unknown_hero_skipped"] / max(1, d["in_window"])
    if skipped_frac > 0.05:
        ids = ", ".join(str(k) for k in d["missing_hero_ids"])
        items.append(
            f"**Catalog posibil învechit.** {pct(skipped_frac)} din meciuri au fost sărite pentru eroi absenți "
            f"din `data/heroes.json` (id-uri: {ids}). Testul e făcut doar pe meciurile fără acești eroi, deci poate "
            "fi părtinit; actualizează catalogul și modelul.")

    return "## Ce e de reparat\n\n" + "\n\n".join(f"{i}. {t}" for i, t in enumerate(items, 1))


# ---------------------------------------------------------------- comparație

def compare(cur: dict, prev: dict, prev_name: str) -> str:
    def val(r, key):
        if key == "slope":
            return r["calibration"]["slope"]
        return r["metrics"]["model"][key]

    better_if_lower = {"logloss", "brier"}
    rows = []
    for key, label in (("logloss", "log-loss"), ("brier", "Brier"), ("auc", "AUC"),
                       ("accuracy", "acuratețe"), ("slope", "panta de calibrare")):
        a, b = val(cur, key), val(prev, key)
        delta = a - b
        if abs(delta) < NOISE[key]:
            what = "neschimbat"
        elif key == "slope":
            what = "mai bine" if abs(a - 1) < abs(b - 1) else "mai rău"
        elif key in better_if_lower:
            what = "mai bine" if delta < 0 else "mai rău"
        else:
            what = "mai bine" if delta > 0 else "mai rău"
        rows.append([label, f"{b:.4f}", f"{a:.4f}", f"{delta:+.4f}", what])

    notes = []
    dc, dp = cur["data"], prev["data"]
    if (dc["n_test"], dc["start"], dc["end"]) != (dp["n_test"], dp["start"], dp["end"]):
        notes.append("Seturile de test **diferă** "
                     f"({dp['n_test']:,} meciuri {dp['start']}→{dp['end']} față de "
                     f"{dc['n_test']:,} meciuri {dc['start']}→{dc['end']}): diferențele de mai sus "
                     "amestecă efectul modificării cu cel al datelor. Pentru o comparație curată "
                     "rulează ambele modele pe același set.")
    mc, mp = cur["model"]["meta"], prev["model"]["meta"]
    changed = [f"`{k}`: {mp.get(k)} → {mc.get(k)}" for k in ("source", "bracket", "min_rank", "matches", "l2_C", "k_beta", "k_counter", "k_synergy", "fetched")
               if mp.get(k) != mc.get(k)]
    notes.append("Modelul s-a schimbat: " + "; ".join(changed) + "." if changed
                 else "Metadatele modelului sunt identice cu cele din rularea anterioară.")
    return "\n".join([f"## Comparație cu rularea anterioară (`{prev_name}`)", "",
                      table(["metrică (model)", "înainte", "acum", "Δ", "sens"], rows), "",
                      *notes, "",
                      "Praguri sub care o diferență se numește „neschimbat”: " +
                      ", ".join(f"{k} {v}" for k, v in NOISE.items()) + "."])


def window_hours(res: dict) -> float:
    """Durata ferestrei de timp acoperite de meciurile de test, în ore."""
    fmt = "%Y-%m-%d %H:%M"
    d = res["data"]
    return (datetime.strptime(d["end"], fmt) - datetime.strptime(d["start"], fmt)).total_seconds() / 3600


def limits(res: dict) -> str:
    narrow = []
    hours = window_hours(res)
    if hours < 24:
        narrow = [
            f"- **Fereastră îngustă:** meciurile de test acoperă doar {hours:.1f} ore "
            f"({res['data']['start']} → {res['data']['end']} UTC): `publicMatches` întoarce mereu cele mai "
            "recente meciuri. Setul e sensibil la ora din zi și la mixul de regiuni, deci un rezultat de aici "
            "nu spune ce se întâmplă în alte zile. Pentru alte perioade e nevoie de un `less_than_match_id` "
            "ales manual, pe care banca nu îl expune încă."]
    if own_holdout(res):
        training = ("- Antrenarea (`etl/build_model.py`) folosește cele mai vechi 80% din meciuri după "
                    "`start_time`; parametrii de regularizare s-au ales pe o împărțire cronologică internă a "
                    "acestor 80%. Benchmark-ul exclude orice meci mai vechi decât începutul hold-out-ului, chiar "
                    "dacă e încărcat dintr-un alt director.")
    else:
        training = ("- Nu s-a făcut antrenare aici: modelul din `data/model.npz` e folosit ca atare. Dacă se "
                    "adaugă antrenare, împărțirea trebuie să fie **cronologică** (`--since`/`--until`), nu "
                    "aleatoare: meta se schimbă în timp și o împărțire aleatoare lasă viitorul să „scape” "
                    "în antrenare.")
    return "\n".join([
        "## Metodologie și limite", "",
        *narrow,
        training,
        "- Baza „avantaj Radiant” folosește rata reală din chiar setul de test (constantă, calculată "
        "pe aceleași date), deci e ușor favorizată; a o bate contează.",
        "- Setul principal conține doar meciuri ranked (`lobby_type` 7): singurele comparabile cu "
        "statisticile pe rang din care vine modelul.",
        "- Intervalele sunt bootstrap percentilă 95% cu sămânță fixă (reproductibile); cele pentru "
        "diferențele de pierdere sunt aproximări normale pe perechi de meciuri.",
    ])


# ---------------------------------------------------------------- asamblare

def build_report(res: dict, prev: dict | None = None, prev_name: str = "") -> str:
    code, sentence = verdict(res)
    parts = [
        "# Raport de evaluare a modelului", "",
        f"_Generat {res['created']} din rezultatele `{res.get('_name', '')}`._", "",
        f"**Verdict.** {sentence}", "",
        f"> {overlap_note(res)}", "",
        section_model(res), "",
        section_metrics(res), "",
        section_components(res), "",
        section_calibration(res), "",
        section_ranks(res), "",
    ]
    modes = section_modes(res)
    if modes:
        parts += [modes, ""]
    parts += [what_to_fix(res), ""]
    if prev is not None:
        parts += [compare(res, prev, prev_name), ""]
    else:
        parts += ["## Comparație cu rularea anterioară", "",
                  "Nu există o rulare anterioară în `benchmark/results/`; comparația apare de la "
                  "a doua evaluare.", ""]
    parts.append(limits(res))
    return "\n".join(parts) + "\n"


def find_results(results_dir: Path, current: Path | None) -> tuple[Path, Path | None]:
    files = sorted(results_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"nu există rezultate în {results_dir}; rulează `python -m benchmark.evaluate`")
    cur = current or files[-1]
    older = [f for f in files if f.name < cur.name]
    return cur, (older[-1] if older else None)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):               # consola Windows e cp1251
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--result", type=Path, default=None, help="fișierul JSON de raportat (implicit: ultimul)")
    ap.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    a = ap.parse_args()
    try:
        cur, prev = find_results(a.results_dir, a.result)
    except FileNotFoundError as exc:
        sys.exit(str(exc))
    res = json.loads(cur.read_text(encoding="utf-8"))
    res["_name"] = cur.name
    prev_res = json.loads(prev.read_text(encoding="utf-8")) if prev else None
    text = build_report(res, prev_res, prev.name if prev else "")
    out = cur.with_suffix(".md")
    out.write_text(text, encoding="utf-8")
    print(f"Scris {out}\n")
    print(text.split("\n\n", 3)[2])                     # verdictul, direct în terminal


if __name__ == "__main__":
    main()
