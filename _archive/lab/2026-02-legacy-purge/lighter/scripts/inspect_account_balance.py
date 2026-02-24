#!/usr/bin/env python3
"""
Lighter - Inspect account structure for get_balance() (M2)

Obté account via REST (httpx) o SDK i imprimeix l'estructura de accounts[0]:
- assets[] (per mapar USDC / available / used)
- total_asset_value
- available_balance, collateral (si existeixen)

Ús: des de l'arrel del projecte
  python3 lab/lighter/scripts/inspect_account_balance.py
  o  ./test.sh lab/lighter/scripts/inspect_account_balance.py

Si no tens LIGHTER_L1_ADDRESS al .env, el script mostra l'estructura esperada i surt 0.
Sortida: consola + lab/out/account_structure.json (quan hi ha dades).
"""

import json
import os
import sys
from pathlib import Path

# Arrel projecte (per lab/out)
ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "lab" / "lighter" / ".env")
    load_dotenv(ROOT / ".env")
except Exception:
    pass

BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai").rstrip("/")
L1_ADDRESS = os.getenv("LIGHTER_L1_ADDRESS")


def _obj_to_dict(obj):
    """Convert SDK/openapi object to dict for JSON."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _obj_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_obj_to_dict(x) for x in obj]
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        return {k: _obj_to_dict(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    if hasattr(obj, "attribute_map"):
        return {k: _obj_to_dict(getattr(obj, k, None)) for k in obj.attribute_map}
    return obj


def fetch_via_httpx():
    """Fetch account via REST (no SDK)."""
    try:
        import httpx
    except ImportError:
        return None, "httpx no instal·lat (pip install httpx)"
    url = f"{BASE_URL}/api/v1/account"
    params = {"by": "l1_address", "value": L1_ADDRESS}
    try:
        r = httpx.get(url, params=params, timeout=15.0)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return None, str(e)
    if data.get("code") != 200:
        return None, f"code={data.get('code')} message={data.get('message', '')}"
    accounts = data.get("accounts") or []
    if not accounts:
        return None, "cap account al response"
    return accounts[0], None


async def fetch_via_sdk():
    """Fetch account via Lighter SDK (AccountApi)."""
    try:
        import lighter
    except ImportError:
        return None, "lighter-sdk no instal·lat"
    try:
        cfg = lighter.Configuration(host=BASE_URL)
        client = lighter.ApiClient(cfg)
        api = lighter.AccountApi(client)
        resp = await api.account(by="l1_address", value=L1_ADDRESS)
        await client.close()
    except Exception as e:
        return None, str(e)
    accounts = getattr(resp, "accounts", []) or []
    if not accounts:
        return None, "cap account al response"
    acc = accounts[0]
    return _obj_to_dict(acc) if hasattr(acc, "__dict__") or hasattr(acc, "to_dict") else acc, None


def main():
    print("=" * 70)
    print("LIGHTER – Account structure (per get_balance M2)")
    print("=" * 70)

    if not L1_ADDRESS:
        print("\n⚠️  LIGHTER_L1_ADDRESS no definit al .env")
        print("   Defineix L1_ADDRESS i torna a executar per veure l'estructura real.")
        print("\n   Estructura esperada (font: LIGHTER_COMPLETE_VALIDATION.md):")
        print('   accounts[0]: { "index", "l1_address", "positions", "assets", "total_asset_value" }')
        print("   Per get_balance(): usar total_asset_value com a equity; si assets[] té items")
        print("   amb symbol/asset_id, buscar USDC per available/balance.")
        return 0

    acc = None
    err = None
    acc, err = fetch_via_httpx()
    if acc is None and err and "httpx" in err:
        import asyncio
        acc, err = asyncio.run(fetch_via_sdk())
    if acc is None:
        print(f"\n❌ Error: {err}")
        return 1

    # Normalitzar a dict si és objecte SDK
    if not isinstance(acc, dict):
        acc = _obj_to_dict(acc) or {}

    print("\n✅ Account obtingut")
    print(f"   Keys a accounts[0]: {list(acc.keys())}")

    total = acc.get("total_asset_value")
    print(f"\n   total_asset_value: {total!r}")

    assets = acc.get("assets") or []
    print(f"\n   assets: len={len(assets)}")
    if assets:
        for i, a in enumerate(assets):
            if isinstance(a, dict):
                print(f"      [{i}] keys: {list(a.keys())}  values: {a}")
            else:
                a_dict = _obj_to_dict(a)
                print(f"      [{i}] {type(a).__name__}: {a_dict!r}")
    else:
        print("      (buida o no present)")

    for key in ("available_balance", "collateral", "balance", "margin", "equity"):
        if key in acc:
            print(f"\n   {key}: {acc[key]!r}")

    out_dir = ROOT / "lab" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "account_structure.json"
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(acc, f, indent=2)
        print(f"\n   Guardat: {out_file}")
    except Exception as e:
        print(f"\n   No s'ha pogut escriure {out_file}: {e}")

    print("\n" + "=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
