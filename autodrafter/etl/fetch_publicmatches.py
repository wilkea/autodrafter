"""Colectează MECIURI BRUTE din OpenDota — sursa unică din care `build_model.py`
scoate toate componentele modelului (β, avantajul de partidă, counter, sinergie).

    python -m autodrafter.etl.fetch_publicmatches --count 250000 --min-rank 50

De ce meciuri brute: vechiul `fetch_opendota.py` lua β din `heroStats` și
victoriile din `/matchups` (alt set de meciuri, altă fereastră), iar counter era
reziduul dintre ele; vezi avertismentul din acel fișier.

Schema `publicMatches` a fost verificată pe un răspuns real:
  match_id, start_time, radiant_win, avg_rank_tier, lobby_type, game_mode,
  radiant_team și dire_team = LISTE de 5 id-uri de eroi (nu șiruri).
Meciurile încă în desfășurare apar cu eroii [0,0,0,0,0]; 1v1 are echipe de câte
un erou; ambele se elimină.

`--count` este numărul de meciuri SCANATE (descărcate), nu al celor păstrate:
se păstrează doar cele ranked (lobby_type 7) cu avg_rank_tier >= --min-rank, iar
restul (Turbo, boți, normale) se aruncă. Progresul afișează rata reală de
păstrare și estimează pe ea totalul de meciuri utile și timpul rămas.

Reluabil: `state.json` reține cursorul (cel mai mic match_id scanat) și
contoarele; o nouă rulare continuă spre meciuri mai vechi. `--count` este ținta
TOTALĂ de meciuri scanate. Cursorul se salvează doar odată cu lotul de pe disc,
deci o cădere nu lasă goluri.

Limita gratuită OpenDota: 60 de cereri/minut și un plafon zilnic (~2500-3000).
La 429 se așteaptă `Retry-After`; când plafonul zilnic ajunge la zero, colectarea
se oprește curat și se reia a doua zi cu aceeași comandă.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from autodrafter.model import DATA_DIR

API = "https://api.opendota.com/api/publicMatches"
RAW_DIR = DATA_DIR / "raw_matches"
RANKED_LOBBY = 7
PER_REQUEST = 100            # cât întoarce publicMatches la o cerere
BATCH = 5000                 # se scrie un fișier când s-au strâns cel puțin atâtea meciuri păstrate
EXPECTED_KEEP = 0.4          # presupunerea de pornire; înlocuită de rata măsurată


class RateLimitExhausted(RuntimeError):
    """Plafonul zilnic e consumat; nicio pauză scurtă nu ajută."""


# ---------------------------------------------------------------- meciuri

def parse_match(row: dict) -> dict | None:
    """Un rând `publicMatches` -> înregistrarea păstrată, sau None dacă meciul nu
    poate fi folosit (incomplet, fără rezultat, echipe nestandard)."""
    try:
        rad, dire, win = row["radiant_team"], row["dire_team"], row["radiant_win"]
        if not (isinstance(rad, list) and isinstance(dire, list)):
            return None
        if len(rad) != 5 or len(dire) != 5:
            return None
        heroes = [int(h) for h in rad + dire]
        if min(heroes) <= 0 or len(set(heroes)) != 10:
            return None
        if not isinstance(win, bool):
            return None
        return {
            "match_id": int(row["match_id"]),
            "start_time": int(row["start_time"]),
            "radiant_win": win,
            "avg_rank_tier": row.get("avg_rank_tier"),
            "lobby_type": row.get("lobby_type"),
            "game_mode": row.get("game_mode"),
            "radiant": heroes[:5],
            "dire": heroes[5:],
        }
    except (KeyError, TypeError, ValueError):
        return None


def wanted(match: dict, min_rank: int | None) -> bool:
    """Ranked, cu rangul mediu cel puțin `min_rank` (avg_rank_tier = 10·rang + stea)."""
    if match["lobby_type"] != RANKED_LOBBY:
        return False
    tier = match["avg_rank_tier"]
    return tier is not None and (not min_rank or tier >= min_rank)


def load_matches(out_dir: Path) -> list[dict]:
    """Toate meciurile salvate, fără duplicate; rândurile deteriorate se ignoră."""
    seen: dict[int, dict] = {}
    for path in sorted(Path(out_dir).glob("matches_*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    m = json.loads(line)
                    seen.setdefault(int(m["match_id"]), m)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
    return list(seen.values())


def _replace(tmp: Path, dst: Path, tries: int = 10) -> None:
    """Înlocuire atomică, cu reîncercări: pe Windows `replace` cade cu PermissionError dacă
    un alt proces (un cititor, antivirusul) ține fișierul deschis o clipă. Așa s-a oprit o
    colectare de o oră la 91%: o eroare trecătoare nu trebuie să o oprească."""
    for attempt in range(tries):
        try:
            tmp.replace(dst)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.2 * (attempt + 1))


def _next_batch_number(out_dir: Path) -> int:
    nums = [int(p.stem.split("_")[1]) for p in out_dir.glob("matches_*.jsonl")
            if p.stem.split("_")[1].isdigit()]
    return max(nums, default=0) + 1


def _write_batch(out_dir: Path, rows: list[dict]) -> Path:
    """Scriere atomică: o cădere la mijloc nu lasă un fișier pe jumătate scris."""
    path = out_dir / f"matches_{_next_batch_number(out_dir):05d}.jsonl"
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    _replace(tmp, path)
    return path


def load_state(out_dir: Path, have: list[dict]) -> dict:
    path = out_dir / "state.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    # fără stare: reluăm de la cel mai vechi meci păstrat (cursorul nu poate fi mai bun de atât)
    ids = [m["match_id"] for m in have]
    return {"cursor": min(ids) if ids else None, "scanned": len(have), "kept": len(have),
            "min_rank": None}


def save_state(out_dir: Path, state: dict) -> None:
    tmp = out_dir / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    _replace(tmp, out_dir / "state.json")


# ---------------------------------------------------------------- rețea

def _get(session, params: dict, tries: int = 6, sleep=time.sleep):
    """O cerere către publicMatches. Întoarce (rânduri, cereri rămase azi).

    La 429 se așteaptă `Retry-After` (sau un backoff exponențial); dacă plafonul
    zilnic e la zero se ridică RateLimitExhausted, fiindcă nicio pauză scurtă nu ajută.
    """
    last = "niciun răspuns"
    for attempt in range(tries):
        try:
            r = session.get(API, params=params, timeout=40)
        except requests.RequestException as exc:
            last = f"{exc.__class__.__name__}: {exc}"
            print(f"      rețea indisponibilă ({exc.__class__.__name__}), reîncerc …", file=sys.stderr)
        else:
            day = r.headers.get("x-rate-limit-remaining-day")
            remaining = int(day) if day and day.isdigit() else None
            if r.status_code == 200:
                return r.json(), remaining
            last = f"HTTP {r.status_code} — {r.text[:200]}"
            if r.status_code == 429:
                if remaining == 0:
                    raise RateLimitExhausted("plafonul zilnic de cereri OpenDota e consumat")
                wait = float(r.headers.get("Retry-After") or 0) or min(90.0, 5 * 2 ** attempt)
                print(f"      limita de cereri atinsă, aștept {wait:.0f}s "
                      f"(încercarea {attempt + 1}/{tries}) …", file=sys.stderr)
                sleep(wait)
                continue
            if 400 <= r.status_code < 500:
                break                       # 4xx care nu e 429: reîncercarea nu ajută
            print(f"      {last[:70]}, reîncerc …", file=sys.stderr)
        sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"cerere eșuată: {API} {params}\n  ultimul răspuns: {last}")


def _fmt_min(minutes: float) -> str:
    return f"{minutes:.0f} min" if minutes < 90 else f"{minutes / 60:.1f} h"


def fetch(count: int, out_dir: Path = RAW_DIR, min_rank: int | None = None,
          pause: float = 1.5, api_key: str | None = None,
          session=None, sleep=time.sleep) -> dict:
    """Scanează meciuri până când starea are `count`. Întoarce starea finală."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()

    have = load_matches(out_dir)
    seen = {m["match_id"] for m in have}
    state = load_state(out_dir, have)
    if state.get("min_rank") not in (None, min_rank) and have:
        print(f"ATENȚIE: datele existente au fost colectate cu min_rank={state['min_rank']}, "
              f"acum se cere {min_rank}; se continuă, dar setul va fi amestecat.", file=sys.stderr)
    state["min_rank"] = min_rank
    if state["scanned"] >= count:
        print(f"S-au scanat deja {state['scanned']:,} meciuri ({state['kept']:,} păstrate) "
              f"— ținta {count:,} e atinsă.")
        return state

    remaining_scan = count - state["scanned"]
    need = math.ceil(remaining_scan / PER_REQUEST)
    # ~0.5 s latență + pauza; ținta e o estimare de pornire, corectată de rata măsurată
    print(f"Țintă: {count:,} meciuri de scanat; de făcut încă {need:,} cereri ≈ "
          f"{_fmt_min(need * (pause + 0.5) / 60)}.")
    print(f"Se păstrează doar meciurile ranked (lobby_type {RANKED_LOBBY})"
          + (f" cu avg_rank_tier ≥ {min_rank}" if min_rank else "")
          + f"; presupunerea de pornire e ~{EXPECTED_KEEP:.0%} păstrate "
          f"(≈{int(count * EXPECTED_KEEP):,} utile) — rata reală apare în progres.")
    if state["cursor"]:
        print(f"Reiau: {state['scanned']:,} scanate, {state['kept']:,} păstrate; "
              f"continui înapoi de la match_id < {state['cursor']}.")

    buf: list[dict] = []
    cursor = state["cursor"]
    run_scan = run_keep = requests_made = 0
    started = time.monotonic()
    warned_quota = False
    try:
        while state["scanned"] < count:
            params: dict = {}
            if api_key:
                params["api_key"] = api_key
            if min_rank:
                params["min_rank"] = min_rank
            if cursor:
                params["less_than_match_id"] = cursor

            rows, remaining_day = _get(session, params, sleep=sleep)
            requests_made += 1
            if not rows:
                print("API-ul nu mai întoarce meciuri.")
                break
            if not warned_quota and remaining_day is not None:
                warned_quota = True
                if remaining_day < need:
                    print(f"ATENȚIE: cota zilnică rămasă ({remaining_day:,} cereri) nu ajunge pentru "
                          f"{need:,} cereri. Colectarea se oprește curat la limită; reia mâine "
                          "cu aceeași comandă.", file=sys.stderr)
                else:
                    print(f"Cota zilnică rămasă: {remaining_day:,} cereri (necesare ≈{need:,}).")

            cursor = min(int(r["match_id"]) for r in rows)
            state["scanned"] += len(rows)
            run_scan += len(rows)
            for r in rows:
                m = parse_match(r)
                if m and wanted(m, min_rank) and m["match_id"] not in seen:
                    seen.add(m["match_id"])
                    buf.append(m)
                    run_keep += 1
                    state["kept"] += 1
            if len(buf) >= BATCH:                      # buf gol după scriere => cursorul e consecvent
                _write_batch(out_dir, buf)
                buf = []
                state["cursor"] = cursor
                save_state(out_dir, state)

            if requests_made % 25 == 0 or state["scanned"] >= count:
                el = time.monotonic() - started
                rate = run_keep / max(run_scan, 1)
                left_req = math.ceil((count - state["scanned"]) / PER_REQUEST)
                eta = left_req * (el / requests_made) / 60
                proj = state["kept"] + rate * (count - state["scanned"])
                left = f" · cereri rămase azi: {remaining_day:,}" if remaining_day is not None else ""
                print(f"  scanate {state['scanned']:>8,}/{count:,} · păstrate {state['kept']:>7,} "
                      f"({rate:.0%}) · ≈{proj:,.0f} utile la final · {_fmt_min(el / 60)} scurs, "
                      f"încă ~{_fmt_min(eta)}{left}")
            if remaining_day is not None and remaining_day <= 3:
                raise RateLimitExhausted("aproape de plafonul zilnic OpenDota")
            sleep(pause)
    finally:
        if buf:                                        # salvăm și lotul parțial
            path = _write_batch(out_dir, buf)
            print(f"  lot parțial salvat: {path.name} ({len(buf)} meciuri)")
        state["cursor"] = cursor
        save_state(out_dir, state)
    return state


