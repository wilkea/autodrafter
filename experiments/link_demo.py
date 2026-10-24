# -*- coding: utf-8 -*-
"""Prototip: legătura erou -> abilitate -> MECANICĂ -> regulă -> scor.

Ideea centrală: NU legăm abilitate de abilitate (800x800 = 640.000 de muchii,
imposibil de întreținut). Legăm abilitate -> ETICHETĂ MECANICĂ, apoi definim
reguli ETICHETĂ x ETICHETĂ. Zeci de reguli explică mii de perechi de eroi.
"""
import json, itertools
from collections import defaultdict

from pathlib import Path
import urllib.request

DATA = Path(__file__).resolve().parent.parent / "data"
BASE = "https://raw.githubusercontent.com/odota/dotaconstants/master/build"


def _load(name):
    p = DATA / name
    if not p.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        print(f"  descarc {name} ...")
        urllib.request.urlretrieve(f"{BASE}/{name}", p)
    return json.loads(p.read_text(encoding="utf-8"))


AB = _load('abilities.json')
HA = _load('hero_abilities.json')

HEROES = ['enigma', 'silencer', 'warlock', 'doom_bringer', 'antimage']
NAME = {'enigma':'Enigma','silencer':'Silencer','warlock':'Warlock',
        'doom_bringer':'Doom','antimage':'Anti-Mage'}

# ---------------------------------------------------------------------------
# STRATUL 1 — citit automat din fișierele jocului (fără interpretare)
# ---------------------------------------------------------------------------
def auto_tags(ability_name):
    a = AB.get(ability_name)
    if not isinstance(a, dict): return {}
    beh = a.get('behavior') or []
    beh = beh if isinstance(beh, list) else [beh]
    t = {}
    if 'Channeled' in beh and 'Hidden' not in beh:
        for at in (a.get('attrib') or []):
            h = (at.get('header') or '').upper()
            if 'CHANNEL' in h or h == 'DURATION:':
                v = at.get('value'); v = v[-1] if isinstance(v, list) else v
                try: t['channeled'] = float(str(v).strip('%')); break
                except ValueError: pass
        t.setdefault('channeled', 3.0)
    if a.get('bkbpierce') == 'Yes': t['pierces_bkb'] = True
    if 'AOE' in beh: t['aoe'] = True
    return t

# ---------------------------------------------------------------------------
# STRATUL 2 — curat de mână, o singură dată: CE FACE abilitatea.
# Fișierul dă NUMERELE (se schimbă la fiecare patch); noi dăm CATEGORIA
# (nu se schimbă). ~150 de rânduri pentru tot jocul, nu 640.000.
# ---------------------------------------------------------------------------
EMIT = {
  'enigma_malefice':        {'stun': 0.9},
  'enigma_demonic_conversion': {'summon': 3},
  'enigma_midnight_pulse':  {'aoe_damage': 10.0},
  'enigma_black_hole':      {'setup': 4.0, 'aoe_lock': 4.0},
  'silencer_curse_of_the_silent': {'aoe_damage': 4.0},
  'silencer_last_word':     {'silence': 6.0, 'single_target': True},
  'silencer_global_silence':{'silence': 6.0, 'global': True},
  'warlock_fatal_bonds':    {'followup': 24.0, 'single_target': True},
  'warlock_shadow_word':    {'heal': 45.0},
  'warlock_upheaval':       {'slow': 100.0},
  'warlock_rain_of_chaos':  {'summon': 1, 'followup': 30.0},
  'doom_bringer_infernal_blade': {'stun': 0.66},
  'doom_bringer_doom':      {'silence': 16.0, 'mute': 16.0, 'single_target': True},
  'antimage_mana_break':    {'mana_burn': 40.0},
  'antimage_counterspell':  {'spell_block': True},
  'antimage_mana_void':     {'stun': 0.3, 'burst_vs_low_mana': True},
  'antimage_blink':         {'escape': True},
}

# vulnerabilități la nivel de EROU (nu de abilitate)
VULN = {
  'enigma':   {'mana_dependent': 1.0, 'summon_dependent': 0.8},
  'silencer': {'single_target_reliant': 0.9, 'mana_dependent': 0.5},
  'warlock':  {'mana_dependent': 0.9, 'summon_dependent': 0.6},
  'doom_bringer': {'mana_dependent': 0.7, 'single_target_reliant': 1.0},
  'antimage': {'single_target_reliant': 0.2},
}

