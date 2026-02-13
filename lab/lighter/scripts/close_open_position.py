#!/usr/bin/env python3
"""
Tanca la posició oberta del compte (ETH market_index=0).
Llegeix la mida via API (by=l1_address) o LIGHTER_CLOSE_SIZE_ETH.

Escala: la UI "Close Position" envia BaseAmount = size_eth × 10_000 (ex. 5 ETH → 50000).
Si un sol ordre falla (límit testnet), es fa fallback a parts de 0.1 ETH.
avg_execution_price: ×100 (2 decimals), amb slippage; NO ×1e6.
"""
import os
import asyncio
from dotenv import load_dotenv
import lighter

load_dotenv()

BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
L1_ADDRESS = os.getenv("LIGHTER_L1_ADDRESS")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY")


def _acceptable_price_int(mid: float, is_ask: bool, slippage_bps: int = 50) -> int:
    """Preu acceptable per market order: ×100. is_ask=True => SELL (mínim acceptable)."""
    slip = slippage_bps / 10_000
    if is_ask:
        px = mid * (1 - slip)
    else:
        px = mid * (1 + slip)
    return int(round(px * 100))


async def main():
    print("=" * 80)
    print("LIGHTER - Tancar posició oberta")
    print("=" * 80)
    print(f"Account: {ACCOUNT_INDEX}\n")

    api_client = lighter.ApiClient()
    account_api = lighter.AccountApi(api_client)

    # Llegir posicions: provar l1_address, després index
    resp = None
    for by, val in [("l1_address", L1_ADDRESS or ""), ("index", str(ACCOUNT_INDEX))]:
        if not val:
            continue
        try:
            resp = await account_api.account(by=by, value=val)
            break
        except Exception as e:
            print(f"   (by={by} fallat: {e})")
            continue
    if resp is None:
        # Fallback: mida manual si hi ha posició oberta que sabem (ex. 5 ETH)
        size_env = os.getenv("LIGHTER_CLOSE_SIZE_ETH")
        if size_env:
            try:
                size_eth = float(size_env)
                entry = 1915.0
                sign = 1
                eth_pos = {"size": size_eth, "sign": sign, "entry": entry}
                print(f"   Usant mida manual LIGHTER_CLOSE_SIZE_ETH={size_eth} ETH\n")
            except ValueError:
                eth_pos = None
        else:
            eth_pos = None
        if not eth_pos:
            print("❌ No s'ha pogut obtenir account (prova LIGHTER_L1_ADDRESS o LIGHTER_CLOSE_SIZE_ETH=5)")
            await api_client.close()
            return
    else:
        accounts = getattr(resp, "accounts", None) or []
        if not accounts:
            print("❌ Cap account al response")
            await api_client.close()
            return
        positions = getattr(accounts[0], "positions", None) or []
        eth_pos = None
        for p in positions:
            sym = getattr(p, "symbol", None) or (p.get("symbol") if isinstance(p, dict) else None)
            if sym != "ETH":
                continue
            pos_str = getattr(p, "position", None) or (p.get("position") if isinstance(p, dict) else "0")
            if pos_str is None:
                pos_str = "0"
            try:
                size = float(pos_str)
            except (TypeError, ValueError):
                size = 0.0
            if size <= 0:
                continue
            sign = getattr(p, "sign", 1) or (p.get("sign", 1) if isinstance(p, dict) else 1)
            entry_str = getattr(p, "avg_entry_price", None) or (p.get("avg_entry_price", "0") if isinstance(p, dict) else "0")
            try:
                entry = float(entry_str)
            except (TypeError, ValueError):
                entry = 1900.0
            eth_pos = {"size": size, "sign": sign, "entry": entry}
            break
        if not eth_pos:
            print("✅ No hi ha posició ETH oberta (size 0).")
            await api_client.close()
            return

    size_eth = eth_pos["size"]
    sign = eth_pos["sign"]
    entry = eth_pos["entry"]
    is_ask = sign == 1
    # avg_execution_price = ×100 amb slippage (NO ×1e6)
    close_avg_px = _acceptable_price_int(entry, is_ask=is_ask, slippage_bps=50)

    signer = lighter.SignerClient(
        url=BASE_URL,
        api_private_keys={API_KEY_INDEX: API_PRIVATE_KEY},
        account_index=ACCOUNT_INDEX,
    )

    # La UI envia BaseAmount=50000 per 5 ETH → escala ×10_000. Provar primer un sol ordre (com la web).
    base_amount_ui = int(round(size_eth * 10_000))  # mateix que "Close Position" a la UI
    print(f"   Posició: {size_eth} ETH {'LONG' if sign == 1 else 'SHORT'}, entry ~{entry:.2f}")
    print(f"   Intent 1: un sol ordre BaseAmount={base_amount_ui} (×10_000, com la UI)...\n")

    _, tx_resp, err = await signer.create_market_order(
        market_index=0,
        client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
        base_amount=base_amount_ui,
        avg_execution_price=close_avg_px,
        is_ask=is_ask,
        reduce_only=True,
    )

    if not err:
        print(f"✅ Posició tancada (1 ordre, com la UI). TX: {getattr(tx_resp, 'tx_hash', tx_resp)}\n")
    else:
        # Fallback: testnet pot limitar mida; tancar en xunks de 0.1 ETH (escala ×1e6)
        print(f"   (1 ordre rebutjat: {err})")
        print(f"   Intent 2: tancar en parts de 0.1 ETH...\n")
        import math
        CHUNK_ETH = 0.1
        base_amount_one = int(round(CHUNK_ETH * 10_000))  # market size ×10_000
        n_chunks = max(1, int(math.ceil(size_eth / CHUNK_ETH)))
        ok, fail = 0, 0
        for i in range(n_chunks):
            coi = (int(asyncio.get_event_loop().time() * 1000) + i) % 1000000
            _, tx_resp2, err2 = await signer.create_market_order(
                market_index=0,
                client_order_index=coi,
                base_amount=base_amount_one,
                avg_execution_price=close_avg_px,
                is_ask=is_ask,
                reduce_only=True,
            )
            if err2:
                print(f"   ❌ ordre {i+1}/{n_chunks}: {err2}")
                fail += 1
            else:
                ok += 1
                print(f"   ✅ {i+1}/{n_chunks} tancat.")
            await asyncio.sleep(1)
        print(f"\n✅ Tancades {ok} parts. Fracassos: {fail}")

    await signer.close()
    await api_client.close()
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
