#!/usr/bin/env python3
"""
Flux complet: obrir ordre (posició) → col·locar SL → manipular SL (modify_order) → tancar tot.
Sense pausa: tot seguit. Mida petita (0.05 ETH) per tancar d’un sol ordre.

Smoke test estable. 3 invariants (no treure):
  1. ApiClient amb host explícit: Configuration(host=BASE_URL) + ApiClient(cfg).
  2. Poll després del close: _wait_until_closed(api_client, timeout_s=20).
  3. Retry invalid nonce (21104) a modify_order i cancel_order; 2s entre passos.
"""
import os
import asyncio
from dotenv import load_dotenv
import lighter

load_dotenv()

try:
    import httpx
except ImportError:
    httpx = None

BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
L1_ADDRESS = os.getenv("LIGHTER_L1_ADDRESS")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY")

SL_CLIENT_ORDER_INDEX = 900001

# Mida petita per poder tancar d’un cop (0.05 ETH; escala ×1e6 = 50000)
SIZE_ETH = 0.05
# Market order size: ×10_000 al testnet (50000=5 ETH; 500=0.05 ETH). Abans 50000 obria 5 ETH per error.
POSITION_SIZE_MARKET = int(SIZE_ETH * 10_000)
SL_SIZE_INT = int(SIZE_ETH * 10_000)  # limit/SL: ×10_000

# avg_execution_price per market orders és ×100 (2 decimals), NO ×1e6. Amb slippage.


def _price_to_float_maybe_scaled(px_raw) -> float:
    """
    Heurística: si el preu ve en cents (×100) serà > 10_000 per ETH.
    Retorna preu en unitats reals (USD).
    """
    px = float(px_raw)
    if px > 10_000:
        return px / 100.0
    return px


def _acceptable_price_int(mid: float, is_ask: bool, slippage_bps: int = 50) -> int:
    """Preu acceptable per market order: ×100. is_ask=True => SELL (mínim acceptable)."""
    slip = slippage_bps / 10_000
    if is_ask:
        px = mid * (1 - slip)   # SELL: mínim acceptable
    else:
        px = mid * (1 + slip)  # BUY: màxim acceptable
    return int(round(px * 100))


def _acceptable_price_int_from_bid_ask(
    best_bid: float, best_ask: float, is_ask: bool, slippage_bps: int = 1000
) -> int:
    """
    avg_execution_price ×100 a partir de bid/ask reals.
    Slippage per defecte 1000 bps (10%) per testnet robust.
    """
    slip = slippage_bps / 10_000
    mid = (best_bid + best_ask) / 2.0
    if is_ask:
        px = mid * (1 - slip)   # SELL: mínim acceptable (més baix = més permissiu)
    else:
        px = mid * (1 + slip)   # BUY: màxim acceptable
    return int(round(px * 100))


async def _get_best_bid_ask(api_client, market_index: int = 0) -> tuple[float, float]:
    """Obté best bid i best ask reals (USD). Llança RuntimeError si no hi ha liquidesa."""
    try:
        orders_api = lighter.OrderApi(api_client)
        ob = await orders_api.order_book_orders(market_id=market_index, limit=5)
        bids = getattr(ob, "bids", None) or []
        asks = getattr(ob, "asks", None) or []
        if not bids or not asks:
            raise RuntimeError("No bids/asks a l'orderbook (sense liquidesa?)")
        best_bid_raw = getattr(bids[0], "price", None) or (bids[0].get("price") if isinstance(bids[0], dict) else None)
        best_ask_raw = getattr(asks[0], "price", None) or (asks[0].get("price") if isinstance(asks[0], dict) else None)
        if best_bid_raw is None or best_ask_raw is None:
            raise RuntimeError("Preus bid/ask no disponibles")
        best_bid = _price_to_float_maybe_scaled(best_bid_raw)
        best_ask = _price_to_float_maybe_scaled(best_ask_raw)
        return best_bid, best_ask
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Orderbook no disponible: {e}") from e


