"""
M3.6 Real Paper E2E "Trading sanity" — 1 trade tiny + verificacions.

Flux: start → get_balance → get_open_positions → open → (optional SL/TP) → close → assert 0 positions.
Sempre adapter.stop() al finally. Cleanup best-effort si falla open/close.

Use: python -m application.e2e_trade --venue lighter --mode PAPER
     python -m application.e2e_trade --venue lighter --mode PAPER --symbol ETH --collateral 100 --leverage 20

Output canònic grepejable: E2E_TRADE step=... status=OK|FAILED
"""

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

from foundation.logging import get_logger

logger = get_logger(__name__)


class _Tee:
    """Write to both original stream and a file (for evidence log)."""

    def __init__(self, stream: "TextIO", path: str):
        self._stream = stream
        self._file: Optional[TextIO] = None
        self._path = path

    def start(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "w", encoding="utf-8")

    def stop(self) -> None:
        if self._file:
            self._file.close()
            self._file = None

    def write(self, data: str) -> int:
        self._stream.write(data)
        if self._file:
            self._file.write(data)
        return len(data)

    def flush(self) -> None:
        self._stream.flush()
        if self._file:
            self._file.flush()

# Greppable canonical lines
E2E_PREFIX = "E2E_TRADE "

# Defaults: testnet ETH/BTC, collateral 100, leverage 20
DEFAULT_SYMBOL = "ETH"
DEFAULT_COLLATERAL = 100.0
DEFAULT_LEVERAGE = 20.0
DEFAULT_TIMEOUT_S = 60
POLL_POSITION_INTERVAL_S = 2.0
POLL_POSITION_MAX_WAIT_S = 30.0
DEFAULT_SETTLE_TIMEOUT_S = 120.0  # testnet latències; P0.2
DEFAULT_POLL_S = 2.0
SIZE_EPSILON = 1e-6  # positions amb abs(notional) < aquest valor es consideren flat


def _emit(step: str, status: str, detail: str = "") -> None:
    line = f"{E2E_PREFIX}step={step} status={status}"
    if detail:
        line += f" {detail}"
    print(line, flush=True)


def _emit_result(ok: bool, error: Optional[str] = None) -> None:
    status = "OK" if ok else "FAILED"
    line = f"{E2E_PREFIX}result={status}"
    if error:
        line += f" error={error}"
    print(line, flush=True)


def _position_size(p) -> float:
    """Size of position (abs notional); 0 if notional missing."""
    n = getattr(p, "notional", None)
    return abs(float(n)) if n is not None else 0.0


