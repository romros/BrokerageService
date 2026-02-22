#!/usr/bin/env python3
"""
smoke_gateway_readonly.py — Gateway read-only E2E via BASE_URL (opt-in).

Comprova tots els endpoints públics read-only accessibles via el gateway single-port
(:8081). Només GETs, cap write, cap ordre. Fail-fast per categoria d'error.

Endpoints verificats:
  /nginx-health
  /realtime/health
  /realtime/status
  /data/health
  /data/status
  /trade/api/v1/broker/health
  /trade/api/v1/broker/data_status
  /trade/api/v1/broker/preflight       (Phase I)
  /backtests/runs                       (pot ser llista buida → 200)

Categories d'error:
  DNS, CONNECT_TIMEOUT, CONNECT_REFUSED
  HTTP_4XX, HTTP_5XX
  UNEXPECTED_PAYLOAD — body no té l'estructura esperada (si es comprova)

Ús:
  python3 scripts/network_smokes/smoke_gateway_readonly.py

Variables d'entorn:
  BASE_URL       Base del gateway (default: http://localhost:8081)
  SMOKE_TIMEOUT  Timeout en segons (default: 5)
"""

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse


# ── Configuració ──────────────────────────────────────────────────────────────

TIMEOUT = int(os.environ.get("SMOKE_TIMEOUT", "5"))
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8081").rstrip("/")


# ── Dataclass resultat ────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    status: str          # "PASS" | "FAIL" | "SKIP"
    category: str        # "OK", "DNS", "CONNECT_TIMEOUT", ...
    detail: str
    next_action: str = ""


results: list[CheckResult] = []


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pass(name: str, detail: str = "") -> CheckResult:
    r = CheckResult(name=name, status="PASS", category="OK", detail=detail)
    results.append(r)
    return r


def _fail(name: str, category: str, detail: str, next_action: str = "") -> CheckResult:
    r = CheckResult(name=name, status="FAIL", category=category,
                    detail=detail, next_action=next_action)
    results.append(r)
    return r


def _skip(name: str, detail: str = "") -> CheckResult:
    r = CheckResult(name=name, status="SKIP", category="OK", detail=detail)
    results.append(r)
    return r


