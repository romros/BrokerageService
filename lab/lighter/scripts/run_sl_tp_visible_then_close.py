#!/usr/bin/env python3
"""
Obre posició a mercat, col·loca SL/TP, fa UPDATE (modify_order),
espera uns segons perquè pugueu veure-ho a la UI, i després tanca.
Ús: python run_sl_tp_visible_then_close.py
"""
import os
import sys
import asyncio
from dotenv import load_dotenv
import lighter

load_dotenv()

BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY")

# Pausa (segons) abans de cancel·lar i tancar, per poder mirar la UI
PAUSE_SECONDS = int(os.getenv("LIGHTER_PAUSE_BEFORE_CLOSE", "90"))

SL_CLIENT_ORDER_INDEX = 900001
TP_CLIENT_ORDER_INDEX = 900002


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
    print("LIGHTER - Obrir posició → SL/TP → UPDATE → (tu ho veus) → Tancar")
    print("=" * 80)
    print(f"Account: {ACCOUNT_INDEX}")
    print(f"Pausa abans de tancar: {PAUSE_SECONDS} s (variable LIGHTER_PAUSE_BEFORE_CLOSE)\n")

    api_client = lighter.ApiClient()
    signer = lighter.SignerClient(
        url=BASE_URL,
        api_private_keys={API_KEY_INDEX: API_PRIVATE_KEY},
        account_index=ACCOUNT_INDEX,
    )

    mid_price = 1966.0
    position_size_eth = 0.05
    position_size_market = int(position_size_eth * 10_000)  # market ×10_000
    open_avg_px = _acceptable_price_int(mid_price, is_ask=False, slippage_bps=50)
    close_avg_px = _acceptable_price_int(mid_price, is_ask=True, slippage_bps=50)
    sl_size_int = int(position_size_eth * 10_000)

    # --- 1. Obrir posició (market) ---
    print("STEP 1: OPEN LONG (market)")
    try:
        _, tx_resp, err = await signer.create_market_order(
            market_index=0,
            client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
            base_amount=position_size_market,
            avg_execution_price=open_avg_px,
            is_ask=False,
            reduce_only=False,
        )
        if err:
            print(f"❌ {err}\n")
            await signer.close()
            await api_client.close()
            return
        print(f"✅ Obert. TX: {getattr(tx_resp, 'tx_hash', tx_resp)}\n")
    except Exception as e:
        print(f"❌ {e}\n")
        await signer.close()
        await api_client.close()
        return

    await asyncio.sleep(2)

    # --- 2. Col·locar SL ---
    print("STEP 2: PLACE SL")
    sl_trigger_1 = mid_price * 0.98
    sl_price_1 = sl_trigger_1 * 0.999
    sl_trigger_int_1 = int(sl_trigger_1 * 100)
    sl_price_int_1 = int(sl_price_1 * 100)
    sl_ok = False
    try:
        _, tx_resp, err = await signer.create_sl_limit_order(
            market_index=0,
            client_order_index=SL_CLIENT_ORDER_INDEX,
            base_amount=sl_size_int,
            trigger_price=sl_trigger_int_1,
            price=sl_price_int_1,
            is_ask=True,
            reduce_only=True,
        )
        if err:
            print(f"❌ {err}\n")
        else:
            print(f"✅ SL col·locat (trigger ${sl_trigger_1:.2f})\n")
            sl_ok = True
    except Exception as e:
        print(f"❌ {e}\n")
    await asyncio.sleep(1)

    # --- 3. Col·locar TP ---
    print("STEP 3: PLACE TP")
    tp_trigger_1 = mid_price * 1.02
    tp_price_1 = tp_trigger_1 * 1.001
    tp_trigger_int_1 = int(tp_trigger_1 * 100)
    tp_price_int_1 = int(tp_price_1 * 100)
    tp_ok = False
    try:
        _, tx_resp, err = await signer.create_tp_limit_order(
            market_index=0,
            client_order_index=TP_CLIENT_ORDER_INDEX,
            base_amount=sl_size_int,
            trigger_price=tp_trigger_int_1,
            price=tp_price_int_1,
            is_ask=True,
            reduce_only=True,
        )
        if err:
            print(f"❌ {err}\n")
        else:
            print(f"✅ TP col·locat (trigger ${tp_trigger_1:.2f})\n")
            tp_ok = True
    except Exception as e:
        print(f"❌ {e}\n")
    await asyncio.sleep(2)

    # --- 4. UPDATE SL ---
    print("STEP 4: UPDATE SL (modify_order)")
    sl_trigger_2 = mid_price * 0.97
    sl_price_2 = sl_trigger_2 * 0.999
    sl_trigger_int_2 = int(sl_trigger_2 * 100)
    sl_price_int_2 = int(sl_price_2 * 100)
    if sl_ok:
        try:
            _, tx_resp, err = await signer.modify_order(
                market_index=0,
                order_index=SL_CLIENT_ORDER_INDEX,
                base_amount=sl_size_int,
                price=sl_price_int_2,
                trigger_price=sl_trigger_int_2,
            )
            if err:
                print(f"❌ {err}\n")
            else:
                print(f"✅ SL actualitzat → trigger ${sl_trigger_2:.2f}\n")
        except Exception as e:
            print(f"❌ {e}\n")
    await asyncio.sleep(1)

    # --- 5. UPDATE TP ---
    print("STEP 5: UPDATE TP (modify_order)")
    tp_trigger_2 = mid_price * 1.03
    tp_price_2 = tp_trigger_2 * 1.001
    tp_trigger_int_2 = int(tp_trigger_2 * 100)
    tp_price_int_2 = int(tp_price_2 * 100)
    if tp_ok:
        try:
            _, tx_resp, err = await signer.modify_order(
                market_index=0,
                order_index=TP_CLIENT_ORDER_INDEX,
                base_amount=sl_size_int,
                price=tp_price_int_2,
                trigger_price=tp_trigger_int_2,
            )
            if err:
                print(f"❌ {err}\n")
            else:
                print(f"✅ TP actualitzat → trigger ${tp_trigger_2:.2f}\n")
        except Exception as e:
            print(f"❌ {e}\n")

    # --- 6. Pausa per mirar la UI ---
    print("=" * 80)
    print(f"👉 Mira la UI ara: Positions (1) + Open Orders (haurien de sortir SL/TP).")
    print(f"   Tancant en {PAUSE_SECONDS} segons...")
    print("=" * 80)
    for remaining in range(PAUSE_SECONDS, 0, -10):
        print(f"   {remaining}s...")
        await asyncio.sleep(10)
    if PAUSE_SECONDS % 10 != 0:
        await asyncio.sleep(PAUSE_SECONDS % 10)
    print("   Tancant ara.\n")

    # --- 7. Cancel·lar SL i TP ---
    print("STEP 6: CANCEL SL & TP")
    for name, oidx in [("SL", SL_CLIENT_ORDER_INDEX), ("TP", TP_CLIENT_ORDER_INDEX)]:
        try:
            _, _, err = await signer.cancel_order(market_index=0, order_index=oidx)
            print(f"   {'✅' if not err else '⚠️'} {name} (order_index={oidx})")
        except Exception as e:
            print(f"   ❌ {name}: {e}")
    await asyncio.sleep(2)

    # --- 8. Tancar posició ---
    print("\nSTEP 7: CLOSE POSITION (market reduce-only)")
    try:
        _, tx_resp, err = await signer.create_market_order(
            market_index=0,
            client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
            base_amount=position_size_market,
            avg_execution_price=close_avg_px,
            is_ask=True,
            reduce_only=True,
        )
        if err:
            print(f"❌ {err}\n")
        else:
            print(f"✅ Posició tancada. TX: {getattr(tx_resp, 'tx_hash', tx_resp)}\n")
    except Exception as e:
        print(f"❌ {e}\n")

    print("=" * 80)
    await signer.close()
    await api_client.close()


if __name__ == "__main__":
    asyncio.run(main())
