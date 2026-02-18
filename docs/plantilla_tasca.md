# Tasca — <títol curt>

**Referències (llegir abans de començar):**
- `AGENTS_ARQUITECTURA.md` (normes, boundaries, graduació LAB→prod-ish→primary)
- `docs/ESTAT.md` (estat operatiu i què és “canònic” ara mateix)
- (si aplica) `docs/SAFETY_RUNBOOK.md`
- (si aplica) `lab/<...>/README.md`

---

## Context
- <què està passant ara / per què surt aquesta tasca>
- <estat actual + constraints rellevants>
- <riscos: què pot trencar si ho fem malament>

---

## Objectiu
- <què volem aconseguir, en una frase>
- <què ha de quedar millor / més simple / més robust>

---

## Abast
**IN**
- <què sí que farem>

**OUT**
- <què explícitament NO farem ara (per evitar scope creep)>

---

## Passos
1. <pas 1>
2. <pas 2>
3. <pas 3>
...

---

## Tests
**Obligatoris (0-network / default):**
- `./test.sh testing/run_all.py`

**Addicionals (si aplica, opt-in):**
- <tests opt-in + condicions de SKIP>
- `docker compose ... config`

---

## Artifacts / Outputs
- <fitxers tocats/creats>
- <paths d’artifacts generats (si n’hi ha)>

---

## Definition of Done
- [ ] <criteri 1 mesurable>
- [ ] <criteri 2 mesurable>
- [ ] `./test.sh testing/run_all.py` passa
- [ ] Docs actualitzades (`docs/ESTAT.md` i/o `AGENTS_ARQUITECTURA.md` si cal)
- [ ] Commit amb missatge clar + push a `main`

---

## Notes operatives
- <comandes útils, gotchas, perf, permisos, docker, etc.>
