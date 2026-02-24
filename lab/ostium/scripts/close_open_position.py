#!/usr/bin/env python3
"""
Tancar una posició oberta a Ostium (conta test / lab).

Aprenent del codi: test_full_cycle_no_subgraph.py (getOpenTrade, close_trade)
i OstiumExecutionAdapter (get_open_positions, close_position).

Ús (des del directori arrel del projecte; cal dependències: pip install -r requirements.txt):
  PYTHONPATH=. python3 lab/ostium/scripts/close_open_position.py --symbol BTCUSD
  PYTHONPATH=. python3 lab/ostium/scripts/close_open_position.py --symbol BTCUSD --dry-run
  PYTHONPATH=. python3 lab/ostium/scripts/close_open_position.py --all

Alternativa amb Docker (com run_ostium_live_smoke.sh):
  docker run --rm -v $(pwd):/app -w /app -e OSTIUM_PRIVATE_KEY=0x... --env-file .env \\
    python:3.11-slim bash -c "pip install -q -r requirements.txt && PYTHONPATH=/app python3 lab/ostium/scripts/close_open_position.py --symbol BTCUSD"

Requereix .env amb PRIVATE_KEY o OSTIUM_PRIVATE_KEY (testnet).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Permetre importar des del repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Carregar .env (lab/ostium o repo root)
try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(REPO_ROOT / "lab" / "ostium" / ".env")
except ImportError:
    pass


async def main():
    parser = argparse.ArgumentParser(description="Tancar posició oberta Ostium (lab/testnet)")
    parser.add_argument("--symbol", type=str, help="Símbol a tancar (ex: BTCUSD, EURUSD)")
    parser.add_argument("--all", action="store_true", help="Tancar totes les posicions obertes")
    parser.add_argument("--dry-run", action="store_true", help="Només llistar, no tancar")
    parser.add_argument("--network", type=str, default="testnet", choices=["testnet", "mainnet"])
    args = parser.parse_args()

    if not args.symbol and not args.all:
        parser.error("Indica --symbol SYMBOL o --all")

    pk = (os.getenv("OSTIUM_PRIVATE_KEY") or os.getenv("PRIVATE_KEY") or "").strip()
    if not pk:
        print("❌ Configura OSTIUM_PRIVATE_KEY o PRIVATE_KEY al .env (lab/ostium o arrel)")
        sys.exit(1)
    # Normalitzar: treure cometes si el .env tenia PRIVATE_KEY="0x..."
    if pk.startswith('"') and pk.endswith('"'):
        pk = pk[1:-1].strip()
    if pk.startswith("'") and pk.endswith("'"):
        pk = pk[1:-1].strip()

    from infrastructure.venues.ostium.ostium_execution_adapter import OstiumExecutionAdapter

    adapter = OstiumExecutionAdapter(private_key=pk, network=args.network)
    await adapter.start()

    if adapter._client is None:
        print("❌ Adapter no inicialitzat (revisa clau i xarxa)")
        sys.exit(1)

    # Escalfar el client (assegura _trader_address al client)
    _ = await adapter.health_check()

    print("📋 Posicions obertes:")
    positions = await adapter.get_open_positions()
    if not positions:
        print("   Cap posició oberta.")
        return

    for p in positions:
        side = "LONG" if p.is_long else "SHORT"
        print(f"   {p.venue_position_id}  {p.symbol} {side}  collateral={p.collateral}  leverage={p.leverage}")

    to_close = []
    if args.all:
        to_close = positions
    else:
        sym = args.symbol.upper().replace("/", "")
        to_close = [p for p in positions if p.symbol == sym]
        if not to_close:
            print(f"   Cap posició oberta per {args.symbol}")
            return

    if args.dry_run:
        print(f"\n[--dry-run] Es tancarien {len(to_close)} posició(s). Torna a executar sense --dry-run.")
        return

    print(f"\n🔴 Tancant {len(to_close)} posició(s)...")
    for p in to_close:
        pid = p.venue_position_id
        ok = await adapter.close_position(pid)
        if ok:
            print(f"   ✅ Tancada: {pid}")
        else:
            print(f"   ❌ Error tancant: {pid}")
    print("   Fi.")


if __name__ == "__main__":
    asyncio.run(main())
