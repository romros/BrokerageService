#!/usr/bin/env python3
"""
Cancel·la TOTES les ordres obertes del compte al testnet Lighter.
Fet servir quan la UI mostra "Open Orders (N)" i vols buidar tot.
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


async def main():
    print("=" * 80)
    print("LIGHTER - Cancel·lar TOTES les ordres obertes")
    print("=" * 80)
    print(f"Account: {ACCOUNT_INDEX}\n")

    api_client = lighter.ApiClient()
    signer = lighter.SignerClient(
        url=BASE_URL,
        api_private_keys={API_KEY_INDEX: API_PRIVATE_KEY},
        account_index=ACCOUNT_INDEX,
    )

    # Cancel All: IMMEDIATE = executar ara. "CancelAllTime should be nil" → timestamp 0
    try:
        _, tx_resp, err = await signer.cancel_all_orders(
            time_in_force=signer.CANCEL_ALL_TIF_IMMEDIATE,
            timestamp_ms=0,  # nil per cancel·lació immediata
        )
        if err:
            print(f"❌ Error: {err}\n")
        else:
            print(f"✅ Cancel·lades totes les ordres.")
            print(f"   TX: {getattr(tx_resp, 'tx_hash', tx_resp)}\n")
    except Exception as e:
        print(f"❌ Exception: {e}\n")

    await signer.close()
    await api_client.close()
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