def _fetch(url: str) -> tuple[Optional[int], Optional[bytes], Optional[str]]:
    """
    Fa GET a url. Retorna (status_code, body_bytes, error_category).
    error_category és None si OK, string de categoria si error de xarxa.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    try:
        socket.getaddrinfo(host, parsed.port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return None, None, "DNS"

    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "BrokerageService-NetworkSmoke/1.0")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read(), None
    except urllib.error.HTTPError as e:
        return e.code, None, None
    except urllib.error.URLError as e:
        reason = str(e.reason).lower()
        if "timed out" in reason or "timeout" in reason:
            return None, None, "CONNECT_TIMEOUT"
        if "connection refused" in reason:
            return None, None, "CONNECT_REFUSED"
        return None, None, "CONNECT_TIMEOUT"
    except TimeoutError:
        return None, None, "CONNECT_TIMEOUT"


def _next_action_for_net_error(category: str, url: str) -> str:
    if category == "DNS":
        return "Comprova DNS / VPN / proxy o si el host és accessible"
    if category == "CONNECT_TIMEOUT":
        return f"Timeout ({TIMEOUT}s) — comprova que el servei estigui en marxa i el port accessible"
    if category == "CONNECT_REFUSED":
        return "Connexió refusada — comprova 'docker compose up' i que el port estigui exposat"
    return "Comprova la connectivitat de xarxa"


def check_endpoint(
    name: str,
    path: str,
    expected_status: int = 200,
    check_json_keys: Optional[list[str]] = None,
) -> bool:
    """
    Verifica un endpoint GET read-only.

    check_json_keys: si present, comprova que el JSON de la resposta
                     contingui totes les claus indicades (best-effort).
    """
    url = f"{BASE_URL}{path}"
    status, body, net_err = _fetch(url)

    if net_err:
        _fail(name, net_err,
              f"Error de xarxa a {url}",
              next_action=_next_action_for_net_error(net_err, url))
        return False

    if status != expected_status:
        if status is not None and 400 <= status < 500:
            cat = "HTTP_4XX"
            nxt = "Comprova autenticació, path o permisos"
        elif status is not None and 500 <= status < 600:
            cat = "HTTP_5XX"
            nxt = "Comprova logs del servei"
        else:
            cat = "UNEXPECTED_PAYLOAD"
            nxt = "Revisa la resposta del servei"
        _fail(name, cat,
              f"HTTP {status} (esperat {expected_status}) a {url}",
              next_action=nxt)
        return False

    # Comprovació opcional de claus JSON
    if check_json_keys and body:
        try:
            data: Any = json.loads(body)
            missing = [k for k in check_json_keys if k not in data]
            if missing:
                _fail(name, "UNEXPECTED_PAYLOAD",
                      f"HTTP {status} OK però manquen claus JSON: {missing}",
                      next_action="Comprova que el servei retorna el format esperat")
                return False
        except (json.JSONDecodeError, TypeError):
            # Body no és JSON vàlid (pot ser text/plain per health)
            pass

    detail = f"HTTP {status}"
    if body:
        # Mostra una previsualització curta del body (max 80 chars, cap secret)
        preview = body[:80].decode("utf-8", errors="replace").strip()
        if preview:
            detail += f" — {preview!r}"
    _pass(name, detail)
    return True


# ── Grups de checks ───────────────────────────────────────────────────────────


def check_proxy() -> None:
    print("\n[1] Proxy nginx")
    check_endpoint("nginx:nginx-health", "/nginx-health")


def check_realtime() -> None:
    print("\n[2] Realtime DataLayer (/realtime/*)")
    check_endpoint("realtime:health", "/realtime/health",
                   check_json_keys=["status"])
    # /status retorna dades detallades per símbol (sense clau top-level "status")
    check_endpoint("realtime:status", "/realtime/status")


def check_historical() -> None:
    print("\n[3] Historical DataLayer (/data/*)")
    check_endpoint("data:health", "/data/health",
                   check_json_keys=["status"])
    # /status retorna dades de coverage per símbol (sense clau top-level "status")
    check_endpoint("data:status", "/data/status")


def check_trading() -> None:
    print("\n[4] Trading Service (/trade/*)")
    check_endpoint("trade:health", "/trade/api/v1/broker/health",
                   check_json_keys=["status"])
    check_endpoint("trade:data_status", "/trade/api/v1/broker/data_status")
    # /preflight — Phase I (kill switch + venue health): espera 200 o 503
    _check_preflight()


def _check_preflight() -> None:
    """
    /preflight pot retornar 200 (tot OK) o 503 (servei degradat).
    404 → SKIP (endpoint Phase I, pot no existir en totes les versions).
    Ambdós 200/503 són respostes vàlides — el que volem és que respongui (no DNS/timeout).
    """
    url = f"{BASE_URL}/trade/api/v1/broker/preflight"
    status, body, net_err = _fetch(url)

    name = "trade:preflight"
    if net_err:
        _fail(name, net_err,
              f"Error de xarxa a {url}",
              next_action=_next_action_for_net_error(net_err, url))
        return

    if status in (200, 503):
        detail = f"HTTP {status}"
        if body:
            preview = body[:80].decode("utf-8", errors="replace").strip()
            if preview:
                detail += f" — {preview!r}"
        _pass(name, detail)
    elif status == 404:
        _skip(name, "HTTP 404 — endpoint /preflight no disponible en aquesta versió (Phase I opt-in)")
    elif status is not None and 400 <= status < 500:
        _fail(name, "HTTP_4XX",
              f"HTTP {status} a {url}",
              next_action="Comprova autenticació o configuració de l'endpoint")
    else:
        _fail(name, "HTTP_5XX",
              f"HTTP {status} a {url}",
              next_action="Comprova logs del trading_service")


def check_backtests() -> None:
    print("\n[5] Backtests alias (/backtests/*)")
    # /backtests/runs pot ser llista buida (200) — vàlid; 404 → SKIP (mòdul opcional)
    url = f"{BASE_URL}/backtests/runs"
    status, body, net_err = _fetch(url)
    name = "backtests:runs"
    if net_err:
        _fail(name, net_err,
              f"Error de xarxa a {url}",
              next_action=_next_action_for_net_error(net_err, url))
    elif status == 404:
        _skip(name, "HTTP 404 — mòdul backtests no disponible en aquesta instància")
    elif status == 200:
        detail = f"HTTP 200"
        if body:
            try:
                data = json.loads(body)
                n_runs = len(data.get("runs", []))
                detail += f" — {n_runs} runs"
            except (json.JSONDecodeError, TypeError):
                preview = body[:80].decode("utf-8", errors="replace").strip()
                detail += f" — {preview!r}"
        _pass(name, detail)
    elif status is not None and 500 <= status < 600:
        _fail(name, "HTTP_5XX",
              f"HTTP {status} a {url}",
              next_action="Comprova logs del trading_service")
    else:
        _fail(name, "HTTP_4XX",
              f"HTTP {status} a {url}",
              next_action="Comprova la configuració nginx de l'alias /backtests/*")


# ── Report ────────────────────────────────────────────────────────────────────


def print_report() -> int:
    pass_n = sum(1 for r in results if r.status == "PASS")
    fail_n = sum(1 for r in results if r.status == "FAIL")
    skip_n = sum(1 for r in results if r.status == "SKIP")

    print()
    print("─" * 60)
    print("  REPORT — smoke_gateway_readonly")
    print("─" * 60)
    for r in results:
        icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘"}.get(r.status, "?")
        line = f"  {icon} [{r.status}] {r.name}"
        if r.category != "OK":
            line += f"  [{r.category}]"
        if r.detail:
            line += f"  — {r.detail}"
        print(line)
        if r.status == "FAIL" and r.next_action:
            print(f"       → {r.next_action}")
    print("─" * 60)
    print(f"  Resultat: {pass_n} PASS, {fail_n} FAIL, {skip_n} SKIP")
    print("─" * 60)
    return 0 if fail_n == 0 else 1


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    print("── smoke_gateway_readonly.py ──────────────────────────")
    print(f"   BASE_URL     = {BASE_URL}")
    print(f"   SMOKE_TIMEOUT = {TIMEOUT}s")
    check_proxy()
    check_realtime()
    check_historical()
    check_trading()
    check_backtests()
    return print_report()


if __name__ == "__main__":
    sys.exit(main())
