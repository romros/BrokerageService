#!/usr/bin/env python3
"""
smoke_connectivity.py — Connectivity & Config (0 transaccions, opt-in).

Comprova:
  1. Presència i format d'env vars mínimes (SENSE mostrar valors secrets).
  2. Connectivitat HTTP bàsica a BASE_URL i endpoints configurats.

Categories d'error:
  AUTH_MISSING_ENV   — variable d'entorn absent o buida
  AUTH_INVALID_FORMAT — variable present però format incorrecte
  DNS                — hostname no resolvible
  CONNECT_TIMEOUT    — connexió establerta però timeout
  CONNECT_REFUSED    — connexió refusada (port tancat)
  HTTP_4XX           — resposta HTTP 4xx (autenticació, not found...)
  HTTP_5XX           — resposta HTTP 5xx (error servidor)
  UNEXPECTED_PAYLOAD — cos de resposta inesperat

Ús:
  python3 scripts/network_smokes/smoke_connectivity.py

Variables d'entorn llegides (mai mostrades en logs):
  BASE_URL            Base del gateway (default: http://localhost:8081)
  REALTIME_DATALAYER_BASE_URL  URL interna del realtime datalayer (opcional)
  SMOKE_TIMEOUT       Timeout per check en segons (default: 5)
  OSTIUM_RPC_URL      RPC Arbitrum (opcional, comprova connectivitat si present)
  OSTIUM_PRIVATE_KEY  Clau privada (mai mostrada; comprova format 0x[64 hex])
  OSTIUM_WALLET_ADDRESS  Wallet address (comprova format 0x[40 hex] si present)
"""

import os
import re
import sys
import socket
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse


# ── Configuració ──────────────────────────────────────────────────────────────

TIMEOUT = int(os.environ.get("SMOKE_TIMEOUT", "5"))
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8081").rstrip("/")

# ── Dataclass resultat ────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    status: str  # "PASS" | "FAIL" | "SKIP"
    category: str  # "OK", "AUTH_MISSING_ENV", "DNS", "CONNECT_TIMEOUT", ...
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


def _check_env_present(var: str, secret: bool = False) -> Optional[str]:
    """Retorna el valor si present, o None. Mai mostra el valor si secret=True."""
    val = os.environ.get(var, "").strip()
    if not val:
        _fail(
            f"env:{var}",
            "AUTH_MISSING_ENV",
            f"Variable {var!r} absent o buida",
            next_action=f"Afegeix {var} a l'entorn o al .env",
        )
        return None
    if secret:
        _pass(f"env:{var}", f"{var} present (valor ocult)")
    else:
        _pass(f"env:{var}", f"{var}={val!r}")
    return val


def _check_env_optional(var: str, secret: bool = False) -> Optional[str]:
    """Com _check_env_present però fa SKIP (no FAIL) si absent."""
    val = os.environ.get(var, "").strip()
    if not val:
        _skip(f"env:{var}", f"{var} no configurat (opcional)")
        return None
    if secret:
        _pass(f"env:{var}", f"{var} present (valor ocult)")
    else:
        _pass(f"env:{var}", f"{var}={val!r}")
    return val


def _check_http(name: str, url: str, expected_status: int = 200) -> bool:
    """Fa un GET a url i classifica l'error si no és expected_status."""
    parsed = urlparse(url)
    host = parsed.hostname or ""

    # Resolució DNS
    try:
        socket.getaddrinfo(host, parsed.port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        _fail(name, "DNS",
              f"No es pot resoldre '{host}': {e}",
              next_action="Comprova DNS, proxy, VPN o si el host és accessible")
        return False

    # Petició HTTP
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "BrokerageService-NetworkSmoke/1.0")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status = resp.status
            if status == expected_status:
                _pass(name, f"HTTP {status}")
                return True
            elif 400 <= status < 500:
                _fail(name, f"HTTP_4XX",
                      f"HTTP {status} (esperat {expected_status})",
                      next_action="Comprova autenticació, path o permisos")
                return False
            elif 500 <= status < 600:
                _fail(name, "HTTP_5XX",
                      f"HTTP {status} (esperat {expected_status})",
                      next_action="Comprova logs del servei")
                return False
            else:
                _fail(name, "UNEXPECTED_PAYLOAD",
                      f"HTTP {status} (esperat {expected_status})",
                      next_action="Revisa la resposta del servei")
                return False
    except urllib.error.HTTPError as e:
        status = e.code
        if 400 <= status < 500:
            _fail(name, "HTTP_4XX",
                  f"HTTP {status}: {e.reason}",
                  next_action="Comprova autenticació, path o permisos")
        elif 500 <= status < 600:
            _fail(name, "HTTP_5XX",
                  f"HTTP {status}: {e.reason}",
                  next_action="Comprova logs del servei")
        else:
            _fail(name, "UNEXPECTED_PAYLOAD",
                  f"HTTP {status}: {e.reason}",
                  next_action="Revisa la resposta del servei")
        return False
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "timed out" in reason.lower() or "timeout" in reason.lower():
            _fail(name, "CONNECT_TIMEOUT",
                  f"Timeout ({TIMEOUT}s) connectant a {url}",
                  next_action="Comprova que el servei estigui en marxa i accessible")
        elif "connection refused" in reason.lower():
            _fail(name, "CONNECT_REFUSED",
                  f"Connexió refusada a {url}",
                  next_action="Comprova que el servei estigui en marxa (docker compose up)")
        else:
            _fail(name, "CONNECT_TIMEOUT",
                  f"URLError: {reason}",
                  next_action="Comprova connectivitat de xarxa")
        return False
    except TimeoutError:
        _fail(name, "CONNECT_TIMEOUT",
              f"Timeout ({TIMEOUT}s) connectant a {url}",
              next_action="Comprova que el servei estigui en marxa i accessible")
        return False


