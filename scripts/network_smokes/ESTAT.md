# ESTAT — Network smokes (subprojecte)

**Última actualització:** 2026-02-21  
**Propòsit:** "On som" i com reproduir errors per reprendre a la propera sessió.

---

## Status (avui)

| Àrea | Resultat |
|------|----------|
| Gateway smokes | PASS (7 PASS, 2 SKIP) |
| Realtime soak | EURUSD 3/3 OK, USDJPY 3/3 OK |
| Ostium read-only | PASS (RPC liveness + chain ok) |
| Ostium trade-cycle testnet | **FAIL** a OPEN amb `SDK_ERROR` "Unknown error (missing in error_map?)" i codi `0xf120e11f` |

---

## Reproduir l'error (copy/paste)

Des de l'arrel del repo. Omple `PRIVATE_KEY` (o usa `.env.secrets` carregat abans).

**1) Versió docker compose run (recomanada, 0-impacte):**
```bash
docker compose -p brokerage_smokes run --rm --no-deps \
  -e OSTIUM_ENABLE_TX=1 \
  -e OSTIUM_NETWORK=testnet \
  -e OSTIUM_PRIVATE_KEY="$PRIVATE_KEY" \
  -e OSTIUM_MAX_COLLATERAL_USDC=1 \
  -e OSTIUM_COLLATERAL_USDC=0.5 \
  -e OSTIUM_LEVERAGE=5 \
  -e RPC_URL=https://sepolia-rollup.arbitrum.io/rpc \
  -v "$PWD:/app" -w /app \
  brokerage /app/scripts/network_smokes/run_network_smokes.sh --only-ostium-trade-cycle
```

**2) Variant més conservadora (collateral/leverage menors):**
```bash
docker compose -p brokerage_smokes run --rm --no-deps \
  -e OSTIUM_ENABLE_TX=1 \
  -e OSTIUM_NETWORK=testnet \
  -e OSTIUM_PRIVATE_KEY="$PRIVATE_KEY" \
  -e OSTIUM_MAX_COLLATERAL_USDC=1 \
  -e OSTIUM_COLLATERAL_USDC=0.1 \
  -e OSTIUM_LEVERAGE=2 \
  -e RPC_URL=https://sepolia-rollup.arbitrum.io/rpc \
  -v "$PWD:/app" -w /app \
  brokerage /app/scripts/network_smokes/run_network_smokes.sh --only-ostium-trade-cycle
```

**Què enganxar si falla:** el bloc `REPORT — smoke_ostium_trade_cycle_testnet` + la línia que conté `0xf120e11f`.

---

## Next steps (ordre estricte, màxim 4)

1. Repetir amb `OSTIUM_COLLATERAL_USDC=0.1` i `OSTIUM_LEVERAGE=2` (comanda 2).
2. Si falla igual: verificar **USDC balance** i **allowance/approval** (via `ostium-cli` o script existent).
3. Si persisteix: confirmar contract/pair config (EURUSD pair_id=0) i capturar output complet.
4. Obrir issue interna amb report + codi + hora UTC.

---

## Wrapper futur (automatització)

Possible millora: afegir un wrapper `scripts/network_smokes/run_trade_cycle_testnet.sh` que llegeixi `.env`/`.env.secrets` i executi la comanda docker compose amb els `-e` necessaris (incloent RPC_URL), per evitar comandaments llargs i reduir errors humans. No implementat encara.
