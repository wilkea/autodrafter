"""Descarcă meciuri publice reale de la OpenDota, în loturi reluabile.

    python -m benchmark.fetch_matches --count 20000
    python -m benchmark.fetch_matches --count 20000 --min-rank 60   # doar Ancient+

Schema `publicMatches` a fost verificată pe un răspuns real, nu presupusă:
  match_id, start_time, radiant_win, avg_rank_tier, lobby_type, game_mode,
  radiant_team și dire_team = LISTE de 5 id-uri de eroi (nu șiruri).
Meciurile încă în desfășurare apar cu eroii [0,0,0,0,0] și `duration` 0, iar
unele moduri (1v1) au echipe de câte un erou; ambele tipuri se elimină aici.

Se păstrează și `lobby_type` / `game_mode`: peste jumătate din meciurile publice
sunt Turbo sau cu boți, iar modelul vine din statistici de meciuri ranked. Filtrul
se aplică la evaluare, deci schimbarea lui nu cere o nouă descărcare.

Reluare: cursorul este cel mai mic match_id deja salvat; o nouă rulare continuă
spre meciuri mai vechi. `--count` este ținta TOTALĂ din director.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

API = "https://api.opendota.com/api/publicMatches"
DEFAULT_OUT = Path(__file__).resolve().parent / "data"
BATCH = 1000                 # meciuri per fișier
PER_REQUEST = 100            # cât întoarce publicMatches la o cerere


class RateLimitExhausted(RuntimeError):
    """Limita zilnică e consumată; a aștepta câteva secunde nu ajută."""


# ---------------------------------------------------------------- meciuri

def parse_match(row: dict) -> dict | None:
    """Un rând `publicMatches` -> înregistrarea păstrată, sau None dacă meciul
    nu poate fi folosit (incomplet, fără rezultat, echipe nestandard)."""
    try:
        rad, dire = row["radiant_team"], row["dire_team"]
        win = row["radiant_win"]
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


def load_matches(out_dir: Path) -> list[dict]:
    """Toate meciurile salvate, fără duplicate. Rândurile deteriorate (o rulare
    întreruptă la mijlocul scrierii) se ignoră în loc să oprească evaluarea."""
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


def _next_batch_number(out_dir: Path) -> int:
    nums = [int(p.stem.split("_")[1]) for p in out_dir.glob("matches_*.jsonl")
            if p.stem.split("_")[1].isdigit()]
    return max(nums, default=0) + 1


def _write_batch(out_dir: Path, rows: list[dict]) -> Path:
    """Scriere atomică: o cădere la mijloc nu lasă un fișier pe jumătate scris."""
    path = out_dir / f"matches_{_next_batch_number(out_dir):05d}.jsonl"
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)
    return path


# ---------------------------------------------------------------- rețea

def _get(session, params: dict, tries: int = 6, sleep=time.sleep):
    """O cerere către publicMatches. Întoarce (rânduri, cereri rămase azi).

    Limita gratuită: 60 de cereri/minut și un plafon zilnic. La 429 se așteaptă
    `Retry-After` (sau un backoff exponențial); dacă plafonul zilnic e la zero,
    se ridică RateLimitExhausted, fiindcă nicio pauză scurtă nu ajută.
    """
    last = "niciun răspuns"
    for attempt in range(tries):
        try:
            r = session.get(API, params=params, timeout=40)
        except requests.RequestException as exc:
            last = f"{exc.__class__.__name__}: {exc}"
            print(f"      rețea indisponibilă ({exc.__class__.__name__}), reîncerc …",
                  file=sys.stderr)
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


def fetch(count: int, out_dir: Path = DEFAULT_OUT, min_rank: int | None = None,
          pause: float = 1.5, api_key: str | None = None,
          session=None, sleep=time.sleep) -> int:
    """Aduce meciuri până când directorul are `count`. Întoarce câte are în total."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()

    have = load_matches(out_dir)
    seen = {m["match_id"] for m in have}
    stored = len(have)
    cursor = min(seen) if seen else None
    if stored >= count:
        print(f"Există deja {stored:,} meciuri în {out_dir} (ținta: {count:,}) — nimic de făcut.")
        return stored
    if stored:
        print(f"Reiau: {stored:,} meciuri salvate, continui înapoi de la match_id < {cursor}.")

    buf: list[dict] = []
    requests_made, started = 0, time.monotonic()
    try:
        while stored + len(buf) < count:
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
            cursor = min(int(r["match_id"]) for r in rows)
            for r in rows:
                m = parse_match(r)
                if m and m["match_id"] not in seen:
                    seen.add(m["match_id"])
                    buf.append(m)
            buf = buf[: max(0, count - stored)]          # nu depășim ținta
            while len(buf) >= BATCH:
                _write_batch(out_dir, buf[:BATCH])
                stored += BATCH
                buf = buf[BATCH:]

            done = stored + len(buf)
            if requests_made % 10 == 0 or done >= count:
                el = time.monotonic() - started
                eta = (count - done) / max(done - len(have), 1) * el
                left = f" · cereri rămase azi: {remaining_day}" if remaining_day is not None else ""
                print(f"  {done:>7,}/{count:,} meciuri · {requests_made} cereri · "
                      f"{el / 60:.1f} min · încă ~{eta / 60:.1f} min{left}")
            if remaining_day is not None and remaining_day <= 3:
                raise RateLimitExhausted("aproape de plafonul zilnic OpenDota")
            sleep(pause)
    finally:
        if buf:                                          # salvăm și lotul parțial
            path = _write_batch(out_dir, buf)
            stored += len(buf)
            print(f"  lot parțial salvat: {path.name} ({len(buf)} meciuri)")
    return stored


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):               # consola Windows e cp1251
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=20000,
                    help="ținta totală de meciuri salvate în director (implicit 20000)")
    ap.add_argument("--min-rank", type=int, default=None,
                    help="avg_rank_tier minim, ex. 60 = Ancient+ (implicit: toate rangurile)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"directorul de ieșire (implicit {DEFAULT_OUT})")
    ap.add_argument("--pause", type=float, default=1.5,
                    help="pauză între cereri, secunde; limita gratuită e 60/minut")
    ap.add_argument("--api-key", default=None, help="cheie OpenDota (opțional, ridică limita)")
    a = ap.parse_args()

    print(f"publicMatches -> {a.out} · țintă {a.count:,} meciuri"
          + (f" · min_rank={a.min_rank}" if a.min_rank else ""))
    try:
        total = fetch(a.count, a.out, a.min_rank, a.pause, a.api_key)
    except RateLimitExhausted as exc:
        print(f"\nOprit: {exc}. Progresul e salvat; reia mâine cu aceeași comandă.",
              file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nÎntrerupt. Progresul e salvat; reia cu aceeași comandă.", file=sys.stderr)
        sys.exit(130)
    except RuntimeError as exc:
        print(f"\nEșec: {exc}\nProgresul e salvat; reia cu aceeași comandă.", file=sys.stderr)
        sys.exit(1)
    print(f"\nGata: {total:,} meciuri în {a.out}")


if __name__ == "__main__":
    main()
