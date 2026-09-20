"""Pune modelul să prezică fiecare meci real și măsoară cât de bine a nimerit.

    python -m benchmark.evaluate
    python -m benchmark.evaluate --subset all --since 2026-09-01

Nu antrenează nimic: modelul din data/model.npz e folosit așa cum e. Dacă vreodată
se adaugă antrenare, împărțirea train/test trebuie făcută CRONOLOGIC (`--since` și
`--until` există tocmai pentru asta), nu aleator: meta se schimbă în timp, iar o
împărțire aleatoare lasă viitorul să „scape" în antrenare.

Rezultatul se scrie în benchmark/results/<timestamp>.json; `benchmark.report`
îl transformă în raport.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from autodrafter.etl.fetch_opendota import BRACKETS
from autodrafter.heroes import load_catalog
from autodrafter.etl.fetch_publicmatches import RAW_DIR
from autodrafter.model import DraftModel, default_model_path, sigmoid
from benchmark import metrics as M
from benchmark.fetch_matches import DEFAULT_OUT, load_matches

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RANKED_LOBBY = 7            # lobby_type al meciurilor ranked (matchmaking)
MIN_GROUP = 100             # sub atâtea meciuri, un grup de moduri nu se raportează

RANK_NAMES = {1: "Herald", 2: "Guardian", 3: "Crusader", 4: "Archon",
              5: "Legend", 6: "Ancient", 7: "Divine", 8: "Immortal"}
LOBBY_NAMES = {0: "public", 1: "practice", 2: "turneu", 4: "co-op boți", 7: "ranked"}
MODE_NAMES = {1: "All Pick", 2: "Captains Mode", 3: "Random Draft", 4: "Single Draft",
              5: "All Random", 16: "Captains Draft", 18: "Ability Draft",
              21: "1v1 Mid", 22: "All Draft", 23: "Turbo"}


# ---------------------------------------------------------------- predicție

def predict(model: DraftModel, catalog, matches: list[dict]):
    """P(Radiant câștigă) pentru fiecare meci.

    Meciurile cu cel puțin un erou absent din catalog se sar (modelul nu are
    indice pentru ei) și se numără; id-urile lipsă se întorc ca să se vadă dacă
    catalogul e învechit. Întoarce (meciuri_păstrate, y, p, Counter_id_lipsă,
    nr_meciuri_sărite).
    """
    kept, y, p = [], [], []
    missing: Counter = Counter()
    skipped = 0
    for m in matches:
        ids = m["radiant"] + m["dire"]
        absent = [h for h in ids if h not in catalog.by_id]
        if absent:
            skipped += 1
            missing.update(absent)
            continue
        rad = tuple(catalog.by_id[h].idx for h in m["radiant"])
        dire = tuple(catalog.by_id[h].idx for h in m["dire"])
        kept.append(m)
        y.append(1.0 if m["radiant_win"] else 0.0)
        # avantajul de partidă se adaugă AICI, la predicția meciurilor reale, și nu în
        # DraftModel.score(): o constantă nu schimbă niciun argmax de draft (vezi model.py)
        p.append(float(sigmoid(model.score(rad, dire) + model.side_advantage)))
    return kept, np.asarray(y), np.asarray(p), missing, skipped


def rank_decade(m: dict) -> int | None:
    """avg_rank_tier = 10·rang + stea (ex. 44 = Archon, 4 stele) -> rang 1..8."""
    t = m.get("avg_rank_tier")
    return int(t) // 10 if t else None


def train_ranks(meta: dict) -> set[int]:
    """Rangurile pe care a fost construit modelul: `min_rank` (modelul din meciuri
    brute) sau coloanele heroStats ale tranșei (modelul vechi)."""
    if meta.get("min_rank"):
        return set(range(int(meta["min_rank"]) // 10, 9))
    cols = BRACKETS.get(meta.get("bracket"), [])
    return {int(c) for c in cols if str(c).isdigit()}


# ---------------------------------------------------------------- analiză

def analyze(y: np.ndarray, p: np.ndarray, B: int = 300) -> dict:
    """Modelul și cele două baze de comparație pe același set, cu intervale."""
    r = float(y.mean())                                  # rata reală a lui Radiant
    half, rad = np.full_like(p, 0.5), np.full_like(p, r)

    model = M.summarize(y, p)
    model["auc_ci"] = M.bootstrap_ci(M.auc, y, p, B)
    bases = {"const_0.5": M.summarize(y, half), "radiant_rate": M.summarize(y, rad)}

    l_m, l_h, l_r = (M.loss_logloss(y, q) for q in (p, half, rad))
    b_m, b_h, b_r = (M.loss_brier(y, q) for q in (p, half, rad))
    deltas = {
        "vs_const_0.5": {"logloss": M.paired_delta(l_m, l_h), "brier": M.paired_delta(b_m, b_h)},
        "vs_radiant_rate": {"logloss": M.paired_delta(l_m, l_r), "brier": M.paired_delta(b_m, b_r)},
    }

    fit = M.calibration_fit(y, p)
    (s_lo, s_hi), (i_lo, i_hi) = M.bootstrap_ci_multi(
        lambda yy, pp: tuple(M.calibration_fit(yy, pp)[k] for k in ("slope", "intercept")),
        y, p, B)
    fit.update(slope_ci=[s_lo, s_hi], intercept_ci=[i_lo, i_hi])

    return {"radiant_rate": r,
            "metrics": {"model": model, **bases},
            "deltas": deltas,
            "calibration": {"table": M.calibration_table(y, p), **fit}}


def group_row(y: np.ndarray, p: np.ndarray) -> dict:
    row = M.summarize(y, p)
    row["logloss_const"] = float(np.log(2.0))
    return row


def by_rank(matches, y, p, trained: set[int]) -> list[dict]:
    dec = np.array([rank_decade(m) or 0 for m in matches])
    rows = []
    for d in sorted(set(dec.tolist())):
        mask = dec == d
        row = group_row(y[mask], p[mask])
        row.update(rank=d, name=RANK_NAMES.get(d, "necunoscut"), in_bracket=d in trained)
        rows.append(row)
    return rows


def in_vs_out(matches, y, p, trained: set[int], B: int) -> dict | None:
    """Modelul pe rangurile pe care a fost construit vs celelalte."""
    dec = np.array([rank_decade(m) or 0 for m in matches])
    inside = np.isin(dec, list(trained))
    if not trained or inside.all() or not inside.any():
        return None
    out = {}
    for name, mask in (("in", inside), ("out", ~inside)):
        g = group_row(y[mask], p[mask])
        g["auc_ci"] = M.bootstrap_ci(M.auc, y[mask], p[mask], B)
        out[name] = g
    return out


def by_mode(matches, y, p) -> list[dict]:
    keys = [(m.get("lobby_type"), m.get("game_mode")) for m in matches]
    rows = []
    for key, n in Counter(keys).most_common():
        if n < MIN_GROUP:
            continue
        mask = np.array([k == key for k in keys])
        row = group_row(y[mask], p[mask])
        row.update(lobby_type=key[0], game_mode=key[1],
                   name=f"{LOBBY_NAMES.get(key[0], key[0])} / {MODE_NAMES.get(key[1], key[1])}")
        rows.append(row)
    return rows


def component_table(model: DraftModel, catalog, test: list[dict], y: np.ndarray,
                    p_model: np.ndarray, B: int = 300) -> dict:
    """Descompune scorul modelului pe componente și le evaluează pe rând.

    Scorul e o sumă (β + sinergie + counter), deci fiecare termen se poate
    testa singur: dacă modelul complet e prost dar β singur e bun, vinovatul e
    un alt termen. Se folosesc doar tablourile modelului; `model.py` nu se atinge.

    Ultimele două rânduri sunt DIAGNOSTIC, nu un model nou: counter-ul din care s-a
    scos componenta de erou (media pe rând), ca să se vadă dacă problema e
    interacțiunea pereche-pereche sau nivelul eroului strecurat în counter. Ele au
    fost evaluate pe același set de test, deci nu se raportează ca îmbunătățire.
    """
    n = model.n
    R = np.array([[catalog.by_id[h].idx for h in m["radiant"]] for m in test])
    D = np.array([[catalog.by_id[h].idx for h in m["dire"]] for m in test])

    def cross(mat):
        return np.array([mat[np.ix_(r, d)].sum() for r, d in zip(R, D)])

    def within(mat, teams):
        return np.array([np.triu(mat[np.ix_(t, t)], 1).sum() for t in teams])

    beta = model.beta[R].sum(1) - model.beta[D].sum(1)
    syn = within(model.synergy, R) - within(model.synergy, D)
    cnt = cross(model.counter)

    hero_level = model.counter.sum(1) / (n - 1)              # componenta de erou din counter
    centred = model.counter - hero_level[:, None] + hero_level[None, :]
    np.fill_diagonal(centred, 0.0)
    cnt_c = cross(centred)

    full = beta + syn + cnt
    variants = [("β — puterea eroilor", beta), ("counter", cnt)]
    if np.any(model.synergy):
        variants.append(("sinergie", syn))
    variants += [("modelul complet (β + counter" + (" + sinergie)" if np.any(model.synergy) else ")"), full)]
    # rândurile de diagnostic au sens doar dacă counter-ul are ceva de scos; un counter deja
    # centrat (modelul din meciuri brute) ar da rânduri identice cu cele de mai sus
    if not np.allclose(model.counter, centred, atol=1e-9):
        variants += [("counter fără componenta de erou (diagnostic)", cnt_c),
                     ("β + counter centrat (diagnostic)", beta + syn + cnt_c)]

    side = model.side_advantage
    rows = []
    for name, s in variants:
        pr = 1.0 / (1.0 + np.exp(-(s + side)))
        rows.append({"name": name, "auc": M.auc(y, s), "auc_ci": M.bootstrap_ci(M.auc, y, s, B),
                     "logloss": M.log_loss(y, pr), "std": float(s.std())})
    # matricele constante (ex. counter = 0) nu au corelație definită
    sums = model.counter.sum(1)
    corr = (float(np.corrcoef(sums, model.beta)[0, 1])
            if n > 2 and sums.std() > 1e-9 and model.beta.std() > 1e-12 else 0.0)
    return {
        "rows": rows,
        # descompunerea trebuie să regăsească exact predicțiile modelului
        "reproduces": bool(np.allclose(1.0 / (1.0 + np.exp(-(full + side))), p_model, atol=1e-9)),
        "counter_row_sum_std": float(model.counter.sum(1).std()),
        "counter_vs_beta_corr": corr,
    }


def iso(ts: int | float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M")


def evaluate(model: DraftModel, catalog, matches: list[dict], subset: str = "ranked",
             since: int | None = None, until: int | None = None, B: int = 300,
             holdout_ts: int | None = None) -> dict:
    """Ansamblul evaluării, ca dicționar serializabil JSON.

    `holdout_ts`: începutul hold-out-ului cronologic al unui model (meta
    `holdout_start_ts`, scris de etl/build_model.py). Orice meci mai vechi se exclude:
    ar putea fi în datele de antrenare, iar a-l testa ar da un rezultat optimist. Dacă nu
    se dă, se ia din meta modelului; un model fără hold-out (cel vechi) nu are garda."""
    loaded = len(matches)
    own_ts = model.meta.get("holdout_start_ts")
    if holdout_ts is None:
        holdout_ts = own_ts
    # „propriu": modelul a fost antrenat cronologic față de acest hold-out. Un hold-out împrumutat
    # (`--holdout-of`) doar aliniază setul de test pentru comparație; nu garantează nimic despre model.
    own = holdout_ts is not None and holdout_ts == own_ts
    before_holdout = 0
    if holdout_ts is not None:
        before_holdout = sum(1 for m in matches if m["start_time"] < holdout_ts)
        matches = [m for m in matches if m["start_time"] >= holdout_ts]
    if since is not None:
        matches = [m for m in matches if m["start_time"] >= since]
    if until is not None:
        matches = [m for m in matches if m["start_time"] < until]
    in_window = len(matches)

    kept, y, p, missing, skipped = predict(model, catalog, matches)

    main_idx = [i for i, m in enumerate(kept)
                if subset == "all" or m.get("lobby_type") == RANKED_LOBBY]
    if len(main_idx) < 30:
        raise ValueError(f"prea puține meciuri de test ({len(main_idx)}) — "
                         f"rulează benchmark.fetch_matches sau folosește --subset all")
    test = [kept[i] for i in main_idx]
    ty, tp = y[main_idx], p[main_idx]
    trained = train_ranks(model.meta)

    result = analyze(ty, tp, B)
    result.update(
        version=1,
        created=time.strftime("%Y-%m-%d %H:%M:%S"),
        model={"meta": model.meta, "n": model.n, "side_advantage": float(model.side_advantage)},
        data={
            "loaded": loaded, "in_window": in_window,
            "unknown_hero_skipped": skipped,
            "missing_hero_ids": dict(missing.most_common(10)),
            "excluded_by_subset": len(kept) - len(test),
            "subset": subset, "n_test": len(test),
            "start": iso(min(m["start_time"] for m in test)),
            "end": iso(max(m["start_time"] for m in test)),
            "since": since, "until": until,
            # meciurile anterioare hold-out-ului sunt excluse: pot fi în antrenare
            "holdout_guard": ({"holdout_start_ts": int(holdout_ts),
                               "excluded_before_holdout": before_holdout, "own": own}
                              if holdout_ts is not None else None),
        },
        train_ranks=sorted(trained),
        components=component_table(model, catalog, test, ty, tp, B),
        by_rank=by_rank(test, ty, tp, trained),
        in_vs_out=in_vs_out(test, ty, tp, trained, B),
        by_mode=by_mode(kept, y, p),
    )
    return result


# ---------------------------------------------------------------- afișare

def summary_text(res: dict) -> str:
    d, m = res["data"], res["metrics"]
    lines = [
        f"Set de test: {d['n_test']:,} meciuri ({d['subset']}), {d['start']} → {d['end']} UTC",
        f"  încărcate {d['loaded']:,} · sărite (erou necunoscut) {d['unknown_hero_skipped']:,} · "
        f"excluse de filtru {d['excluded_by_subset']:,}"
        + (f" · excluse (anterioare hold-out-ului) {d['holdout_guard']['excluded_before_holdout']:,}"
           if d.get("holdout_guard") else ""),
        "",
        f"{'':<24}{'log-loss':>10}{'Brier':>9}{'AUC':>8}{'acuratețe':>11}",
    ]
    for key, label in (("model", "model"), ("const_0.5", "constant 0.5"),
                       ("radiant_rate", f"rata Radiant ({res['radiant_rate']:.3f})")):
        s = m[key]
        lines.append(f"{label:<24}{s['logloss']:>10.4f}{s['brier']:>9.4f}"
                     f"{s['auc']:>8.3f}{s['accuracy']:>11.3f}")
    lo, hi = m["model"]["auc_ci"]
    c = res["calibration"]
    lines += ["", f"AUC model 95%: [{lo:.3f}, {hi:.3f}] · panta de calibrare {c['slope']:.2f} "
                  f"[{c['slope_ci'][0]:.2f}, {c['slope_ci'][1]:.2f}]"]
    for name, key in (("0.5", "vs_const_0.5"), ("rata Radiant", "vs_radiant_rate")):
        dl = res["deltas"][key]["logloss"]
        lines.append(f"Δ log-loss vs {name}: {dl['mean']:+.5f}  [{dl['lo']:+.5f}, {dl['hi']:+.5f}]"
                     "  (negativ = modelul e mai bun)")
    comp = res.get("components")
    if comp:
        lines += ["", "Pe componente (unde greșește):",
                  f"{'':<50}{'AUC':>7}{'log-loss':>10}"]
        for r in comp["rows"]:
            lines.append(f"  {r['name']:<48}{r['auc']:>7.3f}{r['logloss']:>10.4f}")
    return "\n".join(lines)


def _date_to_ts(s: str | None) -> int | None:
    if not s:
        return None
    return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):               # consola Windows e cp1251
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, action="append",
                    help="director cu matches_*.jsonl (repetabil). Implicit: data/raw_matches pentru un "
                         "model cu hold-out, benchmark/data pentru cel vechi")
    ap.add_argument("--model", type=Path, default=None, help="implicit data/model.npz")
    ap.add_argument("--holdout-of", type=Path, default=None,
                    help="testează pe hold-out-ul ALTUI model (ex. modelul vechi, pe meciurile "
                         "nevăzute de cel nou): comparație pe aceleași meciuri")
    ap.add_argument("--out", type=Path, default=RESULTS_DIR)
    ap.add_argument("--subset", choices=["ranked", "all"], default="ranked",
                    help="ranked = doar lobby_type 7 (ce măsoară modelul); all = orice mod")
    ap.add_argument("--since", help="doar meciuri de la această dată (YYYY-MM-DD, UTC)")
    ap.add_argument("--until", help="doar meciuri înainte de această dată (YYYY-MM-DD, UTC)")
    ap.add_argument("--bootstrap", type=int, default=300, help="re-eșantionări pentru intervale")
    a = ap.parse_args()

    model_path = a.model or default_model_path()
    if not model_path.exists():
        sys.exit(f"Nu există {model_path}. Rulează întâi:\n"
                 f"  python -m autodrafter.etl.fetch_publicmatches --count 250000 --min-rank 50\n"
                 f"  python -m autodrafter.etl.build_model")
    model = DraftModel.load(model_path)
    if model.meta.get("source") == "placeholder":
        sys.exit("Modelul e placeholder (numere inventate); nu are sens să fie testat.")

    holdout_ts = None
    if a.holdout_of:
        holdout_ts = DraftModel.load(a.holdout_of).meta.get("holdout_start_ts")
        if holdout_ts is None:
            sys.exit(f"{a.holdout_of} nu are hold-out în meta (nu e făcut de etl/build_model.py).")
    has_holdout = holdout_ts is not None or model.meta.get("holdout_start_ts") is not None
    dirs = a.data or [RAW_DIR if has_holdout else DEFAULT_OUT]

    matches: dict[int, dict] = {}
    for d in dirs:
        for m in load_matches(d):
            matches.setdefault(m["match_id"], m)
    matches = list(matches.values())
    if not matches:
        sys.exit(f"Nu există meciuri în {', '.join(map(str, dirs))}. Rulează întâi "
                 f"`python -m autodrafter.etl.fetch_publicmatches` (sau `benchmark.fetch_matches`).")

    catalog = load_catalog()
    if len(catalog) != model.n:
        sys.exit(f"Catalogul are {len(catalog)} eroi, modelul {model.n}: nepotrivire de versiune.")

    meta = model.meta
    print(f"Model: {model_path} · {meta.get('bracket')} · "
          + (f"{int(meta['matches']):,} meciuri de antrenare ({meta.get('train_start_time')} → "
             f"{meta.get('train_end_time')} UTC)" if meta.get("source") == "publicmatches"
             else f"{int(meta.get('matches', 0)):,} apariții")
          + f" · {meta.get('fetched')}")
    print(f"Meciuri încărcate: {len(matches):,}\nSe calculează …\n")
    try:
        res = evaluate(model, catalog, matches, a.subset,
                       _date_to_ts(a.since), _date_to_ts(a.until), a.bootstrap, holdout_ts)
    except ValueError as exc:
        sys.exit(str(exc))

    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(summary_text(res))
    print(f"\nScris {path}")


if __name__ == "__main__":
    main()
