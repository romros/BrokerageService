# Lighter — Model de Costs (fees, spread, slippage, RWA hours, funding)

> Objectiu: definir un model de costos consistent per a BrokerageService quan el venue és **Lighter**:
> - trading fees (maker/taker)
> - spread (bid/ask)
> - slippage (impacte d’execució)
> - horaris + particularitats de RWAs
> - funding fees (pagaments horaris entre longs/shorts)

## 1) Trading fees (maker/taker)

### 1.1 Standard account (default)
- **Maker fee = 0**
- **Taker fee = 0**
- Per spot i per perpetuals. :contentReference[oaicite:0]{index=0}

> Implicació: a nivell de “commission” del broker, en Standard, el cost “exchange_fee” és **0**.

### 1.2 Premium accounts
- Hi ha **tiers** amb maker/taker > 0, i descomptes en funció de *staking* de LIT. :contentReference[oaicite:1]{index=1}
- Si mai suportem Premium, el cost model ha de llegir la “fee tier” activa de l’account (fora d’aquest MVP).

## 2) Spread (bid/ask) — què és i com afecta el cost real

Lighter és un **CLOB** (order book). El “spread” és:
- `spread = best_ask - best_bid`
- Cost econòmic per *taker*: quan compres a market, creues l’ask; quan vens a market, creues el bid.

Com que **maker/taker fees poden ser 0** (Standard), el **spread** sovint és el “cost principal” d’entrar/sortir si uses market orders.

### Recomanació pràctica per BrokerageService
- Per cada execució:
  - Guarda `best_bid`, `best_ask`, `mid=(bid+ask)/2`.
  - Estima “spread_cost_bps” aproximat:  
    - `spread_bps ≈ (best_ask - best_bid)/mid * 10_000`
- Això et dona el “cost implícit” de l’ordre (encara que fees=0).

## 3) Slippage (impacte d’execució)

### 3.1 Definició operativa
“Slippage” = diferència entre el preu esperat (idealment prop del mid o del teu límit) i el **preu mitjà real** d’execució quan l’ordre consumeix liquiditat del llibre.

En un CLOB:
- Ordres petites poden omplir-se al top-of-book (slippage ~ 0, més enllà del spread).
- Ordres grans “mengen” nivells i el preu mitjà empitjora.

### 3.2 Com es comporten les market orders a Lighter
Lighter permet que una **market order** executi immediatament, però:
- Pots definir un **límit de preu mitjà d’execució** (average execution price) perquè l’execució no es desviï massa del mid.
- Si no hi ha liquiditat suficient o si omplir més quantitat faria que el preu mitjà superi el límit, l’ordre pot quedar **partial fill**. :contentReference[oaicite:2]{index=2}

### 3.3 Recomanació de model (simple i útil)
Per simular / estimar slippage:
1. Llegeix profunditat del llibre (nivells bid/ask) abans d’enviar l’ordre.
2. Simula “walk the book” fins la size objectiu.
3. Calcula `avg_fill_price`.
4. Slippage vs mid:
   - LONG: `slippage = (avg_fill_price - mid)/mid`
   - SHORT: `slippage = (mid - avg_fill_price)/mid`

> Nota: en producció, el millor és guardar també el preu mitjà real retornat per l’execució i comparar-lo amb el mid “snapshot” pre-trade.

## 4) Mark price, index price i “impact price” (per liquidacions i funding)

Lighter defineix el **mark price** com a preu “fair” del perp, combinant:
- Liquiditat del llibre (impact bid/ask i impact price)
- **index price** (spot/oracle)
- Altres components (ex: median de CEX prices), segons la fórmula. :contentReference[oaicite:3]{index=3}

Punts clau:
- L’**impact price** és l’execució mitjana estimada per una compra/venda de mida “impact notional” (p.ex. derivat de 500 USDC i IMR). :contentReference[oaicite:4]{index=4}
- L’index price ve d’una combinació d’oracles (Chainlink, Stork, Pyth). :contentReference[oaicite:5]{index=5}

Això importa perquè:
- **Funding** es basa en la diferència mark vs index.
- **SL/TP triggers** i liquidacions sovint es refereixen al mark, no al last.

## 5) Funding fees (els “pagaments horaris” que veus a l’històric)

### 5.1 Què és el funding (intuïció)
Els perpetuals no expiren. Per mantenir el preu del perp alineat amb el spot:
- Hi ha un pagament periòdic (**funding**) entre traders.
- No és una “fee del exchange” en si: és **peer-to-peer** (P2P). :contentReference[oaicite:6]{index=6}

