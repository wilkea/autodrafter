# 14. Handoff — contextul conversației

Companion la `docs/13-handoff-prezentare.md`. Acolo stau **cifrele**; aici stau
**deciziile, preferințele și capcanele** — ce s-a încercat, ce s-a respins și de
ce, astfel încât o sesiune nouă să nu refacă drumul.

Citește ambele înainte de a propune ceva.

---

## 14.1 Situația

Proiect universitar la algoritmi, trei membri (Turea Victor TI-252,
Talmazanu Sergiu TI-251, Bejnari Roman TI-251). Prezentare de 7 minute.
Utilizatorul lucrează pe `C:\Repo\autodrafter`; PDF-ul de prezentare e pe
`F:\tg desk\AutoDrafter_Prezentare_7min.pdf`.

Sarcina curentă: PDF → markdown, apoi sincronizarea cifrelor din el cu
§13.4–§13.6. Vezi §13.1.

## 14.2 Cum a evoluat scopul (nu reporni de la începutul listei)

1. Planificare și documentare (`docs/01`…`docs/10`).
2. Prototip funcțional: CM complet, om vs algoritm, date reale, rulare locală.
3. **Modelul v1 s-a dovedit mai slab decât o monedă** (AUC 0,483) și a fost
   reconstruit. Vezi §14.4.
4. Materiale de prezentare în română: propunere după șablonul departamentului,
   note explicative, ghid.
5. **Reîncadrarea finală**, convenită cu utilizatorul: modelul complet al
   mecanicii jocului **nu e realizabil** și a fost scos din scop. Funcția de
   evaluare devine *variabilă experimentală*, iar întrebarea de cercetare este
   cum depinde clasamentul algoritmilor de structura evaluatorului (§13.2).

## 14.3 Preferințele utilizatorului, observate direct

- **Scurt și la obiect.** A respins de trei ori variante prea lungi ale
  propunerii: „not much or reducing. i need two paragraphs”, apoi „we should
  limit to same amount of symbols”. Descrierea a fost măsurată față de exemplul
  departamentului (671 de caractere) și adusă la 713.
- **Povestire, nu structură.** Despre ghid: „numi place structura, zicem mai
  mult explicativ ca story, ca problem si ca solutie”. Evită liste de bullet-uri
  unde merge o explicație legată.
- **Cifre concrete când afirmi ceva.** „as saying something loud use numbers”.
- **Nu comite nimic ce nu s-a cerut.** O demonstrație adăugată din proprie
  inițiativă a produs reacția „stai ce ai facut tu, demostratia ceruta nu era
  nevoie de o inlcus nicaier, pentru ce ai facut asta” și a fost ștearsă
  complet. Dacă cere text, dă text — nu cod.
- **Nu inventa structuri din date.** „numi place ce structuri creezi tu din
  date” — încercarea de a deriva categorii de mecanică din `abilities.json` a
  fost respinsă, pe bună dreptate: fișierul are mecanică, nu sens. Fluxul
  convenit: el explică, tu comprimi; tu nu inventezi categorii.
- Scrie în română amestecată cu engleză. Răspunde în română (vezi `CLAUDE.md`).

## 14.4 Ce s-a încercat și a eșuat — nu repeta

**Modelul v1 (`etl/fetch_opendota.py`) — mort, păstrat ca istorie.** β venea din
`heroStats`, counter din `/matchups`, deci counter era un rezidual calculat față
de un β din **altă sursă și altă fereastră de timp**. Rezultat: corelația dintre
sumele pe rânduri ale counter-ului și β era −0,67, iar AUC 0,483 — sub monedă.
Reparat prin: toate componentele din **aceleași meciuri brute**, centrare
obligatorie, și o verificare automată care oprește `build_model.py` dacă
|corr| ≥ 0,15. AUC 0,483 → 0,607. **Banca de testare a prins defectul înainte
să contamineze experimentele** — e un argument bun de prezentare.

**Alfa-beta era orb în faza de ban-uri.** CM începe cu 7 ban-uri consecutive;
la adâncime < 8 toate foile sunt identice și valorează exact 0,5000, pentru
~30% din decizii. Reparat cu adâncire iterativă și buget de timp. Verificat pe
modelul real: recomandarea se schimbă (Bounty Hunter @0,5000 → Brewmaster
@0,5424).

**MCTS — investiție oprită deliberat.** „mcts full se trimite away nu avem
nevoie de el, e doar un try nefavorabil”. Măsurătorile rămân în comparație
(sunt un rezultat), dar nu se mai dezvoltă.

**Modelul mecanic al abilităților — scos din scop**, de comun acord.
`experiments/link_demo.py` rămâne ca prototip de 5 eroi.