# ---------------------------------------------------------------------------
# STRATUL 3 — REGULILE. Aici e generalizarea: 7 reguli, nu 7 perechi.
# Ponderile sunt ILUSTRATIVE; în proiectul real se estimează prin regresie.
# ---------------------------------------------------------------------------
def rules_counter(A, B, a_key, b_key):
    """Cât câștigă eroul A împotriva eroului B, din mecanică."""
    out = []
    a_emit, b_emit = A['emit'], B['emit']
    b_vuln = VULN.get(b_key, {})

    # R1 — orice pierdere de control întrerupe o canalizare.
    #      Contează durata ȘI dacă trece prin imunitate magică.
    chan = max((v for k, v in b_emit.items() if k == 'channeled'), default=0) or \
           max((t.get('channeled', 0) for t in B['per_ability'].values()), default=0)
    if chan:
        best, why = 0.0, None
        for ab, tags in A['per_ability'].items():
            dur = max(tags.get('silence', 0), tags.get('stun', 0), tags.get('mute', 0))
            if dur <= 0: continue
            w = min(1.0, dur / 3.0) * (1.8 if tags.get('pierces_bkb') else 1.0) \
                                    * (1.4 if tags.get('global') else 1.0)
            if w > best:
                best, why = w, (AB[ab]['dname'], dur, tags.get('pierces_bkb', False))
        if best:
            out.append((0.30 * best, f"{why[0]} ({why[1]:g}s"
                        f"{', perforează BKB' if why[2] else ''}) întrerupe canalizarea"))

    # R2 — arderea manei contra unui erou dependent de mana
    if any('mana_burn' in t for t in A['per_ability'].values()) and b_vuln.get('mana_dependent'):
        out.append((0.18 * b_vuln['mana_dependent'], "arderea manei contra erou dependent de mana"))

    # R3 — blocarea vrăjilor contra unui erou cu vrăji pe țintă unică
    if any('spell_block' in t for t in A['per_ability'].values()) and b_vuln.get('single_target_reliant'):
        out.append((0.20 * b_vuln['single_target_reliant'], "blochează vrăjile pe țintă unică"))

    # R4 — damage în arie contra invocărilor
    aoe = max((t.get('aoe_damage', 0) for t in A['per_ability'].values()), default=0)
    if aoe and b_vuln.get('summon_dependent'):
        out.append((0.12 * b_vuln['summon_dependent'], "damage în arie curăță invocările"))

    return out

def rules_synergy(A, B, a_key, b_key):
    """Cât câștigă A și B jucând ÎMPREUNĂ."""
    out = []
    def best(team, tag):
        return max((t.get(tag, 0) for t in team['per_ability'].values()), default=0)
    # R5 — pregătire (blocaj lung în arie) + continuare (damage în arie)
    for X, Y, xn, yn in ((A, B, a_key, b_key), (B, A, b_key, a_key)):
        s, f = best(X, 'setup'), best(Y, 'followup')
        if s and f:
            out.append((0.25 * min(1.0, s / 4.0),
                        f"{NAME[xn]} grupează ținta, {NAME[yn]} o exploatează"))
    return out

# ---------------------------------------------------------------------------
def build(hero_key):
    per = {}
    for raw in HA['npc_dota_hero_' + hero_key]['abilities']:
        for ab in ([raw] if isinstance(raw, str) else raw):
            if ab not in AB: continue
            tags = dict(auto_tags(ab)); tags.update(EMIT.get(ab, {}))
            if tags: per[ab] = tags
    emit = defaultdict(float)
    for t in per.values():
        for k, v in t.items():
            if isinstance(v, (int, float)): emit[k] = max(emit[k], v)
    return {'per_ability': per, 'emit': dict(emit)}

H = {k: build(k) for k in HEROES}

print("ETICHETE CITITE AUTOMAT (din câmpuri structurate):")
for k in HEROES:
    auto = {AB[a]['dname']: {x: y for x, y in t.items() if x in ('channeled','pierces_bkb')}
            for a, t in H[k]['per_ability'].items()
            if any(x in t for x in ('channeled','pierces_bkb'))}
    print(f"  {NAME[k]:10s} {auto}")

print("\n" + "="*78)
print("CONTRACARARE MECANICĂ  (A ▸ B)")
print("="*78)
rows = []
for a, b in itertools.permutations(HEROES, 2):
    r = rules_counter(H[a], H[b], a, b)
    if r: rows.append((sum(w for w, _ in r), a, b, r))
for tot, a, b, r in sorted(rows, reverse=True):
    print(f"\n  {NAME[a]:10s} ▸ {NAME[b]:10s}   {tot:+.2f}")
    for w, why in r: print(f"      {w:+.2f}  {why}")

print("\n" + "="*78)
print("SINERGIE MECANICĂ")
print("="*78)
seen = set()
for a, b in itertools.combinations(HEROES, 2):
    r = rules_synergy(H[a], H[b], a, b)
    if r:
        print(f"\n  {NAME[a]} + {NAME[b]}   {sum(w for w,_ in r):+.2f}")
        for w, why in r: print(f"      {w:+.2f}  {why}")
