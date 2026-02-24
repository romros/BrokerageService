"""
P7c.1 — Unit tests: select_soak_symbol (sense xarxa)

Valida la lògica de selecció de símbol per el Data Layer soak:
- mainnet URL → EURUSD
- testnet URL → ETH
- override → el que diguis
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from testing.helpers.legacy_venue_test_env import (
    select_soak_symbol,
    SOAK_SYMBOL_MAINNET,
    SOAK_SYMBOL_TESTNET,
)


def test_mainnet_url_returns_eurusd():
    """mainnet URL → EURUSD."""
    assert select_soak_symbol("https://mainnet.zklighter.elliot.ai") == SOAK_SYMBOL_MAINNET
    assert select_soak_symbol("https://mainnet.example.com") == SOAK_SYMBOL_MAINNET
    assert select_soak_symbol("http://mainnet.local") == SOAK_SYMBOL_MAINNET


def test_testnet_url_returns_eth():
    """testnet URL → ETH."""
    assert select_soak_symbol("https://testnet.zklighter.elliot.ai") == SOAK_SYMBOL_TESTNET
    assert select_soak_symbol("https://api.testnet.lighter.xyz") == SOAK_SYMBOL_TESTNET
    assert select_soak_symbol("http://testnet.example.com") == SOAK_SYMBOL_TESTNET


def test_override_takes_precedence():
    """override → el que diguis, independent de URL."""
    assert select_soak_symbol("https://mainnet.zklighter.elliot.ai", override="ETH") == "ETH"
    assert select_soak_symbol("https://testnet.zklighter.elliot.ai", override="EURUSD") == "EURUSD"
    assert select_soak_symbol("https://testnet.example.com", override="BTC") == "BTC"
    assert select_soak_symbol("https://mainnet.example.com", override="XAUUSD") == "XAUUSD"


def test_override_empty_ignored():
    """override buit o None → autoselect segons URL."""
    assert select_soak_symbol("https://mainnet.zklighter.elliot.ai", override="") == SOAK_SYMBOL_MAINNET
    assert select_soak_symbol("https://testnet.zklighter.elliot.ai", override=None) == SOAK_SYMBOL_TESTNET
    assert select_soak_symbol("https://testnet.zklighter.elliot.ai", override="   ") == SOAK_SYMBOL_TESTNET


def test_override_stripped_uppercase():
    """override es normalitza (strip, uppercase)."""
    assert select_soak_symbol("https://mainnet.example.com", override="  eth  ") == "ETH"
    assert select_soak_symbol("https://mainnet.example.com", override="eurusd") == "EURUSD"


def main():
    print("=" * 60)
    print("P7c.1 — select_soak_symbol (unit, no xarxa)")
    print("=" * 60)
    test_mainnet_url_returns_eurusd()
    print("✓ test_mainnet_url_returns_eurusd OK")
    test_testnet_url_returns_eth()
    print("✓ test_testnet_url_returns_eth OK")
    test_override_takes_precedence()
    print("✓ test_override_takes_precedence OK")
    test_override_empty_ignored()
    print("✓ test_override_empty_ignored OK")
    test_override_stripped_uppercase()
    print("✓ test_override_stripped_uppercase OK")
    print()
    print("✓ Tots els tests P7c.1 select_soak_symbol passats")


if __name__ == "__main__":
    main()
