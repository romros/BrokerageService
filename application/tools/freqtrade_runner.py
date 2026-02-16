"""
Freqtrade-like runner — PAPER DONE handshake (AGENTS §2.6)

Client pur HTTP: llegeix candles, preu, obre/tanca posicions paper via API.
Assumeix broker en marxa amb pipeline actiu (com docker-compose.soak.yml).

Ús:
  python -m application.tools.freqtrade_runner --venue lighter --mode PAPER --symbol ETH --minutes 15
  python -m application.tools.freqtrade_runner --venue paper --symbol ETH --minutes 15   # zero tx (MODE=paper)
  python -m application.tools.freqtrade_runner --broker-url http://localhost:8000 --minutes 2
  # En background: afegir & al final, o --position-poll-s 30 per veure PnL cada 30s (per defecte)

Log: datafiles/freqtrade_runs/<timestamp>_<symbol>_<minutes>.log
Output canònic: FREQTRADE_RUNNER step=... status=OK|FAILED
"""

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from foundation.utils.file_permissions import set_host_readable_permissions

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


# Endpoints per latency (nom curt per logs)
_ENDPOINT_OHLCV = "ohlcv"
_ENDPOINT_PRICE = "price"
_ENDPOINT_OPEN = "open"
_ENDPOINT_CLOSE = "close"
_ENDPOINT_POSITIONS = "positions"
_ENDPOINT_MODE = "mode"


