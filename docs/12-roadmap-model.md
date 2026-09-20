# 12. Roadmap — de la statistică la mecanică

Modelul actual (AUC 0.607, calibrat) este validat statistic, dar eșuează
sistematic exact acolo unde căutarea îl împinge. Acest document descompune
drumul de la starea curentă la un model care nu mai recomandă drafturi absurde.

---

## 12.0 Diagnosticul — de ce e nevoie de tot ce urmează

Un draft generat de algoritm (Grimstroke, Skywrath, Mirana, Elder Titan,
Outworld Devourer) primește **63%** de la modelul nostru și **30.7%** de la
D2PT. Direcții opuse. Componența nu are structură de farm și nu poate funcționa.

Și un al doilea fapt, din aceeași sursă: **aceiași 10 eroi, cu poziții
reatribuite, trec de la 69/31 la 53/47.** Un salt de 16 puncte doar din
atribuirea rolurilor. Poziția nu e un detaliu, e o variabilă de prim rang.

Trei cauze, tot mai profunde:

1. **Modelul nu are noțiunea de poziție.** Știe cât e de bun un erou, contra
   cui și cu cine. Nimic despre rol, aur sau linie.

2. **Aditivitatea nu poate reprezenta concurența pentru resurse.** Farm-ul e o
   proprietate a întregii mulțimi și e supra-aditivă: al 5-lea core e mult mai
   rău decât al 2-lea. O sumă de termeni perechi crește liniar în numărul de
   perechi. **Nu se repară cu mai multe date — e o limită de reprezentare.**

3. **Căutarea caută unde modelul n-a fost antrenat.** Compoziții cu 5 supporți
   nu apar în meciuri ranked, deci modelul extrapolează liniar într-o regiune
   necunoscută. Iar căutarea vânează maximul, care se află fix acolo unde
   erorile sunt cele mai mari și mai măgulitoare. Legea lui Goodhart.

Punctul 3 e cel important pentru raport: **cu cât căutarea e mai bună, cu atât
exploatează mai eficient punctele oarbe ale modelului.**

---

## 12.1 Nivelul 1 — ce se poate face acum, fără date noi

Toate folosesc lucruri deja descărcate sau deja în cod.

| ce | de ce | efort |
|---|---|---|
| **Test de regresie pe draftul absurd** | fixează cazul din captură ca test permanent: modelul trebuie să-l respingă. Fără el, „am reparat" rămâne o impresie | mic |
| **Rolurile din `heroes.json`** | sunt descărcate, ajung în interfață, nu intră în calcul. Prima aproximare de poziție, gratuită | mic |
| **`pro_ban` din heroStats** | rata de ban în pro e un semnal direct despre ce consideră profesioniștii periculos. Ignorat complet | mic |
| **Adâncime/lățime la alfa-beta** | acum d=4, K=10. Un plan de ban-uri se întinde pe 6–8 niveluri — literalmente nu poate fi văzut | mediu |
| **Semințe explicite la MCTS** | un rezultat nereproductibil nu e rezultat; iar o rulare MCTS e un eșantion, nu un număr | mic |
| **Verificarea frecvențelor de alegere** | rulezi 200 de drafturi, numeri eroii, compari cu ratele reale de pick. Dacă algoritmul ia un erou în 95% din cazuri iar oamenii niciodată — e bug, nu descoperire | mic |

Ultima e cea mai ieftină metodă de a detecta un model stricat și ar fi prins
draftul absurd fără nicio captură de ecran.

---

## 12.2 Nivelul 2 — poziția și matchup-urile

**Poziția e cheia de boltă.** Fără ea nu se pot face nici matchup-urile de
linie, nici penalizarea de farm, nici curba de putere pe linie.

### Formulare

Fiecare erou primește o distribuție peste pozițiile 1–5, estimată din date
(nu aleasă de mână). Componența se evaluează prin **atribuirea optimă a celor
5 eroi la cele 5 poziții**:

```
maximizează Σ potrivire(erou_i, poziția_σ(i))   peste toate atribuirile σ
```

Problema de atribuire → **algoritmul ungar, O(k³), exact**. Deja prevăzut în
doc 04. Dacă nicio atribuire nu e rezonabilă (5 supporți), scorul atribuirii
optime e mic, și aceasta **este** penalizarea — nu trebuie inventată separat.

### De ce repară problema

Termenul devine **neliniar** în componență: valoarea celui de-al cincilea core
depinde de ce s-a luat deja. Exact ce aditivitatea nu poate exprima.

Și testează predicția făcută mai devreme: *avantajul MCTS apare doar când
evaluarea e neliniară*. Cu model aditiv, alfa-beta l-a bătut pe MCTS
(57% vs 43%). Dacă inversarea se produce după adăugarea poziției, ipoteza e
confirmată — și e un rezultat propriu, nu preluat din literatură.

### Sursa datelor