async def _retry_on_invalid_nonce(fn, *, retries: int = 5, base_delay: float = 0.6):
    """
    Reintenta fn() quan l'error és 'invalid nonce' (code 21104).
    fn ha de ser async i retornar (_, tx, err).
    """
    last = None
    for i in range(retries):
        res = await fn()
        err = res[2]
        if not err:
            return res
        msg = str(err).lower()
        if "invalid nonce" in msg or "21104" in msg:
            await asyncio.sleep(base_delay * (i + 1))
            last = err
            continue
        return res
    return (None, None, last)


async def _wait_until_closed(api_client, timeout_s: int = 20) -> tuple[bool, bool]:
    """
    Poll fins que posicions obertes = 0 o timeout.
    Retorna (tancat_confirmat, consulta_ok).
    Si consulta_ok és False, no s'ha pogut verificar (no vol dir "segueix oberta").
    """
    t0 = asyncio.get_event_loop().time()
    last_ok = False
    while asyncio.get_event_loop().time() - t0 < timeout_s:
        pos, ok = await _consultar_posicions(api_client)
        last_ok = ok
        if ok and len(pos) == 0:
            return True, True
        await asyncio.sleep(1)
    return False, last_ok


def _pos_from_account_response(accounts):
    """Extrau llista de posicions amb size>0 des de response account (SDK o dict)."""
    result = []
    if not accounts:
        return result
    acc = accounts[0]
    positions = getattr(acc, "positions", None) or (acc.get("positions") if isinstance(acc, dict) else None) or []
    for pos in positions:
        size_str = getattr(pos, "position", None) or (pos.get("position") if isinstance(pos, dict) else None) or "0"
        try:
            size_f = float(size_str)
        except (TypeError, ValueError):
            size_f = 0.0
        if size_f > 0:
            result.append({
                "symbol": getattr(pos, "symbol", None) or (pos.get("symbol") if isinstance(pos, dict) else "?"),
                "position": str(size_str),
                "entry": getattr(pos, "avg_entry_price", None) or (pos.get("avg_entry_price") if isinstance(pos, dict) else ""),
            })
    return result


async def _consultar_posicions(api_client=None):
    """Retorna (llista de posicions amb size>0, consultat_ok). Prova SDK (AccountApi.account) primer; si falla, httpx."""
    result = []
    consultat = False
    if not L1_ADDRESS:
        return result, consultat
    # 1) Intent amb SDK (AccountApi.account) si tenim api_client
    if api_client is not None:
        try:
            account_api = lighter.AccountApi(api_client)
            resp = await account_api.account(by="l1_address", value=L1_ADDRESS)
            if getattr(resp, "accounts", None):
                result = _pos_from_account_response(resp.accounts)
                consultat = True
        except Exception:
            pass
    # 2) Fallback: GET directe (com la UI) si no httpx o si SDK ha fallat
    if not consultat and httpx:
        try:
            url = f"{BASE_URL.rstrip('/')}/api/v1/account"
            r = await asyncio.to_thread(httpx.get, url, params={"by": "l1_address", "value": L1_ADDRESS}, timeout=10.0)
            r.raise_for_status()
            data = r.json()
            if data.get("code") == 200 and data.get("accounts"):
                result = _pos_from_account_response(data["accounts"])
                consultat = True
        except Exception:
            pass
    return result, consultat