def _record_latency(latencies_by_endpoint: dict[str, list], endpoint: str, ms: float) -> None:
    if endpoint not in latencies_by_endpoint:
        latencies_by_endpoint[endpoint] = []
    latencies_by_endpoint[endpoint].append(ms)


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
    require_real_feed: bool = False,
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
    latencies_by_endpoint: dict[str, list[float]] = {}
    market_data_source: str = "?"
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
        # Esperar broker (ex: docker compose up -d; el runner pot arrencar abans que l'API)
        mode_ok = False
        for attempt in range(30):
            try:
                t0 = time.perf_counter()
                r = requests.get(mode_url, timeout=5)
                ms = (time.perf_counter() - t0) * 1000
                latencies_ms.append(ms)
                _record_latency(latencies_by_endpoint, _ENDPOINT_MODE, ms)
                if r.status_code == 200:
                    data = r.json()
                    src = data.get("market_data_source", "?")
                    market_data_source = src
                    _log(
                        f"{PREFIX}mode={data.get('mode', '?')} market_data_env={data.get('market_data_env', '?')} market_data_source={src}",
                        log_path,
                    )
                    mode_ok = True
                    break
            except Exception as e:
                if attempt < 29:
                    time.sleep(1)
                    continue
                _emit("mode", "FAILED", str(e), log_path)
                return 1, {}
        if not mode_ok:
            _emit("mode", "FAILED", "no response 200", log_path)
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
                r = requests.get(ohlcv_url, timeout=15)  # Docker/CI pot ser lent
                ms = (time.perf_counter() - t0) * 1000
                latencies_ms.append(ms)
                _record_latency(latencies_by_endpoint, _ENDPOINT_OHLCV, ms)
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
                ms = (time.perf_counter() - t0) * 1000
                latencies_ms.append(ms)
                _record_latency(latencies_by_endpoint, _ENDPOINT_PRICE, ms)
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
                        ms = (time.perf_counter() - t0) * 1000
                        latencies_ms.append(ms)
                        _record_latency(latencies_by_endpoint, _ENDPOINT_OPEN, ms)
                        if r.status_code == 200:
                            data = r.json()
                            position_id = data.get("position_id") or ""
                            open_price = data.get("executed_price")
                            open_size = data.get("executed_size")
                            opened = True
                            opens += 1
                            if not position_id:
                                _log(
                                    f"{PREFIX}open OK but position_id empty (serà obtingut de GET /positions)",
                                    log_path,
                                )
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
                    t0 = time.perf_counter()
                    r = requests.get(pos_url, timeout=15)  # Docker/CI pot ser lent
                    _record_latency(latencies_by_endpoint, _ENDPOINT_POSITIONS, (time.perf_counter() - t0) * 1000)
                    if r.status_code == 200:
                        data = r.json()
                        positions = data.get("positions") or []
                        for p in positions:
                            if p.get("symbol") == symbol:
                                mark = p.get("mark_price")
                                pnl = p.get("unrealized_pnl")
                                size_val = p.get("size") or 0.0
                                notional_val = p.get("notional") or 0.0
                                entry = p.get("open_price") or 0.0
                                # Fallback: open_price/size si no vingueren del open
                                if open_price is None and entry:
                                    open_price = float(entry)
                                if open_size is None and entry and size_val:
                                    open_size = float(size_val)
                                # Fallback: position_id des de GET /positions si open no el retornà
                                if not position_id and p.get("position_id"):
                                    position_id = p["position_id"]
                                # Format semblant a taula Positions web: Size, Position Value, Entry Price, Mark Price, Unrealized PnL
                                position_value = (mark * size_val) if (mark and size_val) else notional_val
                                pnl_rounded = round(float(pnl), 2) if pnl is not None else 0.0
                                margin = (notional_val / leverage) if (leverage and notional_val) else 0.0
                                pnl_pct = round((float(pnl) / margin * 100), 2) if (margin and pnl is not None) else 0.0
                                pnl_str = f"${pnl_rounded:.2f}" if pnl_rounded >= 0 else f"-${abs(pnl_rounded):.2f}"
                                _log(
                                    f"{PREFIX}position_pnl symbol={symbol} Size={size_val:.4f} Position Value=${position_value:.2f} Entry Price={entry:.2f} Mark Price={mark} Unrealized PnL={pnl_str} ({pnl_pct}%)",
                                    log_path,
                                )
                                break
                except Exception as e:
                    _log(f"{PREFIX}position_pnl error={e}", log_path)

            time.sleep(poll_s)

        # Cleanup: sempre tancar al final
        # Si position_id buit, intentar obtenir-lo de GET /positions (fallback)
        if opened and not position_id:
            try:
                t0 = time.perf_counter()
                r = requests.get(f"{base}/api/v1/broker/positions?venue={venue}", timeout=15)
                _record_latency(latencies_by_endpoint, _ENDPOINT_POSITIONS, (time.perf_counter() - t0) * 1000)
                if r.status_code == 200:
                    for p in (r.json().get("positions") or []):
                        if p.get("symbol") == symbol and p.get("position_id"):
                            position_id = p["position_id"]
                            break
            except Exception:
                pass
        if opened and position_id:
            close_url = f"{base}/api/v1/broker/orders/close"
            body = {"venue": venue, "position_id": position_id, "percent": 100.0}
            for close_attempt in range(3):  # Reintents per 500 (transient)
                try:
                    t0 = time.perf_counter()
                    r = requests.post(close_url, json=body, timeout=90)  # Docker/CI pot ser lent
                    ms = (time.perf_counter() - t0) * 1000
                    latencies_ms.append(ms)
                    _record_latency(latencies_by_endpoint, _ENDPOINT_CLOSE, ms)
                    if r.status_code == 200:
                        closes += 1
                        _emit("close", "OK", f"position_id={position_id}", log_path)
                        break
                    # Log detall per diagnosticar (500 = error servidor)
                    detail = ""
                    try:
                        j = r.json()
                        detail = j.get("detail", str(j))[:300]
                    except Exception:
                        detail = (r.text or "")[:300]
                    _emit(
                        "close",
                        "FAILED",
                        f"status={r.status_code} detail={detail}" + (f" attempt={close_attempt+1}/3" if close_attempt < 2 else ""),
                        log_path,
                    )
                    # Retry només per 500 (error servidor) o 503; 404/422 no retry
                    if r.status_code in (500, 503) and close_attempt < 2:
                        time.sleep(5)  # Esperar abans de retry
                        continue
                    break
                except Exception as e:
                    _emit("close", "FAILED", f"{e} attempt={close_attempt+1}/3", log_path)
                    if close_attempt < 2:
                        time.sleep(5)
                        continue
                    break

        # Esperar settle i verificar positions_after
        for _ in range(int(30 / poll_s)):
            time.sleep(poll_s)
            pos_url = f"{base}/api/v1/broker/positions?venue={venue}"
            try:
                t0 = time.perf_counter()
                r = requests.get(pos_url, timeout=5)
                _record_latency(latencies_by_endpoint, _ENDPOINT_POSITIONS, (time.perf_counter() - t0) * 1000)
                if r.status_code == 200:
                    data = r.json()
                    positions = data.get("positions") or []
                    for_symbol = [p for p in positions if p.get("symbol") == symbol or symbol in str(p.get("symbol", ""))]
                    positions_after = len(for_symbol)
                    if positions_after == 0:
                        break
            except Exception:
                pass

        # PnL realitzat: obtenir close trade de GET /trades (format semblant a Trade History web)
        if closes and open_price and open_size and open_size > 0:
            close_price = None
            trade_value = open_size * open_price  # Fallback
            want_side = "sell" if is_long else "buy"
            for attempt in range(4):  # 5s, 10s, 15s, 20s
                time.sleep(5)
                trades_url = f"{base}/api/v1/broker/trades?venue={venue}&symbol={symbol}&limit=20"
                try:
                    r = requests.get(trades_url, timeout=10)
                    if r.status_code == 200:
                        data = r.json()
                        trades = data.get("trades") or []
                        for t in trades:
                            if (t.get("side") or "").lower() == want_side:
                                close_price = t.get("price") or 0
                                if close_price > 0:
                                    trade_value = close_price * open_size
                                    realized_pnl = (close_price - open_price) * open_size if is_long else (open_price - close_price) * open_size
                                    notional = open_price * open_size
                                    realized_pnl_pct = (realized_pnl * leverage / notional * 100) if notional and leverage else 0
                                    realized_pnl = round(realized_pnl, 2)
                                    realized_pnl_pct = round(realized_pnl_pct, 2)
                                    # Format semblant a Trade History web: Market, Side, Date, Size, Price, Trade Value, Closed PnL
                                    side_label = "Close Long" if is_long else "Close Short"
                                    ts_str = datetime.now(timezone.utc).strftime("%m/%d/%Y %H:%M:%S")
                                    _log(
                                        f"{PREFIX}closed_trade Market={symbol} Side={side_label} Date={ts_str} Size={open_size:.4f} Price={close_price:.2f} Trade Value=${trade_value:.2f} Closed PnL=${realized_pnl:.2f} ({realized_pnl_pct:.2f}%)",
                                        log_path,
                                    )
                                    break
                    if close_price and close_price > 0:
                        break
                except Exception as e:
                    if attempt == 3:
                        _log(f"{PREFIX}closed_trade error={e}", log_path)
                    continue
            if not close_price or close_price <= 0:
                _log(f"{PREFIX}closed_trade no close trade found (GET /trades retornà 0 o sense side={want_side}); comparar manualment amb Trade History web", log_path)
        elif closes and (open_price is None or open_size is None or open_size <= 0):
            _log(f"{PREFIX}closed_trade skip (open_price={open_price} open_size={open_size})", log_path)

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
            "market_data_source": market_data_source,
            "latency_p50_ms": round(p50, 1),
            "latency_p95_ms": round(p95, 1),
        }
        # Per-endpoint latency (p50, p95)
        for ep in [_ENDPOINT_OHLCV, _ENDPOINT_PRICE, _ENDPOINT_OPEN, _ENDPOINT_CLOSE, _ENDPOINT_POSITIONS]:
            vals = latencies_by_endpoint.get(ep, [])
            if vals:
                s = sorted(vals)
                summary[f"latency_{ep}_p50_ms"] = round(_percentile(s, 50), 1)
                summary[f"latency_{ep}_p95_ms"] = round(_percentile(s, 95), 1)
        if realized_pnl is not None:
            summary["realized_pnl"] = realized_pnl
        if realized_pnl_pct is not None:
            summary["realized_pnl_pct"] = realized_pnl_pct
        _emit("result", "OK" if positions_after == 0 and candles_read >= 1 else "FAILED", f"positions_after={positions_after} candles={candles_read}", log_path)
        _log(f"{PREFIX}summary " + " ".join(f"{k}={v}" for k, v in sorted(summary.items())), log_path)

        # Health gate (exit codes)
        if positions_after != 0:
            return 2, summary
        if missing_minutes > 1:
            return 3, summary
        if require_real_feed and market_data_source != "real":
            return 4, summary
        return 0 if candles_read >= 1 else 1, summary

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
    parser.add_argument("--log-path", default=None, help="Override full log file path (for soak scripts)")
    parser.add_argument("--require-real-feed", action="store_true", help="Exit 4 if market_data_source != real (soak amb preus reals)")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent.parent
    datafiles = os.getenv("DATAFILES_ROOT", str(root / "datafiles"))
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if args.log_path:
        log_path = Path(args.log_path)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    else:
        log_dir = Path(args.log_dir) if args.log_dir else Path(datafiles) / "freqtrade_runs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            log_dir = Path(tempfile.gettempdir()) / "freqtrade_runs"
            log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{ts}_{args.symbol}_{int(args.minutes)}m.log"

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# Freqtrade runner {ts} venue={args.venue} symbol={args.symbol} minutes={args.minutes}\n")
    set_host_readable_permissions(log_path)

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
        require_real_feed=args.require_real_feed,
    )
    print(f"\nLog: {log_path}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
