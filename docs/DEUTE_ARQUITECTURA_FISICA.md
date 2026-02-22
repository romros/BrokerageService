# Deute d’arquitectura física (post-objectiu)

**Context:** avui el projecte ja està separat en **3 serveis** (realtime / historical / trading) amb gateway single-port i routing per prefix. Això dona una separació **runtime/operativa** bona.  
**Punt pendent:** la separació encara és sobretot **lògica i de contenidors** perquè els 3 serveis comparteixen **mateixa imatge/codi** i `PYTHONPATH=/app`. L’objectiu d’aquest document és definir com fer la separació **física real** (de codi i deploy) quan el projecte ja estigui estable.

---

## Objectiu final (què vol dir “separació física”)

Separació física = que cada servei:

- tingui **el seu paquet** Python (imports/requisits controlats)
- tingui **la seva imatge Docker** (el codi que no hi és, no es pot importar)
- tingui **els seus contractes** (API estable i versionada)
- pugui executar **tests i smoke** amb el mínim d’ENV i dependències
- mantingui un **shared** mínim i disciplinat (sense “mini-monòlit” compartit)

---

## Estat actual (baseline)

- Gateway single-port (nginx) amb rutes prefixades:
  - `/realtime/*` → realtime_datalayer
  - `/data/*` → historical_datalayer
  - `/trade/*` + `/backtests/*` → trading_service
- Split en runtime ja existent via `deploy/compose/docker-compose.split.yml`
- Però: **mateixa imatge/codi** pels 3 serveis (scaffold vNext: “encara no migració de codi”)
- Risc: acoblaments invisibles (imports creuats), shared que creix, dependències d’infra barrejades.

---

## Visió target (bounded contexts defensables)

### 1) Gateway (infra)
- Únic port, routing, health checks.
- **Zero lògica de domini**.

### 2) Realtime DataLayer
- Responsabilitat: ingest + transform (ticks→candles) + persistència + status/metrics.
- **No** decideix trades ni executa ordres.

### 3) Historical DataLayer
- Responsabilitat: dataset canònic, stitching, coverage, long-range API, metadata.
- **No** executa ordres ni coneix guardrails de trading.

### 4) Trading Service
- Responsabilitat: TradingCore + guardrails + idempotència + reconcile + exec adapters.
- Consumeix dades via **clients** (ports) als data layers.
- **No** escriu datasets (només llegeix); la persistència de mercat és dels data layers.

---

## Pla incremental (post-objectiu), sense refactors destructius

### Pas 1 — Paquets per servei (frontera real de codi)
**Objectiu:** impedir imports creuats accidentals.

Proposta de layout (monorepo amb paquets separats):
```

apps/
realtime_datalayer/
pyproject.toml
src/realtime_datalayer/...
historical_datalayer/
pyproject.toml
src/historical_datalayer/...
trading_service/
pyproject.toml
src/trading_service/...
packages/
shared/
pyproject.toml
src/shared/...
deploy/
compose/...
gateway/
nginx/...

```

**Regla d’or:** `shared/` és **minúscul** i només conté:
- DTOs/models compartits (si cal)
- error taxonomy + envelopes
- utilitats pures (clock/retry/serialization)
- **NO** clients HTTP, NO SDKs, NO web3, NO dependències d’infra.

**DoD del pas 1:**
- cada servei instal·la el seu paquet i `shared`
- test “import boundary” que falli si `trading_service` importa `realtime_datalayer` (i viceversa)
- tests suites continuen funcionant.

---

### Pas 2 — Imatges Docker separades (frontera física de deploy)
**Objectiu:** tallar acoblaments de manera física.

Opcions:
- 3 Dockerfiles (`Dockerfile.realtime`, `Dockerfile.historical`, `Dockerfile.trading`)
- o Dockerfile multi-stage amb `--target realtime|historical|trading`

**DoD del pas 2:**
- `docker-compose.split.yml` builda 3 images diferents
- cada imatge només conté el seu paquet + shared (no tot `/app`)
- smoke “boot” per cada servei.

---

### Pas 3 — Contractes d’API + observabilitat uniforme
**Objectiu:** operabilitat i integració estable.

- Normalitzar endpoints comuns:
  - `/health`, `/status`, `/metrics` a tots els serveis
- Normalitzar errors:
  - `code`, `message`, `details`, `trace_id`
- Logs estructurats amb `request_id/trace_id`
- Timeouts i retries coherents (config central i explícita)

**DoD del pas 3:**
- contractes documentats (schemas o docs)
- errors homogenis
- traces/logs comparables entre serveis.

---

## Deute tecnològic típic (símptomes) i com pagar-lo

### 1) Imports creuats
**Símptoma:** trading importa mòduls interns de realtime/historical per “comoditat”.  
**Pagament:** Pas 1 + test boundary.

### 2) Shared que creix massa
**Símptoma:** shared té infra, clients, o lògica de domini.  
**Pagament:** política “shared mínim”; qualsevol client/SDK va al servei corresponent.

### 3) Config duplicada / hardcoded
**Símptoma:** la mateixa env var o constant apareix en 2-3 llocs.  
**Pagament:** config centralitzada per servei, i shared només per helpers genèrics.

### 4) Contractes inconsistents
**Símptoma:** `/health` o errors diferents segons servei.  
**Pagament:** Pas 3.

### 5) Operabilitat desigual
**Símptoma:** un servei té logs/metrics/timeout ben definits i l’altre no.  
**Pagament:** Pas 3 + “playbook” d’ops.

---

## Principi rector (agilitat + robustesa)
- Iteracions petites: *1 pas = 1 frontera més ferma*.
- No refactors massius mentre hi hagi objectiu funcional pendent.
- Qualsevol millora ha de tenir:
  - **Abast IN/OUT** clar
  - **DoD** concret
  - **Tests per suite** + smoke opt-in si cal

---

## Nota
Aquest document és “post-objectiu”: primer prioritzem estabilitat, determinisme i operabilitat en l’arquitectura actual (0-network CI + smokes opt-in). Un cop estabilitzat, apliquem el pla per convertir el split runtime en separació física completa.