### 5.2 Quan passa
- Els **funding payments passen a cada hora (hour mark)**. :contentReference[oaicite:7]{index=7}
- La majoria de mercats desplegats tenen funding period = **1 hora** (configurable per mercat). :contentReference[oaicite:8]{index=8}

### 5.3 Qui paga a qui
- Si el **funding rate és positiu**:  
  **LONGs paguen** a **SHORTs**. :contentReference[oaicite:9]{index=9}
- Si el **funding rate és negatiu**:  
  **SHORTs paguen** a **LONGs**. :contentReference[oaicite:10]{index=10}

### 5.4 De què depèn el pagament
Depèn de:
- la **mida** de la posició,
- el **costat** (long/short),
- i el **funding rate** del període. :contentReference[oaicite:11]{index=11}

El funding rate reflecteix la diferència entre:
- **mark price** del perp
- i **index price** (spot/oracle). :contentReference[oaicite:12]{index=12}

### 5.5 Com ho has d’interpretar al teu PnL
- El funding pot ser **cost** (si pagues) o **ingrés** (si cobres).
- És normal veure moviments petits i constants (cada hora) a l’històric de funding.
- Si la teva estratègia manté posicions hores, el funding esdevé una part real del cost/edge.

### 5.6 On obtenir funding rate via API
- Endpoint de funding rates: `GET /api/v1/funding-rates` (mainnet host). :contentReference[oaicite:13]{index=13}

> Recomanació: guardar el funding rate aplicat i el pagament resultant per trade-id/position-id per poder auditar PnL.

## 6) RWAs (Real World Assets): horaris i comportament fora d’hores

### 6.1 Idees clau
- Les **RWAs són tradeables 24/7** (com a mercat dins Lighter), però:
- els **price feeds externs (oracles) NO estan disponibles 24/7**. :contentReference[oaicite:14]{index=14}

Això implica:
- Durant “trading hours” de l’actiu (p.ex. equities), el mercat es comporta “normal” com crypto.
- Fora d’hores, Lighter fa servir un mecanisme de transició de pricing per gestionar **oracle stale**.

### 6.2 Mecanisme de pricing fora d’hores (important per spread/slippage i riscos d’obertura)
Quan l’oracle es torna “stale”, el sistema **transiciona gradualment** de:
- pricing basat en oracles
cap a
- pricing intern basat en order book impact prices + EMA (smoothed). :contentReference[oaicite:15]{index=15}

Detalls útils:
- Hi ha pesos amb decaïment exponencial entre “external” i “internal”. :contentReference[oaicite:16]{index=16}
- Constants de temps diferents per index vs mark. :contentReference[oaicite:17]{index=17}
- Hi ha **caps** relatius al darrer preu oracle i al leverage per limitar desviacions. :contentReference[oaicite:18]{index=18}

**Risc operatiu important**:
- “market open” pot tenir swings forts (gap). La docs ho adverteix: el leverage no canvia fora d’hores, però el preu pot moure’s significativament a l’obertura. :contentReference[oaicite:19]{index=19}

### 6.3 Regles de marge / estructura de mercat RWA
- RWAs operen en **isolated mode only** (no cross margin) per ara. :contentReference[oaicite:20]{index=20}
- LLP no actua com a market maker en RWA; s’usa un pool separat (XLP). :contentReference[oaicite:21]{index=21}
- RWA markets indiquen canvis en liquidacions i (en alguns casos) “no liquidation fee” per l’IoC close. :contentReference[oaicite:22]{index=22}

## 7) Resum “CostModel” recomanat (MVP)

Per cada execució (open/close):
- `exchange_fee = 0` (Standard account) :contentReference[oaicite:23]{index=23}
- `spread_cost` estimat amb best bid/ask (snapshot)
- `slippage_cost` estimat vs mid o vs el teu “avg execution price limit”
- `funding_accrual`:
  - si mantens posició > 1h, sumar/treure pagaments horaris segons funding rate :contentReference[oaicite:24]{index=24}

Per RWAs:
- marcar `market_type = RWA`
- assumir que fora d’hores hi pot haver:
  - pricing transicionant a intern (EMA + impact) :contentReference[oaicite:25]{index=25}
  - volatilitat/gaps a l’obertura :contentReference[oaicite:26]{index=26}
- recomanat: limitar size o exigir “price guardrails” més estrictes en market orders.

--- 
Referències:
- Lighter Docs: Trading Fees, Funding, Fair Price Marking, Order Types & Matching, RWA + RWA Pricing Mechanism.
- Lighter API Docs: funding-rates endpoint.
