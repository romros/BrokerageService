"""
Freqtrade-like runner — PAPER DONE handshake (AGENTS §2.6)

Client pur HTTP: llegeix candles, preu, obre/tanca posicions paper via API.
Assumeix broker en marxa amb pipeline actiu (com docker-compose.soak.yml).

Ús:
  python -m application.tools.freqtrade_runner --venue lighter --mode PAPER --symbol ETH --minutes 15
  python -m application.tools.freqtrade_runner --broker-url http://localhost:8000 --minutes 2
  # En background: afegir & al final, o --position-poll-s 30 per veure PnL cada 30s (per defecte)

Log: datafiles/freqtrade_runs/<timestamp>_<symbol>_<minutes>.log
Output canònic: FREQTRADE_RUNNER step=... status=OK|FAILED
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    import requests
except ImportError:
    print("requests package required: pip install requests")
    sys.exit(1)

PREFIX = "FREQTRADE_RUNNER "
CANDLE_INTERVAL_S = 60
# Des de dins Docker Compose: BROKER_URL=http://brokerage:8000 (broker ha d'estar en marxa)
DEFAULT_BROKER_URL = "http://localhost:8000"
DEFAULT_SYMBOL = "ETH"
DEFAULT_MINUTES = 15
DEFAULT_POLL_S = 2
DEFAULT_POSITION_POLL_S = 30  # Cada quant consultar PnL de la posició oberta
DEFAULT_OPEN_EVERY_MINUTES = 3
DEFAULT_COLLATERAL = 100.0
DEFAULT_LEVERAGE = 20.0


def _emit(step: str, status: str, detail: str = "", log_path: Optional[Path] = None) -> None:
    line = f"{PREFIX}step={step} status={status}"
    if detail:
        line += f" {detail}"
    print(line, flush=True)
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def _log(msg: str, log_path: Optional[Path] = None) -> None:
    print(msg, flush=True)
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass


def _compute_missing_minutes(candles: list, log_path: Optional[Path] = None) -> int:
    """
    Compta minuts absents (gaps) sobre candles tancades.
    ts[i] - ts[i-1] == 60 → OK; altrament gap.
    Ignora última candle si és parcial (ts molt recent).
    """
    if len(candles) < 2:
        return 0
    ts_list = []
    for c in candles:
        ts = c.get("ts") if isinstance(c.get("ts"), (int, float)) else c.get("timestamp")
        if ts is not None:
            ts_list.append(float(ts))
    ts_list.sort()
    missing = 0
    for i in range(1, len(ts_list)):
        diff = ts_list[i] - ts_list[i - 1]
        if diff > CANDLE_INTERVAL_S:
            gaps = int((diff - CANDLE_INTERVAL_S) / CANDLE_INTERVAL_S) + 1
            missing += gaps
    return missing


def _percentile(sorted_list: list, p: float) -> float:
    if not sorted_list:
        return 0.0
    k = (len(sorted_list) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(sorted_list) - 1)
    return sorted_list[f] + (k - f) * (sorted_list[c] - sorted_list[f]) if f < len(sorted_list) - 1 else sorted_list[-1]


def run(
    broker_url: str,
    venue: str,
    symbol: str,
    minutes: float,
    poll_s: float,
    position_poll_s: float,
    open_every_minutes: int,
    collateral: float,
    leverage: float,
    log_path: Optional[Path] = None,
) -> tuple[int, dict]:
    """
    Executa el runner. Retorna (exit_code, summary_dict).
    """
    base = broker_url.rstrip("/")
    candles_read = 0
    opens = 0
    closes = 0
    positions_after = -1
    missing_minutes = 0
    latencies_ms: list[float] = []
    position_id: Optional[str] = None
    opened = False
    open_price: Optional[float] = None
    open_size: Optional[float] = None
    is_long = True  # freqtrade_runner obre sempre long
    realized_pnl: Optional[float] = None
    realized_pnl_pct: Optional[float] = None

    try:
        # Header inicial
        _log(f"\n{PREFIX}start broker_url={base} venue={venue} symbol={symbol} minutes={minutes} poll_s={poll_s}", log_path)
        mode_url = f"{base}/api/v1/broker/mode"
        try:
            t0 = time.perf_counter()
            r = requests.get(mode_url, timeout=5)
            latencies_ms.append((time.perf_counter() - t0) * 1000)
            if r.status_code == 200:
                data = r.json()
                _log(f"{PREFIX}mode={data.get('mode', '?')} market_data_env={data.get('market_data_env', '?')}", log_path)
        except Exception as e:
            _emit("mode", "FAILED", str(e), log_path)
            return 1, {}

        deadline = time.monotonic() + (minutes * 60)
        last_open_min = -999
        last_position_poll = 0.0
        candles_by_ts: dict[float, dict] = {}

        while time.monotonic() < deadline:
            # 1) Llegir candles
            ohlcv_url = f"{base}/api/v1/broker/ohlcv/{symbol}?tf=1m&limit=100"
            try:
                t0 = time.perf_counter()
                r = requests.get(ohlcv_url, timeout=5)
                latencies_ms.append((time.perf_counter() - t0) * 1000)
                if r.status_code == 200:
                    data = r.json()
                    candles = data.get("candles") or data.get("ohlcv") or []
                    if isinstance(candles, list):
                        for c in candles:
                            if isinstance(c, dict):
                                ts = c.get("ts") if isinstance(c.get("ts"), (int, float)) else c.get("timestamp")
                                if ts is not None:
                                    candles_by_ts[float(ts)] = c
                        candles_read = len(candles_by_ts)
            except Exception as e:
                _emit("ohlcv", "FAILED", str(e), log_path)

            # 2) Llegir preu
            price_url = f"{base}/api/v1/broker/price/latest?venue={venue}&symbol={symbol}"
            try:
                t0 = time.perf_counter()
                r = requests.get(price_url, timeout=5)
                latencies_ms.append((time.perf_counter() - t0) * 1000)
            except Exception:
                pass

            # 3) Open cada open_every_minutes
            elapsed_min = int((time.monotonic() - (deadline - minutes * 60)) / 60)
            if elapsed_min > last_open_min and elapsed_min >= 0 and (elapsed_min % open_every_minutes == 0 or opens == 0):
                last_open_min = elapsed_min
                if not opened:
                    open_url = f"{base}/api/v1/broker/orders/open"
                    body = {
                        "venue": venue,
                        "symbol": symbol,
                        "side": "long",
                        "collateral": collateral,
                        "leverage": leverage,
                    }
                    try:
                        t0 = time.perf_counter()
                        r = requests.post(open_url, json=body, timeout=15)
                        latencies_ms.append((time.perf_counter() - t0) * 1000)
                        if r.status_code == 200:
                            data = r.json()
                            position_id = data.get("position_id") or ""
                            open_price = data.get("executed_price")
                            open_size = data.get("executed_size")
                            opened = True
                            opens += 1
                            _emit("open", "OK", f"position_id={position_id}", log_path)
                        else:
                            _emit("open", "FAILED", f"status={r.status_code} {r.text[:200]}", log_path)
                    except Exception as e:
                        _emit("open", "FAILED", str(e), log_path)

            # 4) Si tenim posició oberta, cada position_poll_s consultar PnL
            now = time.monotonic()
            if opened and (now - last_position_poll) >= position_poll_s:
                last_position_poll = now
                pos_url = f"{base}/api/v1/broker/positions?venue={venue}"
                try:
                    r = requests.get(pos_url, timeout=5)
                    if r.status_code == 200:
                        data = r.json()
                        positions = data.get("positions") or []
                        for p in positions:
                            if p.get("symbol") == symbol:
                                mark = p.get("mark_price")
                                pnl = p.get("unrealized_pnl")
                                # Fallback: open_price/size si no vingueren del open
                                if open_price is None and p.get("open_price"):
                                    open_price = float(p["open_price"])
                                if open_size is None and p.get("open_price") and p.get("size"):
                                    open_size = float(p["size"])
                                _log(
                                    f"{PREFIX}position_pnl symbol={symbol} mark_price={mark} unrealized_pnl={pnl}",
                                    log_path,
                                )
                                break
                except Exception as e:
                    _log(f"{PREFIX}position_pnl error={e}", log_path)

            time.sleep(poll_s)

        # Cleanup: sempre tancar al final
        if opened and position_id:
            close_url = f"{base}/api/v1/broker/orders/close"
            body = {"venue": venue, "position_id": position_id, "percent": 100.0}
            try:
                t0 = time.perf_counter()
                r = requests.post(close_url, json=body, timeout=60)
                latencies_ms.append((time.perf_counter() - t0) * 1000)
                if r.status_code == 200:
                    closes += 1
                    _emit("close", "OK", f"position_id={position_id}", log_path)
                else:
                    _emit("close", "FAILED", f"status={r.status_code}", log_path)
            except Exception as e:
                _emit("close", "FAILED", str(e), log_path)

        # Esperar settle i verificar positions_after
        for _ in range(int(30 / poll_s)):
            time.sleep(poll_s)
            pos_url = f"{base}/api/v1/broker/positions?venue={venue}"
            try:
                r = requests.get(pos_url, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    positions = data.get("positions") or []
                    for_symbol = [p for p in positions if p.get("symbol") == symbol or symbol in str(p.get("symbol", ""))]
                    positions_after = len(for_symbol)
                    if positions_after == 0:
                        break
            except Exception:
                pass

        # PnL realitzat: obtenir close trade de GET /trades i comparar amb web
        if closes and open_price and open_size and open_size > 0:
            time.sleep(5)  # Marge per settle del trade (Lighter pot trigar)
            trades_url = f"{base}/api/v1/broker/trades?venue={venue}&symbol={symbol}&limit=20"
            try:
                r = requests.get(trades_url, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    trades = data.get("trades") or []
                    # Long close = sell; buscar el sell més recent
                    for t in trades:
                        if (t.get("side") or "").lower() == "sell":
                            close_price = t.get("price") or 0
                            if close_price > 0:
                                realized_pnl = (close_price - open_price) * open_size if is_long else (open_price - close_price) * open_size
                                # % ROI sobre margin (com la web: PnL / (notional/leverage) * 100)
                                notional = open_price * open_size
                                realized_pnl_pct = (realized_pnl * leverage / notional * 100) if notional and leverage else 0
                                _log(
                                    f"{PREFIX}closed_pnl realized_pnl=${realized_pnl:.2f} ({realized_pnl_pct:.2f}%) open={open_price} close={close_price}",
                                    log_path,
                                )
                                realized_pnl = round(realized_pnl, 2)
                                realized_pnl_pct = round(realized_pnl_pct, 2)
                            break
                    else:
                        _log(f"{PREFIX}closed_pnl no sell trade found (trades={len(trades)})", log_path)
                else:
                    _log(f"{PREFIX}closed_pnl trades status={r.status_code}", log_path)
            except Exception as e:
                _log(f"{PREFIX}closed_pnl error={e}", log_path)
        elif closes and (open_price is None or open_size is None or open_size <= 0):
            _log(f"{PREFIX}closed_pnl skip (open_price={open_price} open_size={open_size})", log_path)

        all_candles = list(candles_by_ts.values())
        missing_minutes = _compute_missing_minutes(all_candles, log_path)
        lat_sorted = sorted(latencies_ms) if latencies_ms else []
        p50 = _percentile(lat_sorted, 50)
        p95 = _percentile(lat_sorted, 95)

        summary = {
            "minutes_run": minutes,
            "candles_read": candles_read,
            "missing_minutes": missing_minutes,
            "opens": opens,
            "closes": closes,
            "positions_after": positions_after,
            "latency_p50_ms": round(p50, 1),
            "latency_p95_ms": round(p95, 1),
        }
        if realized_pnl is not None:
            summary["realized_pnl"] = realized_pnl
        if realized_pnl_pct is not None:
            summary["realized_pnl_pct"] = realized_pnl_pct
        _emit("result", "OK" if positions_after == 0 and candles_read >= 1 else "FAILED", f"positions_after={positions_after} candles={candles_read}", log_path)
        _log(f"{PREFIX}summary " + " ".join(f"{k}={v}" for k, v in sorted(summary.items())), log_path)
        return 0 if positions_after == 0 and candles_read >= 1 else 1, summary

    except Exception as e:
        _emit("error", "FAILED", str(e), log_path)
        if opened and position_id:
            try:
                b = broker_url.rstrip("/")
                close_url = f"{b}/api/v1/broker/orders/close"
                requests.post(close_url, json={"venue": venue, "position_id": position_id, "percent": 100.0}, timeout=30)
            except Exception:
                pass
        return 1, {"error": str(e)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Freqtrade-like runner (PAPER DONE handshake)")
    parser.add_argument("--broker-url", default=os.getenv("BROKER_URL", DEFAULT_BROKER_URL), help="Broker base URL")
    parser.add_argument("--venue", default="lighter")
    parser.add_argument("--mode", default="PAPER")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--minutes", type=float, default=DEFAULT_MINUTES)
    parser.add_argument("--poll-s", type=float, default=DEFAULT_POLL_S)
    parser.add_argument("--position-poll-s", type=float, default=DEFAULT_POSITION_POLL_S, help="Cada quant segons consultar PnL de la posició")
    parser.add_argument("--open-every-minutes", type=int, default=DEFAULT_OPEN_EVERY_MINUTES)
    parser.add_argument("--collateral", type=float, default=DEFAULT_COLLATERAL)
    parser.add_argument("--leverage", type=float, default=DEFAULT_LEVERAGE)
    parser.add_argument("--log-dir", default=None, help="Override log directory (default: datafiles/freqtrade_runs)")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent.parent
    datafiles = os.getenv("DATAFILES_ROOT", str(root / "datafiles"))
    log_dir = Path(args.log_dir) if args.log_dir else Path(datafiles) / "freqtrade_runs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        import tempfile
        log_dir = Path(tempfile.gettempdir()) / "freqtrade_runs"
        log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{ts}_{args.symbol}_{int(args.minutes)}m.log"

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# Freqtrade runner {ts} venue={args.venue} symbol={args.symbol} minutes={args.minutes}\n")

    exit_code, summary = run(
        broker_url=args.broker_url,
        venue=args.venue,
        symbol=args.symbol,
        minutes=args.minutes,
        poll_s=args.poll_s,
        position_poll_s=args.position_poll_s,
        open_every_minutes=args.open_every_minutes,
        collateral=args.collateral,
        leverage=args.leverage,
        log_path=log_path,
    )
    print(f"\nLog: {log_path}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
