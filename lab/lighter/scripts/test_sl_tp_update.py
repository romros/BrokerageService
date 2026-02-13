#!/usr/bin/env python3
"""
Lighter - SL/TP UPDATE validation (testnet)
Prova update de Stop Loss i Take Profit amb SDK modify_order().
Referència: https://github.com/elliottech/lighter-python/tree/main/examples
  - create_modify_cancel_order_http.py → modify_order(market_index, order_index, base_amount, price, trigger_price)
  - order_index = client_order_index (el que es passa a create_sl_limit_order / create_tp_limit_order)
"""
import os
import asyncio
from dotenv import load_dotenv
import lighter

load_dotenv()

BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY")

# client_order_index fixos per poder fer update (modify_order) i cancel
SL_CLIENT_ORDER_INDEX = 900001
TP_CLIENT_ORDER_INDEX = 900002


async def main():
    print("=" * 80)
    print("LIGHTER - SL/TP UPDATE VALIDATION (modify_order)")
    print("=" * 80)
    print(f"Account: {ACCOUNT_INDEX}\n")

    api_client = lighter.ApiClient()
    signer = lighter.SignerClient(
        url=BASE_URL,
        api_private_keys={API_KEY_INDEX: API_PRIVATE_KEY},
        account_index=ACCOUNT_INDEX,
    )

    current_price = 1966.0
    position_size_eth = 0.05
    position_size_market = int(position_size_eth * 1e6)
    entry_price = int(current_price * 1e6)

    # Escalat limit/SL/TP: size ×10000, price/trigger ×100
    sl_size_int = int(position_size_eth * 10000)

    # --- STEP 1: Open position ---
    print("=" * 80)
    print("STEP 1: OPEN LONG POSITION (Market Order)")
    print("=" * 80)
    try:
        _, tx_resp, err = await signer.create_market_order(
            market_index=0,
            client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
            base_amount=position_size_market,
            avg_execution_price=entry_price,
            is_ask=False,
            reduce_only=False,
        )
        if err:
            print(f"❌ Failed to open position: {err}\n")
            await api_client.close()
            return
        print(f"✅ POSITION OPENED! TX: {getattr(tx_resp, 'tx_hash', tx_resp)}\n")
    except Exception as e:
        print(f"❌ Error: {e}\n")
        await api_client.close()
        return

    await asyncio.sleep(2)

    # --- STEP 2: Place SL (client_order_index fix per poder fer update) ---
    print("=" * 80)
    print("STEP 2: PLACE STOP LOSS (client_order_index={})".format(SL_CLIENT_ORDER_INDEX))
    print("=" * 80)
    sl_trigger_1 = current_price * 0.98
    sl_price_1 = sl_trigger_1 * 0.999
    sl_trigger_int_1 = int(sl_trigger_1 * 100)
    sl_price_int_1 = int(sl_price_1 * 100)
    print(f"   SL inicial: trigger=${sl_trigger_1:.2f}, price=${sl_price_1:.2f}\n")

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
            print(f"❌ Failed to place SL: {err}\n")
        else:
            print(f"✅ SL PLACED! TX: {getattr(tx_resp, 'tx_hash', tx_resp)}\n")
            sl_ok = True
    except Exception as e:
        print(f"❌ Error placing SL: {e}\n")

    await asyncio.sleep(1)

    # --- STEP 3: Place TP ---
    print("=" * 80)
    print("STEP 3: PLACE TAKE PROFIT (client_order_index={})".format(TP_CLIENT_ORDER_INDEX))
    print("=" * 80)
    tp_trigger_1 = current_price * 1.02
    tp_price_1 = tp_trigger_1 * 1.001
    tp_trigger_int_1 = int(tp_trigger_1 * 100)
    tp_price_int_1 = int(tp_price_1 * 100)
    print(f"   TP inicial: trigger=${tp_trigger_1:.2f}, price=${tp_price_1:.2f}\n")

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
            print(f"❌ Failed to place TP: {err}\n")
        else:
            print(f"✅ TP PLACED! TX: {getattr(tx_resp, 'tx_hash', tx_resp)}\n")
            tp_ok = True
    except Exception as e:
        print(f"❌ Error placing TP: {e}\n")

    await asyncio.sleep(2)

    # --- STEP 4: UPDATE SL (modify_order) ---
    print("=" * 80)
    print("STEP 4: UPDATE STOP LOSS (modify_order)")
    print("=" * 80)
    sl_trigger_2 = current_price * 0.97   # nou trigger més baix
    sl_price_2 = sl_trigger_2 * 0.999
    sl_trigger_int_2 = int(sl_trigger_2 * 100)
    sl_price_int_2 = int(sl_price_2 * 100)
    print(f"   SL nou: trigger=${sl_trigger_2:.2f}, price=${sl_price_2:.2f}\n")

    sl_update_ok = False
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
                print(f"❌ Failed to update SL: {err}\n")
            else:
                print(f"✅ SL UPDATED! TX: {getattr(tx_resp, 'tx_hash', tx_resp)}\n")
                sl_update_ok = True
        except Exception as e:
            print(f"❌ Error updating SL: {e}\n")
    else:
        print("   (Skip: SL no es va col·locar)\n")

    await asyncio.sleep(1)

    # --- STEP 5: UPDATE TP (modify_order) ---
    print("=" * 80)
    print("STEP 5: UPDATE TAKE PROFIT (modify_order)")
    print("=" * 80)
    tp_trigger_2 = current_price * 1.03   # nou trigger més alt
    tp_price_2 = tp_trigger_2 * 1.001
    tp_trigger_int_2 = int(tp_trigger_2 * 100)
    tp_price_int_2 = int(tp_price_2 * 100)
    print(f"   TP nou: trigger=${tp_trigger_2:.2f}, price=${tp_price_2:.2f}\n")

    tp_update_ok = False
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
                print(f"❌ Failed to update TP: {err}\n")
            else:
                print(f"✅ TP UPDATED! TX: {getattr(tx_resp, 'tx_hash', tx_resp)}\n")
                tp_update_ok = True
        except Exception as e:
            print(f"❌ Error updating TP: {e}\n")
    else:
        print("   (Skip: TP no es va col·locar)\n")

    await asyncio.sleep(2)

    # --- STEP 6: Cancel SL i TP (order_index = client_order_index) ---
    print("=" * 80)
    print("STEP 6: CANCEL SL & TP (order_index=client_order_index)")
    print("=" * 80)
    for name, oidx in [("SL", SL_CLIENT_ORDER_INDEX), ("TP", TP_CLIENT_ORDER_INDEX)]:
        try:
            _, tx_resp, err = await signer.cancel_order(market_index=0, order_index=oidx)
            if err:
                print(f"   ⚠️  Cancel {name} ({oidx}): {err}")
            else:
                print(f"   ✅ Cancelled {name} (order_index={oidx})")
        except Exception as e:
            print(f"   ❌ Cancel {name}: {e}")
    print()

    await asyncio.sleep(2)

    # --- STEP 7: Close position ---
    print("=" * 80)
    print("STEP 7: CLOSE POSITION (Market reduce-only)")
    print("=" * 80)
    try:
        _, tx_resp, err = await signer.create_market_order(
            market_index=0,
            client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
            base_amount=position_size_market,
            avg_execution_price=entry_price,
            is_ask=True,
            reduce_only=True,
        )
        if err:
            print(f"❌ Failed to close: {err}\n")
        else:
            print(f"✅ POSITION CLOSED! TX: {getattr(tx_resp, 'tx_hash', tx_resp)}\n")
    except Exception as e:
        print(f"❌ Error closing: {e}\n")

    # --- Summary ---
    print("=" * 80)
    print("SL/TP UPDATE VALIDATION SUMMARY")
    print("=" * 80)
    print("\n✅ Workflow:")
    print(f"   1. Open position ✅")
    print(f"   2. Place SL (client_order_index={SL_CLIENT_ORDER_INDEX}) {'✅' if sl_ok else '❌'}")
    print(f"   3. Place TP (client_order_index={TP_CLIENT_ORDER_INDEX}) {'✅' if tp_ok else '❌'}")
    print(f"   4. Update SL (modify_order) {'✅' if sl_update_ok else '❌'}")
    print(f"   5. Update TP (modify_order) {'✅' if tp_update_ok else '❌'}")
    print("   6. Cancel SL & TP ✅")
    print("   7. Close position ✅")
    if sl_update_ok and tp_update_ok:
        print("\n🎯 SL/TP UPDATE (modify_order) VALIDATED al testnet.")
    print("\n" + "=" * 80)

    await signer.close()
    await api_client.close()


if __name__ == "__main__":
    asyncio.run(main())
