# Playbooks d'onboarding d'assets

**Què és un playbook:** Procediment operatiu executable — passos concrets per completar una tasca sense coneixement extern.

**Quan s'utilitza:** Quan cal afegir un nou asset al Data Layer (Ostium live, Dukascopy històric, o ambdós).

**Principis:**
- Accionables: cada pas és executable (comandes, validacions)
- Basats en casos reals: MSFT, NVDA, NDXUSD
- Reutilitzables per Cursor i humans

---

## Diferència amb altres docs

| Doc | Propòsit |
|-----|----------|
| **AGENTS_ARQUITECTURA.md** | Disseny, invariants, contractes — què és el sistema |
| **SAFETY_RUNBOOK.md** | Incidents, recovery, kill switches — què fer quan falla |
| **docs/playbooks/** | Procediments d'onboarding — com afegir assets pas a pas |

**Playbooks ≠ documentació teòrica.** Han de permetre executar la tasca sense consultar altres fonts.

---

## Playbooks disponibles

| Playbook | Objectiu |
|----------|----------|
| [PLAYBOOK_ADD_ASSET_OSTIUM.md](PLAYBOOK_ADD_ASSET_OSTIUM.md) | Afegir asset live amb persistència durable (CSV→Parquet) |
| [PLAYBOOK_ADD_ASSET_DUKASCOPY.md](PLAYBOOK_ADD_ASSET_DUKASCOPY.md) | Afegir cobertura històrica via backfill Dukascopy |
| [PLAYBOOK_ADD_ASSET_FULL.md](PLAYBOOK_ADD_ASSET_FULL.md) | Asset complet: Ostium live + Dukascopy històric |

---

## Validació conceptual

Els playbooks han de permetre:
- Reproduir MSFT (equity amb mapping MSFT→MSFTUSD)
- Reproduir NVDA (equity amb mapping NVDA→NVDAUSD)
- Detectar que QQQ no existeix a Ostium
- Arribar a NDXUSD com a substitut funcional de QQQ

---

## Referències

- [ESTAT.md](../ESTAT.md) — estat operatiu, TASCA 3/4/5
- [AGENTS_ARQUITECTURA.md](../../AGENTS_ARQUITECTURA.md) — arquitectura
- [SAFETY_RUNBOOK.md](../SAFETY_RUNBOOK.md) — incidents i recovery