`publicMatches` nu dă roluri. Detaliile de meci (`/matches/{id}`) au
`lane_role` per jucător, dar sunt o cerere per meci — prea scump pentru 100k.
Trei variante, în ordinea costului:

1. **Din `heroes.json`** — câmpul `roles` (Carry, Support, …). Grosier, gratuit.
2. **Agregat per erou** — distribuția de poziții a fiecărui erou, estimată o
   singură dată dintr-un eșantion mic de meciuri cu detalii complete
   (2.000–5.000 de meciuri ajung pentru o distribuție per erou).
3. **Din net worth** — rangul averii în echipă la finalul meciului aproximează
   poziția. `publicMatches` nu îl dă, dar detaliile da.

Varianta 2 e compromisul corect: cost unic, rezultat stabil, nu depinde de
meciul curent.

### Matchup-urile de linie

Necesită poziția ca precondiție. Counter-ul actual e global, echipă contra
echipă; matchup-ul de linie cere să știi cine stă cu cine. Se adaugă abia
după ce poziția există.

---

## 12.3 Nivelul 3 — peak de putere

Da, se scoate din statistică, și da, se poate face obiectiv.

### Metoda simplă

Pentru fiecare erou, rata de câștig pe intervale de durată (0–25, 25–35,
35–45, 45+ min). Potrivești o curbă; maximul ei este peak-ul. Durata e deja
în `publicMatches`, deci costul e zero.

### Confuzia care trebuie declarată

**Meciurile câștigate se termină mai repede.** Deci „eroul X câștigă meciurile
scurte" poate însemna „X e puternic devreme" SAU „X face bulgăre de zăpadă".
Cele două nu se disting din durată.

### Metoda curată

Avantajul de aur/experiență la momente FIXE (10, 20, 30 de minute), nu la
finalul meciului. `/matches/{id}` conține seria `radiant_gold_adv`. E mai
scump (o cerere per meci), dar măsoară puterea la un moment dat, nu rezultatul.

Recomandare: varianta simplă întâi, cu confuzia scrisă în documentație;
varianta curată pe un eșantion de 5.000 de meciuri, ca verificare.

### Cum intră în model

Trăsătură la nivel de echipă: **nepotrivirea curbelor**.

```
curve_mismatch = Σ_t  w(t) · (putere_noi(t) − putere_ei(t))
```

Neliniară, la fel ca poziția. Răspunde la „ei sunt puternici devreme, noi
târziu — cine apucă să închidă meciul".

---

## 12.4 Nivelul 4 — stratul mecanic: abilități, sinergii, counter-abilități

Partea despre care spuneai că nu ai idee cum se face. Are o soluție curată.

### Problema cu statistica — de ce „fără pricină" contează

Silencer contra Enigma. Statistic: se întâlnesc în ~0.25% din meciuri, iar
Silencer are poate +3%. Dar acele +3% sunt o **medie diluată** peste meciuri în
care Global Silence a prins Black Hole și meciuri în care nu, în care Silencer
avea Refresher și în care nu.

Mecanica nu e o medie: **când prinde, lupta e decisă.**

Și, mai important, statistica **nu generalizează**. Numărul +3% nu spune că
același motiv se aplică lui Warlock, Death Prophet, Witch Doctor, Bane, Pudge,
Crystal Maiden. Pentru fiecare pereche ai nevoie de date separate. O regulă
mecanică le explică pe toate deodată — inclusiv pentru un erou apărut ieri,
care n-are încă nicio statistică.

### Arhitectura: de ce NU legăm abilitate de abilitate

800 de abilități de eroi → 640.000 de muchii. Imposibil de întreținut, și
aproape toate fără sens.

**Legăm abilitate → ETICHETĂ MECANICĂ, și definim reguli ETICHETĂ × ETICHETĂ.**

```
  EROU ──are──▶ ABILITATE ──emite──▶ ETICHETĂ ◀──consumă── VULNERABILITATE ◀──are── EROU
                                        │
                                   REGULĂ (etichetă × etichetă → pondere)
```

E un graf, dar **tripartit și cu muchii tipizate** — nu un arbore. Nodurile de
mijloc (etichetele) sunt mecanismul de generalizare: ~30 de reguli explică mii
de perechi de eroi.

### Cele trei straturi de date

| strat | conținut | volum | se schimbă la patch |
|---|---|---|---|
| **A — automat** | `Channeled`, `bkbpierce`, `dispellable`, tip de damage, durate cu header propriu (SILENCE/HEX/ROOT/SLEEP/TAUNT/FEAR) | tot jocul | da, automat |
| **B — curat de mână** | abilitate → categorie („Global Silence este un silence") | ~150–300 rânduri, o dată | rar |
| **C — reguli** | etichetă × etichetă → pondere | ~30 rânduri | niciodată |

Stratul B e necesar fiindcă — verificat pe date reale — **faptul că Global
Silence e un silence nu există în niciun câmp structurat**, doar în nume.
Regula de aur rămâne cea din doc 09: *fișierul deține numerele, noi deținem
categoriile.*

### Demonstrație pe 5 eroi

`python experiments/link_demo.py` — 7 reguli aplicate pe Enigma, Silencer,
Warlock, Doom, Anti-Mage produc:

```
  Silencer  ▸ Enigma    +0.85   Global Silence (6s, perforează BKB) întrerupe canalizarea
  Silencer  ▸ Warlock   +0.83   idem, contra Upheaval
  Doom      ▸ Enigma    +0.54   Doom (16s, perforează BKB) întrerupe canalizarea
  Anti-Mage ▸ Doom      +0.33   arderea manei + blochează vrăjile pe țintă unică
  Anti-Mage ▸ Silencer  +0.27   idem

  SINERGIE
  Enigma + Warlock      +0.25   Enigma grupează ținta, Warlock o exploatează
```

Ultima e Black Hole + Chaotic Offering — combinația clasică — apărută dintr-o
regulă generală „pregătire + continuare", nu dintr-o listă de combo-uri.

**Un defect vizibil în demonstrație**, lăsat intenționat: Upheaval e citit ca
`channeled: 1.0s` în loc de 16s, fiindcă extragerea prinde headerul greșit.
Exact clasa de eroare pe care o prind testele-etalon din doc 09 §9.4.

### Itemii

Nu sunt entități separate — sunt **modificatori pe valoarea etichetelor**.
Refresher nu e „un item", e „×2 utilizări ale ultimate-ului", deci dublează
magnitudinea etichetei. BKB e „imunitate magică N secunde", deci anulează
regulile care nu perforează.

Ca să nu explodeze: se iau doar itemii cu rată mare de cumpărare pe eroul
respectiv (din date), nu toți itemii × toți eroii. Rămâne opțional, după poziție.

### dmg per level și faza de linie

Complet calculabil din fișiere, fără nicio statistică: damage de bază +
creșterea pe atribut × nivel, plus damage-ul abilităților la nivelurile 1–6,
plus armură, viteză, rază de atac, EHP.

Nu ca notă unică, cum ai spus — ci ca **profil de linie**, care alimentează
matchup-ul de linie. Deci și acesta are nevoie de poziție înainte.

### Cum intră totul în model

```
model.counter = counter_statistic + counter_mecanic
model.synergy = synergy_statistic + synergy_mecanic
```

Adunare de matrice. `score()` nu se schimbă, căutarea nu se schimbă, interfața
nu se schimbă. **Ponderile se estimează prin regresie pe meciuri reale**, nu se
aleg de mână — cele din demonstrație (0.30, 0.18, 0.25) sunt ilustrative.

### Validarea care contează

1. **AUC pe meciuri nevăzute** urcă peste 0.607, sau nu?
2. **Draftul absurd** e respins acum, sau nu?
3. **Cold start**: scoți un erou complet din datele statistice și vezi cât de
   bine îl evaluează stratul mecanic singur. Aici statistica nu poate concura.

Dacă (1) nu se îmbunătățește dar (2) și (3) da, tot e un câștig — și e un
rezultat care merită scris, fiindcă arată că AUC-ul global nu măsoară ce
contează pentru draft.

---

## 12.5 Ordinea recomandată

| # | pas | deblochează | efort |
|---|---|---|---|
| 1 | test de regresie pe draftul absurd | măsurarea progresului | mic |
| 2 | poziție + atribuire ungară | matchup de linie, penalizare de farm, neliniaritate | mare |
| 3 | reverificarea draftului absurd | dovada că pasul 2 a funcționat | mic |
| 4 | curba de putere | nepotrivirea de tempo | mediu |
| 5 | stratul mecanic (A + B + C) | generalizare, cold start, explicabilitate | mare |
| 6 | adâncime mai mare la căutare | planuri de ban-uri pe mai mulți pași | mediu |
| 7 | matchup de linie | precizie în faza de linie | mediu |
| 8 | itemi, preferință de eroi | opționale | mediu |

Pasul 1 înaintea pasului 2 nu e birocrație: fără el nu poți demonstra că
pasul 2 a schimbat ceva.

---

## 12.6 Ce nu face acest model, și trebuie scris în raport

- Nu modelează execuția, coordonarea sau nivelul jucătorilor.
- Nu modelează ordinea acțiunilor într-o luptă — doar dacă mecanismele există.
- Stratul mecanic va fi probabil mai slab decât statistica la predicție brută;
  valoarea lui e în explicabilitate, cold start și transfer între patch-uri.
- Auto-jocul rămâne „cine câștigă după modelul nostru". Singurele judecăți
  externe rămân meciurile reale, optimul exact pe instanța redusă, și acordul
  cu drafturile profesioniste.