# ── Checks env ────────────────────────────────────────────────────────────────


def check_env_config() -> None:
    print("\n[1] Configuració d'entorn")
    print(f"    BASE_URL = {BASE_URL}")
    print(f"    SMOKE_TIMEOUT = {TIMEOUT}s")
    print()

    # BASE_URL: present i format http(s)://host
    base = os.environ.get("BASE_URL", "http://localhost:8081").strip()
    if re.match(r"^https?://", base):
        _pass("env:BASE_URL", f"BASE_URL={base!r}")
    else:
        _fail("env:BASE_URL", "AUTH_INVALID_FORMAT",
              f"BASE_URL format incorrecte: {base!r}",
              next_action="BASE_URL ha de ser http://host:port o https://host")

    # REALTIME_DATALAYER_BASE_URL (opcional)
    _check_env_optional("REALTIME_DATALAYER_BASE_URL")

    # Ostium (opcionals — presència indica intent d'ús)
    pk = _check_env_optional("OSTIUM_PRIVATE_KEY", secret=True)
    if pk is not None:
        # Comprova format 0x[64 hex] SENSE mostrar la clau
        if re.match(r"^0x[0-9a-fA-F]{64}$", pk):
            _pass("env:OSTIUM_PRIVATE_KEY:format", "Format 0x[64hex] correcte")
        else:
            _fail("env:OSTIUM_PRIVATE_KEY:format", "AUTH_INVALID_FORMAT",
                  "OSTIUM_PRIVATE_KEY no és 0x[64 hex]",
                  next_action="La clau ha de tenir el format 0x + 64 caràcters hex")

    wallet = _check_env_optional("OSTIUM_WALLET_ADDRESS")
    if wallet is not None:
        if re.match(r"^0x[0-9a-fA-F]{40}$", wallet, re.IGNORECASE):
            _pass("env:OSTIUM_WALLET_ADDRESS:format", "Format 0x[40hex] correcte")
        else:
            _fail("env:OSTIUM_WALLET_ADDRESS:format", "AUTH_INVALID_FORMAT",
                  "OSTIUM_WALLET_ADDRESS no és 0x[40 hex]",
                  next_action="L'adreça ha de tenir el format 0x + 40 caràcters hex")

    _check_env_optional("OSTIUM_RPC_URL")


# ── Checks connectivitat ──────────────────────────────────────────────────────


def check_gateway_connectivity() -> None:
    print("\n[2] Connectivitat gateway")
    print(f"    BASE_URL = {BASE_URL}")
    print()

    _check_http("gateway:nginx-health", f"{BASE_URL}/nginx-health")


def check_optional_rpc() -> None:
    rpc_url = os.environ.get("OSTIUM_RPC_URL", "").strip()
    if not rpc_url:
        return

    print("\n[3] Connectivitat RPC (Ostium, opcional)")
    print(f"    OSTIUM_RPC_URL = {rpc_url}")
    print()

    # Comprova connectivitat HTTP al RPC (no executa cap mètode JSON-RPC)
    _check_http("rpc:ostium:reach", rpc_url, expected_status=200)


def check_optional_realtime() -> None:
    rt_url = os.environ.get("REALTIME_DATALAYER_BASE_URL", "").strip()
    if not rt_url:
        return

    print("\n[4] Connectivitat Realtime DataLayer (opcional)")
    print(f"    REALTIME_DATALAYER_BASE_URL = {rt_url}")
    print()

    _check_http("realtime:health", f"{rt_url.rstrip('/')}/health")


# ── Report ────────────────────────────────────────────────────────────────────


def print_report() -> int:
    pass_n = sum(1 for r in results if r.status == "PASS")
    fail_n = sum(1 for r in results if r.status == "FAIL")
    skip_n = sum(1 for r in results if r.status == "SKIP")

    print()
    print("─" * 60)
    print("  REPORT — smoke_connectivity")
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
    print("── smoke_connectivity.py ──────────────────────────────")
    check_env_config()
    check_gateway_connectivity()
    check_optional_rpc()
    check_optional_realtime()
    return print_report()


if __name__ == "__main__":
    sys.exit(main())
