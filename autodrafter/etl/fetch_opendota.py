"""⚠ ÎNVECHIT — NU folosi acest script pentru modelul curent. Modelul se construiește
acum cu `fetch_publicmatches.py` + `build_model.py`, dintr-o singură sursă.

Defectul găsit de `benchmark/` (raportul din benchmark/results/): counter se
calculează aici ca reziduu față de β, dar β vine din `heroStats` (tranșele alese) iar
victoriile din `/matchups` — ALT set de meciuri, altă fereastră, probabil toate
tranșele. Reziduul absoarbe diferența dintre cele două surse în loc să măsoare
interacțiunea, deci matricea counter conține un nivel de erou de semn opus lui β
(sumele pe rânduri corelează −0.67 cu β). Rezultat măsurat pe 8.347 de meciuri ranked:
β singur AUC 0.590, counter singur 0.441 (anti-predictiv), modelul complet 0.488 —
mai rău decât o monedă (log-loss 0.7152 față de 0.6931).
Fișierul rămâne în repo ca parte din povestea metodologică a proiectului: o
componentă calculată din două surse nu e „mai multă informație", e o inconsecvență.

Construiește modelul real din API-ul public OpenDota (metoda veche).

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
import json
import sys
import time
from pathlib import Path

import numpy as np
import requests

from autodrafter.heroes import load_catalog
from autodrafter.model import (DATA_DIR, DraftModel, default_model_path, logit,
                               shrink)

API = "https://api.opendota.com/api"

# Coloanele heroStats: 1..8 sunt tranșele de rang (1 = Herald … 8 = Immortal).
BRACKETS = {
    "all": [f"{i}" for i in range(1, 9)],
    "high": ["6", "7", "8"],
    "pro": ["pro"],
}


CACHE = DATA_DIR / "cache"


def _get(session: requests.Session, url: str, key: str | None, tries: int = 5):
    """Cerere cu reîncercări. La eșec ridică o eroare care SPUNE ce s-a întâmplat.

    Limita gratuită OpenDota este de 60 de cereri pe minut și 2000 pe zi; la
    depășire răspunde cu 429 și, de regulă, cu antetul Retry-After.
    """
    params = {"api_key": key} if key else None
    last = "niciun răspuns"

    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            last = f"{exc.__class__.__name__}: {exc}"
            print(f"      rețea indisponibilă ({exc.__class__.__name__}), reîncerc …",
                  file=sys.stderr)
        else:
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code} — {r.text[:200]}"
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After") or 0) or min(90.0, 5 * 2 ** attempt)
                print(f"      limita de cereri atinsă, aștept {wait:.0f}s "
                      f"(încercarea {attempt + 1}/{tries}) …", file=sys.stderr)
                time.sleep(wait)
                continue
            if 400 <= r.status_code < 500:
                break        # 4xx care nu e 429: reîncercarea nu ajută
            print(f"      {last[:60]}, reîncerc …", file=sys.stderr)
        time.sleep(2 ** attempt)

    raise RuntimeError(
        f"cerere eșuată: {url}\n"
        f"  ultimul răspuns: {last}\n"
        f"  dacă este 429, mărește --sleep (ex. --sleep 2) sau folosește --api-key"
    )


def _matchups(session, hero, key, sleep: float, use_cache: bool) -> list:
    """Matchup-urile unui erou, cu cache pe disc.

    Colectarea durează minute și poate cădea la jumătate. Fără cache, o cădere
    la eroul 90 înseamnă reluarea de la zero; cu cache, reluarea continuă.
    """
    path = CACHE / f"matchups_{hero.hero_id}.json"
    if use_cache and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            path.unlink(missing_ok=True)

    rows = _get(session, f"{API}/heroes/{hero.hero_id}/matchups", key)
    if use_cache:
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows), encoding="utf-8")
    time.sleep(sleep)
    return rows


def build(bracket: str = "high", api_key: str | None = None,
          k_beta: float = 2000.0, k_counter: float = 300.0,
          sleep: float = 1.5, use_cache: bool = True) -> DraftModel:
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
    cached = sum(1 for h in cat if (CACHE / f"matchups_{h.hero_id}.json").exists())
    if use_cache and cached:
        print(f"      {cached}/{n} deja în cache, se reiau doar restul")

    for i, h in enumerate(cat, 1):
        rows = _matchups(s, h, api_key, sleep, use_cache)
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
        if i % 10 == 0 or i == n:
            print(f"      {i}/{n}")

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
    ap.add_argument("--sleep", type=float, default=1.5,
                    help="pauză între cereri (secunde); limita gratuită e 60/minut")
    ap.add_argument("--no-cache", action="store_true",
                    help="ignoră cache-ul din data/cache și descarcă tot din nou")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()

    model = build(a.bracket, a.api_key, a.k_beta, a.k_counter, a.sleep,
                  use_cache=not a.no_cache)
    out = a.out or default_model_path()
    model.save(out)
    print(f"\nScris {out} · {model.meta}")


if __name__ == "__main__":
    main()
