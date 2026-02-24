#!/usr/bin/env python3
"""
Obrir una posició a Ostium (EURUSD per defecte, com els scripts del lab), esperar N s i tancar-la.

Reutilitza OstiumExecutionAdapter (com run_ostium_live_smoke.sh i test_full_cycle_multicall).
Flux: open → (client espera/reintenta trobar el trade) → wait → close.

Ús (des del directori arrel del projecte):
  ./test.sh lab/ostium/scripts/open_wait_close_btc.py
  ./test.sh lab/ostium/scripts/open_wait_close_btc.py --symbol EURUSD --wait 15 --collateral 5 --leverage 2

Requereix .env amb PRIVATE_KEY o OSTIUM_PRIVATE_KEY (testnet).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(REPO_ROOT / "lab" / "ostium" / ".env")
except ImportError:
    pass


async def main():
    parser = argparse.ArgumentParser(
        description="Obrir posició Ostium → esperar N s → tancar (lab/testnet)"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="EURUSD",
        help="Símbol (default: EURUSD; lab testnet validat amb EURUSD)",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=10.0,
        metavar="SECS",
        help="Segons entre open i close (default: 10)",
    )
    parser.add_argument(
        "--collateral",
        type=float,
        default=5.0,
        metavar="USDC",
        help="Collateral USDC (default: 5)",
    )
    parser.add_argument(
        "--leverage",
        type=float,
        default=2.0,
        metavar="X",
        help="Leverage (default: 2)",
    )
    parser.add_argument(
        "--long",
        action="store_true",
        default=True,
        help="Obrir LONG (default)",
    )
    parser.add_argument(
        "--short",
        action="store_true",
        help="Obrir SHORT",
    )
    parser.add_argument(
        "--network",
        type=str,
        default="testnet",
        choices=["testnet", "mainnet"],
    )
    args = parser.parse_args()

    is_long = not args.short

    pk = (os.getenv("OSTIUM_PRIVATE_KEY") or os.getenv("PRIVATE_KEY") or "").strip()
    if not pk:
        print("❌ Configura OSTIUM_PRIVATE_KEY o PRIVATE_KEY al .env (lab/ostium o arrel)")
        sys.exit(1)
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

    _ = await adapter.health_check()

    symbol = args.symbol.upper().replace("/", "")
    print(f"📋 Open → wait {args.wait}s → close")
    print(f"   Símbol: {symbol}  {'LONG' if is_long else 'SHORT'}  {args.collateral} USDC @ {args.leverage}x")
    print()

    print(f"1️⃣  Obrint posició {symbol}...")
    result = await adapter.open_position(
        symbol=symbol,
        is_long=is_long,
        collateral=args.collateral,
        leverage=args.leverage,
    )
    if not result.success:
        print(f"❌ open_position falla: {result.error_message}")
        sys.exit(1)
    position_id = result.position_id
    print(f"   ✅ Oberta: {position_id}  TX: {result.tx_hash}  preu: {result.executed_price}")
    print()

    print(f"2️⃣  Esperant {args.wait} segons...")
    await asyncio.sleep(args.wait)
    print(f"   ✅ Fi espera")
    print()

    print(f"3️⃣  Tancant posició {position_id}...")
    ok = await adapter.close_position(position_id)
    if not ok:
        print(f"❌ close_position falla per {position_id}")
        sys.exit(1)
    print(f"   ✅ Tancada")
    print()
    print("✅ Open → wait → close completat.")


if __name__ == "__main__":
    asyncio.run(main())