**Dotabuff — exclus.** Nu are API public, iar scraping-ul încalcă ToS. Doar
OpenDota / STRATZ.

**D2PT — nu există date de la el.** O singură apariție, `docs/12:13`: două cifre
citite manual pentru un singur draft, folosite ca diagnostic. Nu e dataset.

## 14.5 Erori pe care le-am făcut eu și le-am corectat

Listate ca să nu fie repetate ca „fapte”:

- **Am raportat EBF 2,9 la K=10 — invalid.** Cifra venea din turul 0, unde toate
  valorile sunt egale, deci retezarea e artificial maximă. Corect, din poziții
  cu semnal real: **EBF 3,5–4,2**, ușor peste √K.
- **Am scris ~10³⁰ stări — greșit cu patru ordine de mărime.** Corect:
  **2,42 × 10³⁴** componențe finale distincte. Corectat în propunere, dar
  **încă necorectat în `CLAUDE.md` și `docs/01-problem.md`** (oferit de două
  ori, fără răspuns).
- **Utilizatorul a afirmat că datele sunt „din ultimele 2 luni” — fals.** Sunt
  dintr-**o singură zi** (~10 h antrenare + 2,3 h hold-out). Nu prelua
  afirmația; cifra reală e în §13.4.

## 14.6 Terminologie: SCM

„Greedy” e o *metodă* de proiectare, nu un nume de algoritm — observație a
utilizatorului, corectă; chiar șablonul departamentului scrie „Greedy by
Density”. În propunere obiectivul e acum **SCM**, descris ca „alege la fiecare
etapă acțiunea cu cel mai bun câștig imediat, fără anticiparea adversarului”.
Utilizatorul a confirmat: „its right that is an greedy one”.

Abrevierea a fost lăsată nedesfăcută intenționat — denumirea completă e a lui,
nu a mea, și nu am inventat una. Dacă o cere desfăcută, întreabă-l care sunt
cele trei cuvinte.

În cod a rămas denumirea veche: `autodrafter/search/greedy.py`
(`class GreedySearcher`, `name = "greedy"`), `web/app.js` (`ALGO_LABEL`,
`ALGO_TAG`), `web/index.html` (un buton, două `<option>`). Redenumirea lui
locală nu era pushată la 20.11.2026.

## 14.7 Starea livrabilelor

**În repo:** codul, `data/model.npz`, `docs/01`…`docs/14`,
`experiments/results/`, `benchmark/results/`.

**NU în repo** — generate în scratchpad-ul sesiunii din cloud, care s-a șters
la resetarea containerului; reconstruite din istoricul sesiunii:

- `Propunere_Proiect.docx` — versiunea finală: conformă șablonului, 1 tabel,
  4 rânduri, 14 obiective (al 7-lea cu SCM), 408 cuvinte, nume reale.
  Generată de un script `sablon.js` cu biblioteca `docx` pentru Node.
- `Note_Explicative.docx` — ~1.035 de cuvinte, 6 secțiuni: tot ce a fost tăiat
  din propunere.
- `Ghid_Prezentare.docx` — ghid narativ, 10 secțiuni.

Dacă utilizatorul le vrea pe disc, el are versiunile trimise în chat; altfel se
regenerează.

## 14.8 Context tehnic util

- **LibreOffice e stricat în container** — eșuează chiar și pe un `.txt`. `.docx`
  se verifică extrăgând `word/document.xml` și parsând elementele `<w:t>`. Nu
  pot *vedea* pagina randată; spune-o explicit când raportezi.
- **`api.opendota.com` e blocat de proxy-ul de egress (403)** din cloud. Toată
  colectarea de date se face local. Într-o sesiune locală asta nu mai e o
  problemă.
- `scikit-learn` e folosit doar de `etl/build_model.py` și nu intră în
  dependențele de rulare (`requirements-serve.txt`).
- Testele cer `pytest` și `httpx`; `fastapi.testclient` dă un avertisment de
  deprecare pentru `httpx` — inofensiv, 106 teste trec.

## 14.9 Rămas deschis

1. PDF-ul: §13.1 — sarcina curentă.
2. Corectarea 10³⁰ → 2,42 × 10³⁴ în `CLAUDE.md` și `docs/01-problem.md`.
3. Butoane de ieșire din draft / revenire în menu (TODO al utilizatorului).
4. Poziția și algoritmul ungar în `model.py` — pasul real următor, blochează CFR.
   Ideea unificatoare convenită: poziția = *rata de alocare a resurselor*;
   puterea unui erou e funcție de resurse, nu de timp; bugetul fix de aur al
   echipei face ca formațiile cu 5 carry sau 5 support să eșueze automat, fără
   nicio penalizare inventată.
5. CFR pe instanța redusă — direcție declarată, necesită mai întâi poziții.