async def main():
    print("=" * 80)
    print("LIGHTER - Obrir → SL → actualitzar SL → tancar tot")
    print("=" * 80)
    print(f"Account: {ACCOUNT_INDEX}  |  Mida: {SIZE_ETH} ETH\n")

    # ApiClient ha d'apuntar al testnet (sinó AccountApi.account() pot fallar / host per defecte).
    cfg = lighter.Configuration(host=BASE_URL)
    api_client = lighter.ApiClient(cfg)

    # --- 0. POSICIONS OBERTES (inici) — SDK (AccountApi.account) o fallback httpx ---
    print("0. POSICIONS OBERTES (inici)")
    posicions_inici, consultat_inici = await _consultar_posicions(api_client)
    if not consultat_inici:
        print("   ⚠️ No s'han pogut consultar (LIGHTER_L1_ADDRESS; SDK i, si hi ha httpx, API directa).\n")
    else:
        n_inici = len(posicions_inici)
        print(f"   Posicions obertes: {n_inici}")
        for p in posicions_inici:
            print(f"      - {p['symbol']} size={p['position']} entry={p['entry']}")
        if n_inici == 0:
            print("   (cap)\n")
        else:
            print()

    signer = lighter.SignerClient(
        url=BASE_URL,
        api_private_keys={API_KEY_INDEX: API_PRIVATE_KEY},
        account_index=ACCOUNT_INDEX,
    )

    # Preu acceptable des de bid/ask REAL abans d'obrir (slippage 10% testnet).
    try:
        best_bid, best_ask = await _get_best_bid_ask(api_client, market_index=0)
        mid_price = (best_bid + best_ask) / 2.0
        print("   📊 Orderbook: bid=${:.2f} ask=${:.2f} mid=${:.2f}\n".format(best_bid, best_ask, mid_price))
        open_avg_px = _acceptable_price_int_from_bid_ask(best_bid, best_ask, is_ask=False, slippage_bps=1000)
    except RuntimeError as e:
        print("   ⚠️ {} Usant fallback mid 1966.\n".format(e))
        mid_price = 1966.0
        open_avg_px = _acceptable_price_int(mid_price, is_ask=False, slippage_bps=1000)

    # --- 1. Obrir posició (market) ---
    print("1. OBRIR POSICIÓ (market LONG)")
    _, tx, err = await signer.create_market_order(
        market_index=0,
        client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
        base_amount=POSITION_SIZE_MARKET,
        avg_execution_price=open_avg_px,
        is_ask=False,
        reduce_only=False,
    )
    if err:
        print(f"   ❌ {err}\n")
        await signer.close()
        await api_client.close()
        return
    print(f"   ✅ Obert. TX: {getattr(tx, 'tx_hash', tx)}\n")
    await asyncio.sleep(2)  # Pausa entre tx (testnet nonce)

    # --- 2. Col·locar SL ---
    print("2. COL·LOCAR SL")
    sl_trigger_1 = mid_price * 0.98
    sl_price_1 = sl_trigger_1 * 0.999
    sl_trigger_int_1 = int(sl_trigger_1 * 100)
    sl_price_int_1 = int(sl_price_1 * 100)
    _, tx, err = await signer.create_sl_limit_order(
        market_index=0,
        client_order_index=SL_CLIENT_ORDER_INDEX,
        base_amount=SL_SIZE_INT,
        trigger_price=sl_trigger_int_1,
        price=sl_price_int_1,
        is_ask=True,
        reduce_only=True,
    )
    if err:
        print(f"   ❌ {err}\n")
    else:
        print(f"   ✅ SL col·locat (trigger ${sl_trigger_1:.2f})\n")
    await asyncio.sleep(2)

    # --- 3. Manipular SL (modify_order) ---
    print("3. ACTUALITZAR SL (modify_order)")
    sl_trigger_2 = mid_price * 0.97
    sl_price_2 = sl_trigger_2 * 0.999
    sl_trigger_int_2 = int(sl_trigger_2 * 100)
    sl_price_int_2 = int(sl_price_2 * 100)
    _, tx, err = await _retry_on_invalid_nonce(
        lambda: signer.modify_order(
            market_index=0,
            order_index=SL_CLIENT_ORDER_INDEX,
            base_amount=SL_SIZE_INT,
            price=sl_price_int_2,
            trigger_price=sl_trigger_int_2,
        ),
        retries=5,
        base_delay=0.6,
    )
    if err:
        print(f"   ❌ {err}\n")
    else:
        print(f"   ✅ SL actualitzat (nou trigger ${sl_trigger_2:.2f})\n")
    await asyncio.sleep(2)

    # --- 4. Cancel·lar SL ---
    print("4. CANCEL·LAR SL")
    _, tx, err = await _retry_on_invalid_nonce(
        lambda: signer.cancel_order(market_index=0, order_index=SL_CLIENT_ORDER_INDEX),
        retries=5,
        base_delay=0.6,
    )
    if err:
        print(f"   ❌ {err}\n")
    else:
        print(f"   ✅ SL cancel·lat\n")
    await asyncio.sleep(2)

    # --- 5. Tancar posició del tot (market reduce-only) ---
    # Preu acceptable des de bid/ask REAL just abans de tancar (crític: mercat pot haver mogut). Slippage 10%.
    try:
        best_bid_close, best_ask_close = await _get_best_bid_ask(api_client, market_index=0)
        close_avg_px = _acceptable_price_int_from_bid_ask(
            best_bid_close, best_ask_close, is_ask=True, slippage_bps=1000
        )
        print("5. TANCAR POSICIÓ (market reduce-only)")
        print("   Bid=${:.2f} Ask=${:.2f} → close_avg_px (×100) = {}".format(
            best_bid_close, best_ask_close, close_avg_px
        ))
    except RuntimeError as e:
        print("   ⚠️ {} Usant mid anterior per tancar.".format(e))
        close_avg_px = _acceptable_price_int(mid_price, is_ask=True, slippage_bps=1000)
        print("5. TANCAR POSICIÓ (market reduce-only)")
        print("   close_avg_px (fallback) = {}".format(close_avg_px))

    # Mida a tancar: la que hi ha realment (rounding / partial fills).
    posicions_ara, _ = await _consultar_posicions(api_client)
    size_to_close_eth = SIZE_ETH
    for p in posicions_ara:
        if (getattr(p, "symbol", None) or p.get("symbol")) == "ETH":
            try:
                size_to_close_eth = float(getattr(p, "position", None) or p.get("position", "0"))
            except (TypeError, ValueError):
                pass
            break
    base_amount_close = int(round(size_to_close_eth * 10_000))
    print("   Tancant {:.4f} ETH (base_amount={})".format(size_to_close_eth, base_amount_close))

    _, tx, err = await signer.create_market_order(
        market_index=0,
        client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
        base_amount=base_amount_close,
        avg_execution_price=close_avg_px,
        is_ask=True,
        reduce_only=True,
    )
    if err:
        print(f"   ❌ {err}\n")
    else:
        print(f"   ✅ Ordre tancament enviada. TX: {getattr(tx, 'tx_hash', tx)}\n")

    # --- 5b. Poll fins que posicions = 0 (eventual consistency) ---
    closed, consulta_ok = await _wait_until_closed(api_client, timeout_s=20)
    if closed:
        print("   ✅ Closed confirmed\n")
    elif not consulta_ok:
        print("   ⚠️ No s'ha pogut verificar el tancament (consulta posicions fallida; comprova LIGHTER_L1_ADDRESS i pip install httpx)\n")
    else:
        print("   ❌ Still open after timeout\n")

    # --- 6. POSICIONS OBERTES (final) — ha de quedar igual que a l'inici (SDK o httpx) ---
    print("6. POSICIONS OBERTES (final)")
    posicions_final, consultat_final = await _consultar_posicions(api_client)
    if not consultat_final:
        if not L1_ADDRESS:
            print("   ⚠️ Falta LIGHTER_L1_ADDRESS al .env\n")
        elif not httpx:
            print("   ⚠️ Falta httpx (pip install httpx)\n")
        else:
            print("   ⚠️ No s'han pogut consultar posicions\n")
    else:
        n_final = len(posicions_final)
        print(f"   Posicions obertes: {n_final}")
        for p in posicions_final:
            print(f"      - {p['symbol']} size={p['position']} entry={p['entry']}")
        if n_final == 0:
            print("   (cap)\n")

    # Comparar: ha de quedar igual (mateix nombre de posicions que a l'inici)
    if consultat_inici and consultat_final:
        n_inici = len(posicions_inici)
        n_final = len(posicions_final)
        if n_inici == n_final:
            print("   ✅ Ha de quedar igual: correcte (inici={} final={}).".format(n_inici, n_final))
        else:
            print("   ❌ FALLO: no ha quedat igual (inici={} final={}). La posició no s'ha tancat del tot.".format(n_inici, n_final))
    else:
        print("   ⚠️ No s'ha pogut comprovar (consulta inici o final fallida).")
    print("=" * 80)

    await signer.close()
    await api_client.close()


if __name__ == "__main__":
    asyncio.run(main())
