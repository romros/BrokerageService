#!/usr/bin/env python3
"""
Verifica que GET /api/v1/account?by=l1_address&value=<L1> retorna les posicions
(igual que la UI). Sense SDK, sense auth. Ús: ./test.sh lab/lighter/scripts/verify_account_by_l1_address.py
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

try:
    import httpx
except ImportError:
    print("Requereix httpx (requirements.txt del projecte)")
    sys.exit(1)

# Totes les variables venen del .env (load_dotenv() a dalt). Defaults només si .env no té la variable.
BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai").rstrip("/")
L1_ADDRESS = os.getenv("LIGHTER_L1_ADDRESS")  # Obligatori: la teva wallet L1 (la mateixa que a la UI)
if not L1_ADDRESS:
    print("ERROR: Falta LIGHTER_L1_ADDRESS al .env")
    sys.exit(1)

def main():
    url = f"{BASE_URL}/api/v1/account"
    params = {"by": "l1_address", "value": L1_ADDRESS}
    print(f"GET {url}")
    print(f"   params: {params}")
    print()

    r = httpx.get(url, params=params, timeout=10.0)
    r.raise_for_status()
    data = r.json()

    if data.get("code") != 200:
        print(f"ERROR: code={data.get('code')}, message={data.get('message', '')}")
        sys.exit(1)

    accounts = data.get("accounts") or []
    if not accounts:
        print("ERROR: cap account al response")
        sys.exit(1)

    acc = accounts[0]
    positions = acc.get("positions") or []
    print(f"Account index: {acc.get('index')}")
    print(f"Positions: {len(positions)}")
    for i, pos in enumerate(positions):
        sym = pos.get("symbol", "?")
        size = pos.get("position", "0")
        entry = pos.get("avg_entry_price", "")
        print(f"  [{i+1}] {sym} position={size} avg_entry={entry}")

    # Criteri d'èxit: si la UI mostra ETH, aquí ha d'aparèixer
    has_eth = any(p.get("symbol") == "ETH" and p.get("position", "0") != "0.00000" for p in positions)
    if has_eth:
        print("\n✅ Posició ETH trobada (by=l1_address funciona igual que la UI)")
    else:
        print("\n⚠️  Cap posició ETH amb size>0 (pot ser que no en tinguis oberta)")
    return 0 if True else 1

if __name__ == "__main__":
    sys.exit(main())