async def _wait_until_flat(
    adapter,
    symbol: str,
    timeout_s: float,
    poll_s: float,
) -> tuple[bool, list]:
    """
    Poll until no positions for symbol (or all have size≈0).
    Returns (ok, positions_for_symbol) — ok=True if flat.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        positions = await adapter.get_open_positions()
        for_symbol = [p for p in positions if p.symbol == symbol or symbol in p.symbol]
        # Consider flat if none, or all have size ≈ 0
        non_flat = [p for p in for_symbol if _position_size(p) >= SIZE_EPSILON]
        if not non_flat:
            return True, for_symbol
        await asyncio.sleep(poll_s)
    return False, [p for p in await adapter.get_open_positions() if p.symbol == symbol or symbol in p.symbol]


async def _run_e2e(
    adapter,
    symbol: str,
    collateral: float,
    leverage: float,
    sl_price: Optional[float],
    tp_price: Optional[float],
    timeout_s: float,
    mode: str,
    settle_timeout_s: float,
    poll_s: float,
) -> bool:
    """Run single E2E trade: open → optional SL/TP → close. Returns True if OK."""
    close_id: Optional[str] = None
    opened = False

    try:
        # Guards: LIVE mode requires ENABLE_LIVE_TRADING
        if str(mode).upper() == "LIVE":
            from application.services.live_guards import (
                assert_live_trading_enabled,
                assert_risk_limits_ok,
            )
            assert_live_trading_enabled(mode)
            positions_before = await adapter.get_open_positions()
            notional = collateral * leverage
            assert_risk_limits_ok(positions_before, notional)

        # Step: balance
        balance = await adapter.get_balance()
        logger.info(f"Balance: usdc={balance.usdc} available={balance.available_margin}")
        _emit("balance", "OK", f"usdc={balance.usdc}")

        # Step: positions before
        positions_before = await adapter.get_open_positions()
        logger.info(f"Open positions before: {len(positions_before)}")
        _emit("positions_before", "OK", f"count={len(positions_before)}")

        # Step: open
        client_order_id = f"e2e_{int(time.time() * 1000)}"
        result = await adapter.open_position(
            symbol=symbol,
            is_long=True,
            collateral=collateral,
            leverage=leverage,
            sl_price=sl_price,
            tp_price=tp_price,
            client_order_id=client_order_id,
        )
        if not result.success:
            _emit("open", "FAILED", f"result={result}")
            return False

        opened = True
        close_id = result.position_id
        logger.info(f"Opened order_id={result.order_id} position_id={result.position_id}")

        # Poll until position visible (close_position needs it in get_open_positions)
        ids_before = {p.position_id for p in positions_before}
        deadline = time.monotonic() + min(POLL_POSITION_MAX_WAIT_S, timeout_s - 5)
        while time.monotonic() < deadline:
            positions = await adapter.get_open_positions()
            for p in positions:
                if (p.symbol == symbol or symbol in p.symbol) and p.position_id not in ids_before:
                    break
            else:
                await asyncio.sleep(POLL_POSITION_INTERVAL_S)
                continue
            break
        else:
            logger.warning("Position not visible after poll; attempting close anyway")

        canonical_id = result.position_id
        tx_hash = getattr(result, "tx_hash", None) or ""

        open_detail = f"order_id={result.order_id} position_id={canonical_id}"
        if tx_hash:
            open_detail += f" tx_hash={tx_hash}"
        _emit("open", "OK", open_detail)
        # Explorer: per anar al bloc/hash (Lighter testnet)
        if tx_hash and symbol:
            acc = os.getenv("LIGHTER_ACCOUNT_INDEX", "")
            if acc:
                _emit("explorer", "OK", f"url=https://testnet.app.lighter.xyz/explorer/accounts/{acc}")

        # Step: close
        closed = await adapter.close_position(close_id, percent=100.0)
        if not closed:
            _emit("close", "FAILED", f"position_id={canonical_id}")
            return False

        _emit("close", "OK", f"position_id={canonical_id}")

        # Step: wait until flat (settle) — robust against eventual consistency
        flat_ok, positions_for_symbol = await _wait_until_flat(
            adapter, symbol, timeout_s=settle_timeout_s, poll_s=poll_s
        )
        for_symbol = [p for p in positions_for_symbol if _position_size(p) >= SIZE_EPSILON]
        count_non_flat = len(for_symbol)

        # P0.2: si timeout, force_close_remaining (close_position per cada pair_id restant) + retry
        if not flat_ok and count_non_flat > 0:
            pair_ids = list({p.pair_id for p in for_symbol})
            _emit("force_close", "OK", f"retrying {len(pair_ids)} position(s)")
            for pair_id in pair_ids:
                try:
                    await adapter.close_position(f"lighter:{pair_id}", percent=100.0)
                except Exception as e:
                    logger.warning("force_close lighter:%s failed: %s", pair_id, e)
            flat_ok, positions_for_symbol = await _wait_until_flat(
                adapter, symbol, timeout_s=settle_timeout_s, poll_s=poll_s
            )
            for_symbol = [p for p in positions_for_symbol if _position_size(p) >= SIZE_EPSILON]
            count_non_flat = len(for_symbol)

        if not flat_ok or count_non_flat > 0:
            dump = "; ".join(
                f"id={p.position_id} size={_position_size(p):.4f} is_long={p.is_long}"
                for p in for_symbol[:5]
            )
            _emit(
                "positions_after",
                "FAILED",
                f"expected 0 for {symbol}, got {count_non_flat} (settle timeout) {dump}",
            )
            return False

        _emit("positions_after", "OK", "count=0")
        return True

    except Exception as e:
        logger.exception("E2E trade failed: %s", e)
        _emit("error", "FAILED", str(e))
        # Best-effort cleanup: close if we opened
        if opened:
            cleanup_id = close_id
            if not cleanup_id:
                # Try to find new position by symbol and close it
                try:
                    ids_before = {p.position_id for p in positions_before}
                    positions = await adapter.get_open_positions()
                    for p in positions:
                        if (p.symbol == symbol or symbol in p.symbol) and p.position_id not in ids_before:
                            cleanup_id = f"lighter:{p.pair_id}"
                            break
                except Exception:
                    pass
            if cleanup_id:
                try:
                    await adapter.close_position(cleanup_id, percent=100.0)
                    logger.info("Cleanup: closed position %s", cleanup_id)
                except Exception as cleanup_e:
                    logger.warning("Cleanup close failed: %s", cleanup_e)
        return False


def _build_adapter(venue: str):
    """Build venue adapter. Raises if unsupported."""
    if venue == "lighter":
        # Lazy: evita carregar lighter si --venue mock
        from infrastructure.builders.lighter_di import build_lighter_paper_adapter
        return build_lighter_paper_adapter()
    raise ValueError(f"Unsupported venue: {venue} (use lighter)")


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E trade sanity: open → close, 0 positions at end")
    parser.add_argument("--venue", default=os.getenv("VENUE", "lighter"), help="Venue (lighter)")
    parser.add_argument("--mode", default=os.getenv("MODE", "PAPER"), help="Mode (PAPER | LIVE)")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="Symbol (default ETH)")
    parser.add_argument("--collateral", type=float, default=DEFAULT_COLLATERAL, help="Collateral USDC (default 100)")
    parser.add_argument("--leverage", type=float, default=DEFAULT_LEVERAGE, help="Leverage (default 20)")
    parser.add_argument("--sl", type=float, default=None, help="Stop loss price (optional)")
    parser.add_argument("--tp", type=float, default=None, help="Take profit price (optional)")
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S, dest="timeout_s", help="Max seconds for whole run (default 60)")
    parser.add_argument("--settle-timeout-s", type=float, default=DEFAULT_SETTLE_TIMEOUT_S, dest="settle_timeout_s", help="Max seconds to wait for flat after close (default 120)")
    parser.add_argument("--poll-s", type=float, default=DEFAULT_POLL_S, dest="poll_s", help="Poll interval for settle wait (default 2)")
    parser.add_argument("--log-path", type=str, default=None, dest="log_path", help="Write output to file (default: datafiles/e2e_runs/<ts>_<venue>_<symbol>.log)")
    args = parser.parse_args()

    # Log file: explicit path or default for evidence
    if args.log_path:
        log_path = args.log_path
    else:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        log_path = f"datafiles/e2e_runs/{ts}_{args.venue}_{args.symbol}.log"
    tee_stdout = _Tee(sys.stdout, log_path)
    tee_stderr = _Tee(sys.stderr, log_path)
    tee_stdout.start()
    tee_stderr.start()
    sys.stdout = tee_stdout
    sys.stderr = tee_stderr

    adapter = None
    try:
        adapter = _build_adapter(args.venue)
    except Exception as e:
        logger.exception("Failed to build adapter: %s", e)
        _emit_result(False, str(e))
        return 1

    async def _run():
        try:
            await adapter.start()
            ok = await _run_e2e(
                adapter,
                symbol=args.symbol,
                collateral=args.collateral,
                leverage=args.leverage,
                sl_price=args.sl,
                tp_price=args.tp,
                timeout_s=args.timeout_s,
                mode=args.mode,
                settle_timeout_s=args.settle_timeout_s,
                poll_s=args.poll_s,
            )
            _emit_result(ok)
            return 0 if ok else 1
        finally:
            await adapter.stop()

    try:
        return asyncio.run(_run())
    except Exception as e:
        logger.exception("E2E trade crashed: %s", e)
        _emit_result(False, str(e))
        return 1
    finally:
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        tee_stdout.stop()
        tee_stderr.stop()


if __name__ == "__main__":
    sys.exit(main())
