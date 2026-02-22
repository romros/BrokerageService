# PLAYBOOK — Network smokes

Quan un smoke falla: triatge 60s → taula categoria → comanda següent. Zero palla.

---

## Triatge en 60s

1. **Connectivitat:** `./scripts/network_smokes/run_network_smokes.sh --only-connectivity`
2. **Ostium RPC + chain:** `OSTIUM_RPC_URL=<url> OSTIUM_CHAIN_ID=421614 ./scripts/network_smokes/run_network_smokes.sh --only-ostium`
3. **EstimateGas (preu de TX):** `OSTIUM_RPC_URL=... OSTIUM_CONTRACT_ADDRESS=0x... OSTIUM_FROM_ADDRESS=0x... ./scripts/network_smokes/run_network_smokes.sh --only-ostium-estimate-gas`

*(Des de l’arrel del repo.)*

---

## Category → Què vol dir → Què provar ara → Smoke

| Category | Què vol dir | Què provar ara | Smoke |
|----------|-------------|----------------|-------|
| DNS | Host no resol | Comprova VPN/proxy; resol el host manualment | `--only-connectivity` |
| CONNECT_TIMEOUT | RPC no respon a temps | Augmenta `SMOKE_TIMEOUT`; prova un altre RPC | `--only-ostium` |
| CONNECT_REFUSED | Port tancat | Comprova URL i port; firewall | `--only-connectivity` |
| HTTP_4XX | Error client (URL/auth) | Revisa URL i capçaleres | `--only-gateway` o `--only-ostium` |
| HTTP_5XX | Error servidor | Retry; comprova que el servei està viu | `--only-gateway` |
| AUTH_MISSING_ENV | Falta variable | Defineix la variable que indica el report | mateix smoke |
| AUTH_INVALID_FORMAT | Format incorrecte | Corregeix format (0x40 hex, http(s), enter) | mateix smoke |
| CHAIN_MISMATCH | chain_id ≠ esperat | Revisa `OSTIUM_RPC_URL` i `OSTIUM_CHAIN_ID` (421614 testnet) | `--only-ostium` |
| SUBGRAPH_STALE | Subgraph no indexa | **INFO; no bloqueja.** Testnet known-broken | `--only-ostium` |
| CONTRACT_REVERT | Simulació/tx revertida | Revisa contract, chain, wallet, params | `--only-ostium-preflight` o `--only-ostium-estimate-gas` |
| SDK_ERROR | Error SDK/TX | Revisa saldo USDC, leverage, RPC | `--only-ostium-trade-cycle` |
| UNEXPECTED_PAYLOAD | Resposta RPC inesperada | Revisa endpoint i mètode cridat | mateix smoke |

**Nota:** `SUBGRAPH_STALE` és INFO a testnet (subgraph no indexa); no fa exit 1.

---

## Comandes copiables

**Default (connectivity + gateway):**
```bash
./scripts/network_smokes/run_network_smokes.sh
```

**Ostium read-only:**
```bash
OSTIUM_RPC_URL=https://... OSTIUM_CHAIN_ID=421614 ./scripts/network_smokes/run_network_smokes.sh --only-ostium
```

**Ostium preflight (eth_call getOpenTrade):**
```bash
OSTIUM_RPC_URL=... OSTIUM_CHAIN_ID=421614 OSTIUM_CONTRACT_ADDRESS=0x... OSTIUM_WALLET_ADDRESS=0x... ./scripts/network_smokes/run_network_smokes.sh --only-ostium-preflight
```

**Ostium estimateGas:**
```bash
OSTIUM_RPC_URL=... OSTIUM_CONTRACT_ADDRESS=0x... OSTIUM_FROM_ADDRESS=0x... ./scripts/network_smokes/run_network_smokes.sh --only-ostium-estimate-gas
```

**Ostium trade-cycle (1 OPEN + 1 CLOSE testnet):**
```bash
OSTIUM_ENABLE_TX=1 OSTIUM_NETWORK=testnet OSTIUM_PRIVATE_KEY=0x... OSTIUM_MAX_COLLATERAL_USDC=1 OSTIUM_COLLATERAL_USDC=0.5 OSTIUM_LEVERAGE=5 ./scripts/network_smokes/run_network_smokes.sh --only-ostium-trade-cycle
```
