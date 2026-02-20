# TASCA — <TÍTOL CURT I ACCIONABLE>

## 0) Referències canòniques (llegir abans d’implementar)
- `AGENTS_ARQUITECTURA.md`: <link raw>
- `docs/ESTAT.md`: <link raw>
- Docs subprojecte (si aplica): <links raw>
- Fitxers clau (codi): <paths>

---

## 1) Context / Problema
- Què està passant ara (símptomes o gap respecte estat desitjat).
- Per què importa (bloqueig, risc, soroll, cost, incoherència).

---

## 2) Rumb triat (why now)
**Decisió:** <què farem i què NO farem>  
**Per què ara:** <1–3 bullets, ROI, risc reduït, desbloqueja següent fase>  
**Principi:** <ex: fail-closed, single-writer, no trencar contractes API, etc.>

---

## 3) Objectiu
- [ ] Objectiu 1 (mesurable)
- [ ] Objectiu 2 (mesurable)
- [ ] Objectiu 3 (mesurable)

---

## 4) Punt d’entrada (on tocar el codi)
**Subprojecte:** <realtime_datalayer | trading_service | historical_datalayer | shared>  
**Fitxer/funció canònica:**  
- `<path>:<func/class>` (punt únic on ha de passar la lògica)
**Components afectats:**  
- <llista curta>

---

## 5) Abast

### ENTRA
- <bullets>

### NO ENTRA
- <bullets>

---

## 6) Disseny / Regles (contracte intern)
- Regla 1: <determinista>
- Regla 2: <fail-closed / fallback / no throws>
- Regla 3: <observability mínima>

**Contracte de retorn (si aplica):**
- Inputs:
- Outputs:
- Errors: (never throws / throws only X)  
- Side-effects:

---

## 7) Pla de treball (passos)
1) <pas 1>
2) <pas 2>
3) <pas 3>
4) <pas 4>

---

## 8) Tests / Validació
### Unit (0-network)
- <test name> — què prova
- <test name> — què prova

### Integration / Smoke (si aplica)
- Comanda:
- Esperat:
- Artifact (fitxer/log/screenshot):

---

## 9) Observabilitat (què hauré de veure per dir “OK”)
**Logs esperats:**
- Exemple 1:
- Exemple 2:

**Mètriques/counters (si n’hi ha):**
- <metric> incrementa quan <condició>

**Endpoints (si aplica):**
- `/health`:
- `/status`:

---

## 10) Criteris d’acceptació (DoD)
- [ ] No es trenca cap contracte extern (API/storage).
- [ ] Comportament nou observable segons §9.
- [ ] Tests §8 passen.
- [ ] `docs/ESTAT.md` actualitzat (1–3 línies: què s’ha tancat, com verificar).
- [ ] PR/Commit amb missatge clar.

---

## 11) Riscos i guardrails
**Risc principal:** <què pot sortir malament>  
**Guardrail:** <com ho prevenim: fail-closed, timeouts, backoff, feature flag>  
**Rollback:** <env flag / revert commit / disable feature>

---

## 12) Artifacts
- PR:
- Commits:
- Evidència (logs/snippet):
- Notes finals:
