"""Construiește modelul real din API-ul public OpenDota.

    python -m autodrafter.etl.fetch_opendota --bracket high

Se rulează LOCAL (api.opendota.com nu este accesibil din orice mediu) și
scrie data/model.npz. Serverul îl încarcă automat dacă există.

Metodologie (doc 03 §3.1):
  β_h       = logit(wr_h) − logit(wr_mediu), regularizat după numărul de meciuri
  cnt(a, b) = logit(wr al lui a contra lui b) − logit(wr_a) + logit(wr_b) − logit(wr_mediu)

Abaterea de la baza aditivă este esențială: „A câștigă 56% contra lui B"
înseamnă în mare parte doar că A este un erou puternic. Regularizarea către 0
împiedică perechile cu puține meciuri să domine scorul.

Sinergia (aceeași echipă) NU este expusă de API — necesită interogări SQL prin
/explorer. Rămâne zero în acest model; vezi doc 03 §3.1 pentru continuare.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import requests

from autodrafter.heroes import load_catalog
from autodrafter.model import DraftModel, default_model_path, logit, shrink

API = "https://api.opendota.com/api"

# Coloanele heroStats: 1..8 sunt tranșele de rang (1 = Herald … 8 = Immortal).
BRACKETS = {
    "all": [f"{i}" for i in range(1, 9)],
    "high": ["6", "7", "8"],
    "pro": ["pro"],
}


def _get(session: requests.Session, url: str, key: str | None, tries: int = 4):
    params = {"api_key": key} if key else None
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt * 2)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            if attempt == tries - 1:
                raise
            print(f"  reîncercare ({exc.__class__.__name__}) …", file=sys.stderr)
            time.sleep(2 ** attempt)
    raise RuntimeError("inaccesibil")


def build(bracket: str = "high", api_key: str | None = None,
          k_beta: float = 2000.0, k_counter: float = 300.0,
          sleep: float = 1.1) -> DraftModel:
    cat = load_catalog()
    n = len(cat)
    cols = BRACKETS[bracket]
    s = requests.Session()

    print(f"[1/2] heroStats (tranșa: {bracket}) …")
    stats = _get(s, f"{API}/heroStats", api_key)
    by_id = {h["id"]: h for h in stats}

    picks = np.zeros(n)
    wins = np.zeros(n)
    for h in cat:
        row = by_id.get(h.hero_id)
        if not row:
            continue
        picks[h.idx] = sum(float(row.get(f"{c}_pick") or 0) for c in cols)
        wins[h.idx] = sum(float(row.get(f"{c}_win") or 0) for c in cols)

    total = picks.sum()
    if total == 0:
        raise RuntimeError("nu s-au obținut meciuri — verificați tranșa aleasă")
    base_wr = wins.sum() / total
    with np.errstate(divide="ignore", invalid="ignore"):
        wr = np.where(picks > 0, wins / np.maximum(picks, 1), base_wr)
    beta = shrink(logit(wr) - logit(base_wr), picks, k_beta)
    print(f"      {int(total):,} apariții · winrate mediu {base_wr:.4f} · "
          f"β ∈ [{beta.min():+.3f}, {beta.max():+.3f}]")

    print(f"[2/2] matchups pentru {n} eroi (≈{n * sleep / 60:.1f} min) …")
    counter = np.zeros((n, n))
    obs = np.zeros((n, n))
    for i, h in enumerate(cat, 1):
        rows = _get(s, f"{API}/heroes/{h.hero_id}/matchups", api_key)
        for row in rows:
            opp = cat.by_id.get(row.get("hero_id"))
            g = float(row.get("games_played") or 0)
            if opp is None or g < 1:
                continue
            w = float(row.get("wins") or 0)
            raw = (logit(w / g) - logit(wr[h.idx]) + logit(wr[opp.idx])
                   - logit(base_wr))
            counter[h.idx, opp.idx] = raw
            obs[h.idx, opp.idx] = g
        if i % 20 == 0 or i == n:
            print(f"      {i}/{n}")
        time.sleep(sleep)

    counter = shrink(counter, obs, k_counter)
    counter = (counter - counter.T) / 2.0        # impunem antisimetria
    np.fill_diagonal(counter, 0.0)

    return DraftModel(
        beta=beta, counter=counter, synergy=np.zeros((n, n)),
        meta={"source": "opendota", "bracket": bracket, "n": n,
              "matches": int(total), "base_wr": round(float(base_wr), 5),
              "k_beta": k_beta, "k_counter": k_counter,
              "fetched": time.strftime("%Y-%m-%d %H:%M"),
              "synergy": "zero — necesită /explorer SQL"},
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bracket", choices=sorted(BRACKETS), default="high")
    ap.add_argument("--api-key", default=None, help="cheie OpenDota (opțional, ridică limita)")
    ap.add_argument("--k-beta", type=float, default=2000.0)
    ap.add_argument("--k-counter", type=float, default=300.0)
    ap.add_argument("--sleep", type=float, default=1.1, help="pauză între cereri (secunde)")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()

    model = build(a.bracket, a.api_key, a.k_beta, a.k_counter, a.sleep)
    out = a.out or default_model_path()
    model.save(out)
    print(f"\nScris {out} · {model.meta}")


if __name__ == "__main__":
    main()