def summarize(out_dir: Path) -> str:
    ms = load_matches(out_dir)
    if not ms:
        return "niciun meci salvat"
    t0, t1 = min(m["start_time"] for m in ms), max(m["start_time"] for m in ms)
    f = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")
    return f"{len(ms):,} meciuri ranked, {f(t0)} → {f(t1)} UTC ({(t1 - t0) / 3600:.1f} h)"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):               # consola Windows e cp1251
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=250000,
                    help="ținta TOTALĂ de meciuri scanate (nu păstrate); implicit 250000")
    ap.add_argument("--min-rank", type=int, default=None,
                    help="avg_rank_tier minim, ex. 50 = Legend+ (implicit: toate rangurile)")
    ap.add_argument("--api-key", default=None, help="cheie OpenDota (opțional, ridică limita)")
    ap.add_argument("--out", type=Path, default=RAW_DIR, help=f"director (implicit {RAW_DIR})")
    ap.add_argument("--pause", type=float, default=1.5,
                    help="pauză între cereri, secunde; limita gratuită e 60/minut")
    a = ap.parse_args()

    try:
        fetch(a.count, a.out, a.min_rank, a.pause, a.api_key)
    except RateLimitExhausted as exc:
        print(f"\nOprit: {exc}. Progresul e salvat; reia cu aceeași comandă (mâine).", file=sys.stderr)
        print(summarize(a.out))
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nÎntrerupt. Progresul e salvat; reia cu aceeași comandă.", file=sys.stderr)
        sys.exit(130)
    except RuntimeError as exc:
        print(f"\nEșec: {exc}\nProgresul e salvat; reia cu aceeași comandă.", file=sys.stderr)
        sys.exit(1)
    print(f"\nGata: {summarize(a.out)}")


if __name__ == "__main__":
    main()
