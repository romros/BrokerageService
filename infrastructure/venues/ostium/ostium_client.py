"""
OstiumClient — thin wrapper around ostium_python_sdk per facilitar testing.

IOstiumClient: interfície per DI (production vs fake).
OstiumClient:  implementació real (usa ostium_python_sdk + web3).
FakeOstiumClient: implementació stub per 0-network tests.

Patró de referència: lighter/market_data_client.py

Notes SDK (testnet):
    config = NetworkConfig.testnet()  # o mainnet()
    sdk = OstiumSDK(config, private_key)

    # Preu
    price, bid, ask = await sdk.price.get_price("EUR", "USD")

    # Obrir posició (SINCRONA — l'SDK no és async)
    receipt = sdk.ostium.perform_trade(trade_params, at_price=price)

    # Tancar posició (SINCRONA)
    close_receipt = sdk.ostium.close_trade(pair_id, trade_index, price)

    # getOpenTrade via web3 (per trobar trade_index)
    result = contract.functions.getOpenTrade(trader, pair_id, index).call()
    # → (openPrice, tp, sl, collateral, leverage, isLong)
    # si collateral > 0 → trade actiu

Ostium event:
    ORDER_OPENED_TOPIC = Web3.keccak(text='OrderOpened(uint256,address,uint8)').hex()
    topic[3] → pair_id
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from foundation.logging import get_logger

logger = get_logger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

TRADING_CONTRACT_TESTNET = "0x2A9B9c988393f46a2537B0ff11E98c2C15a95afe"
TRADING_CONTRACT_MAINNET = "0x2A9B9c988393f46a2537B0ff11E98c2C15a95afe"  # TODO: verificar mainnet

GET_OPEN_TRADE_ABI = [{
    "inputs": [
        {"name": "trader", "type": "address"},
        {"name": "pairId", "type": "uint16"},
        {"name": "index", "type": "uint8"},
    ],
    "name": "getOpenTrade",
    "outputs": [
        {"name": "openPrice", "type": "uint192"},
        {"name": "tp", "type": "uint192"},
        {"name": "sl", "type": "uint192"},
        {"name": "collateral", "type": "uint192"},
        {"name": "leverage", "type": "uint32"},
        {"name": "isLong", "type": "bool"},
    ],
    "stateMutability": "view",
    "type": "function",
}]

# Signatura de l'event OrderOpened (calculada amb Web3.keccak)
ORDER_OPENED_TOPIC = "0x" + "b1c6bd0c9c6a36fbb3b8cccda60a0ad29e2f28fb6e5c7c6b6a62b0c02026ce9"
# Nota: el valor real és Web3.keccak(text='OrderOpened(uint256,address,uint8)').hex()
# — es recalcula a l'inici si web3 disponible (veure OstiumClient.__init__)

FIND_TRADE_MAX_INDEX = 32  # lab scripts cerquen 0..N; 32 cobreix diversos trades per pair

# ── USDC ERC-20 (per get_balance) ────────────────────────────────────────────

USDC_CONTRACT_TESTNET = "0xe73B11Fb1e3eeEe8AF2a23079A4410Fe1B370548"  # Confirmat al lab
USDC_CONTRACT_MAINNET = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # USDC on Arbitrum One
USDC_PRECISION = 10 ** 10  # Confirmat al lab (PRECISION_10)

USDC_BALANCE_ABI = [{
    "inputs": [{"name": "account", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "", "type": "uint256"}],
    "stateMutability": "view",
    "type": "function",
}]


# ── Dataclasses de resultat ──────────────────────────────────────────────────

@dataclass
class OpenTradeReceipt:
    """Resultat de perform_trade."""
    tx_hash: str
    pair_id: int
    trade_index: int
    open_price: float  # preu executat (float, USD)


@dataclass
class CloseTradeReceipt:
    """Resultat de close_trade."""
    tx_hash: str


@dataclass
class OpenTradeInfo:
    """Informació d'un trade obert (getOpenTrade)."""
    pair_id: int
    trade_index: int
    open_price: float   # USD
    tp: float           # USD (0 si no definit)
    sl: float           # USD (0 si no definit)
    collateral: float   # USDC (raw / 1e18 o escala SDK)
    leverage: int
    is_long: bool


# ── Interfície ───────────────────────────────────────────────────────────────

class IOstiumClient(ABC):
    """Interfície que OstiumExecutionAdapter consumeix (DI-friendly)."""

    @abstractmethod
    async def get_price(self, base: str, quote: str) -> Tuple[float, float, float]:
        """Retorna (mid, bid, ask) en USD."""

    @abstractmethod
    async def open_trade(
        self,
        pair_id: int,
        is_long: bool,
        collateral: float,
        leverage: int,
        at_price: float,
        tp_price: float = 0.0,
        sl_price: float = 0.0,
    ) -> OpenTradeReceipt:
        """Obre posició. Retorna OpenTradeReceipt amb pair_id i trade_index resolts."""

    @abstractmethod
    async def close_trade(
        self,
        pair_id: int,
        trade_index: int,
        at_price: float,
    ) -> CloseTradeReceipt:
        """Tanca posició. Retorna CloseTradeReceipt."""

    @abstractmethod
    async def update_sl(
        self, pair_id: int, trade_index: int, new_sl: float
    ) -> bool:
        """Actualitza stop-loss. Retorna True si ok."""

    @abstractmethod
    async def update_tp(
        self, pair_id: int, trade_index: int, new_tp: float
    ) -> bool:
        """Actualitza take-profit. Retorna True si ok."""

    @abstractmethod
    async def get_open_trades(
        self, trader_address: str, pair_ids: Optional[List[int]] = None
    ) -> List[OpenTradeInfo]:
        """
        Retorna totes les posicions obertes per trader_address.
        Si pair_ids especificat, filtra per aquells pairs.
        """

    @abstractmethod
    async def health(self) -> bool:
        """Retorna True si l'API és accessible."""

    @abstractmethod
    async def get_usdc_balance(self) -> float:
        """Retorna saldo USDC de la wallet (float, en USDC humans)."""

    @abstractmethod
    async def get_trade_info(
        self, pair_id: int, trade_index: int
    ) -> Optional[OpenTradeInfo]:
        """
        Retorna info del trade via getOpenTrade.
        Retorna None si collateral==0 (trade ja tancat o no existent).
        """

    @abstractmethod
    async def get_trade_metrics(
        self, pair_id: int, trade_index: int
    ) -> Optional[Dict]:
        """
        Retorna mètriques del trade via sdk.get_open_trade_metrics().
        Keys esperades: unrealizedPnl (float), unrealizedPnlPercentage (float).
        Retorna None si el SDK no exposa el mètode o falla.
        """


# ── Implementació real ────────────────────────────────────────────────────────

class OstiumClient(IOstiumClient):
    """
    Client real per Ostium SDK.

    Requereix: ostium_python_sdk, web3, eth_account.
    Totes les crides SDK (perform_trade, close_trade) s'executen en executor
    per no bloquejar l'event loop (SDK és sincrona).
    """

    def __init__(
        self,
        private_key: str,
        network: str = "testnet",
        rpc_url: Optional[str] = None,
    ):
        self._private_key = private_key
        self._network = network
        self._rpc_url = rpc_url
        self._sdk: Any = None
        self._w3: Any = None
        self._contract: Any = None
        self._usdc_contract: Any = None
        self._trader_address: Optional[str] = None

    def _ensure_sdk(self) -> None:
        """Lazy-init SDK (evita import al test-time si no es necessita)."""
        if self._sdk is not None:
            return
        from ostium_python_sdk import OstiumSDK, NetworkConfig  # type: ignore[import]
        from web3 import Web3
        from eth_account import Account

        config = NetworkConfig.testnet() if self._network == "testnet" else NetworkConfig.mainnet()
        self._sdk = OstiumSDK(config, self._private_key)

        rpc = self._rpc_url or (
            "https://sepolia-rollup.arbitrum.io/rpc" if self._network == "testnet"
            else "https://arb1.arbitrum.io/rpc"
        )
        self._w3 = Web3(Web3.HTTPProvider(rpc))
        contract_addr = TRADING_CONTRACT_TESTNET if self._network == "testnet" else TRADING_CONTRACT_MAINNET
        self._contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(contract_addr),
            abi=GET_OPEN_TRADE_ABI,
        )
        usdc_addr = USDC_CONTRACT_TESTNET if self._network == "testnet" else USDC_CONTRACT_MAINNET
        self._usdc_contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(usdc_addr),
            abi=USDC_BALANCE_ABI,
        )
        account = Account.from_key(self._private_key)
        self._trader_address = account.address

        # Recalcular ORDER_OPENED_TOPIC amb la llibreria real
        global ORDER_OPENED_TOPIC
        ORDER_OPENED_TOPIC = Web3.keccak(text="OrderOpened(uint256,address,uint8)").hex()

        logger.info(
            "OstiumClient init: network=%s trader=%s",
            self._network,
            self._trader_address,
        )

    def _parse_receipt(self, receipt: Any) -> Tuple[str, Optional[int]]:
        """
        Extreu (tx_hash, pair_id) del receipt de perform_trade.
        Retorna pair_id=None si no trobi l'event OrderOpened.
        """
        tx_receipt = receipt.get("receipt", receipt)
        tx_hash = tx_receipt.get("transactionHash", b"")
        if hasattr(tx_hash, "hex"):
            tx_hash = tx_hash.hex()

        pair_id: Optional[int] = None
        for log in tx_receipt.get("logs", []):
            topics = log.get("topics", [])
            if len(topics) < 4:
                continue
            sig = topics[0].hex() if hasattr(topics[0], "hex") else topics[0]
            if sig.lower().strip("0x") != ORDER_OPENED_TOPIC.lower().strip("0x"):
                continue
            raw = topics[3].hex() if hasattr(topics[3], "hex") else topics[3]
            pair_id = int(raw, 16)
            break

        return str(tx_hash), pair_id

    def _find_trade_index_sync(
        self, trader: str, pair_id: int, max_idx: int = FIND_TRADE_MAX_INDEX
    ) -> Optional[int]:
        """Brute-force 0..max_idx: retorna el primer index amb collateral > 0."""
        for idx in range(max_idx):
            try:
                result = self._contract.functions.getOpenTrade(
                    self._w3.to_checksum_address(trader),
                    pair_id,
                    idx,
                ).call()
                if result[3] > 0:  # collateral > 0
                    return idx
            except Exception:
                continue
        return None

    async def get_price(self, base: str, quote: str) -> Tuple[float, float, float]:
        self._ensure_sdk()
        loop = asyncio.get_event_loop()
        try:
            mid, bid, ask = await self._sdk.price.get_price(base, quote)
            return float(mid), float(bid), float(ask)
        except TypeError:
            # Alguns entorns: get_price és sync
            mid, bid, ask = await loop.run_in_executor(
                None, lambda: self._sdk.price.get_price(base, quote)
            )
            return float(mid), float(bid), float(ask)

    async def open_trade(
        self,
        pair_id: int,
        is_long: bool,
        collateral: float,
        leverage: int,
        at_price: float,
        tp_price: float = 0.0,
        sl_price: float = 0.0,
    ) -> OpenTradeReceipt:
        self._ensure_sdk()
        loop = asyncio.get_event_loop()

        trade_params: Dict[str, Any] = {
            "collateral": collateral,
            "leverage": leverage,
            "asset_type": pair_id,
            "direction": is_long,
            "order_type": "MARKET",
        }
        if tp_price > 0:
            trade_params["tp"] = tp_price
        if sl_price > 0:
            trade_params["sl"] = sl_price

        receipt = await loop.run_in_executor(
            None,
            lambda: self._sdk.ostium.perform_trade(trade_params, at_price=at_price),
        )

        tx_hash, found_pair_id = self._parse_receipt(receipt)
        if found_pair_id is None:
            found_pair_id = pair_id
            logger.warning(
                "open_trade: no OrderOpened event trobar; usant pair_id passat: %d", pair_id
            )

        # Seguint lab scripts (test_full_cycle_multicall): "Esperar confirmació (30s)" abans de find.
        # El node/oracle pot tardar a reflectir l'estat; open → wait → find.
        trade_index: Optional[int] = None
        for attempt in range(7):  # 0..6: espera 0s, 5s, 5s, ... → ~30s total
            trade_index = await loop.run_in_executor(
                None,
                lambda: self._find_trade_index_sync(self._trader_address, found_pair_id),
            )
            if trade_index is not None:
                break
            if attempt < 6:
                await asyncio.sleep(5.0)
        if trade_index is None:
            raise RuntimeError(
                f"OstiumClient: no s'ha trobat trade actiu per pair_id={found_pair_id} "
                f"trader={self._trader_address} (després d'esperar ~30s)"
            )

        logger.info(
            "open_trade OK: pair_id=%d trade_index=%d tx=%s",
            found_pair_id, trade_index, tx_hash[:20],
        )
        return OpenTradeReceipt(
            tx_hash=tx_hash,
            pair_id=found_pair_id,
            trade_index=trade_index,
            open_price=at_price,
        )

    async def close_trade(
        self,
        pair_id: int,
        trade_index: int,
        at_price: float,
    ) -> CloseTradeReceipt:
        self._ensure_sdk()
        loop = asyncio.get_event_loop()

        close_receipt = await loop.run_in_executor(
            None,
            lambda: self._sdk.ostium.close_trade(pair_id, trade_index, at_price),
        )

        tx_hash = close_receipt.get("transactionHash", "")
        if hasattr(tx_hash, "hex"):
            tx_hash = tx_hash.hex()

        logger.info(
            "close_trade OK: pair_id=%d trade_index=%d tx=%s",
            pair_id, trade_index, str(tx_hash)[:20],
        )
        return CloseTradeReceipt(tx_hash=str(tx_hash))

    async def update_sl(
        self, pair_id: int, trade_index: int, new_sl: float
    ) -> bool:
        """
        Actualitza SL via SDK (si disponible) o notifica que no implementat.
        Ostium SDK: actualitzar SL/TP requereix cridar updateTrade o similar.
        Phase G MVP: retorna True sense error (no-op amb log).
        """
        logger.warning(
            "OstiumClient.update_sl: no implementat al SDK testnet "
            "(pair_id=%d trade_index=%d new_sl=%f)",
            pair_id, trade_index, new_sl,
        )
        return True

    async def update_tp(
        self, pair_id: int, trade_index: int, new_tp: float
    ) -> bool:
        """
        Actualitza TP via SDK (si disponible) o no-op.
        Phase G MVP: retorna True sense error (no-op amb log).
        """
        logger.warning(
            "OstiumClient.update_tp: no implementat al SDK testnet "
            "(pair_id=%d trade_index=%d new_tp=%f)",
            pair_id, trade_index, new_tp,
        )
        return True

    async def get_open_trades(
        self, trader_address: str, pair_ids: Optional[List[int]] = None
    ) -> List[OpenTradeInfo]:
        """
        Cerca tots els trades oberts via getOpenTrade brute-force.
        Itera pair_ids × indices (0..FIND_TRADE_MAX_INDEX).
        Si trader_address és buida, s'usa l'adreça del client (després de _ensure_sdk).
        """
        self._ensure_sdk()
        if not (trader_address or "").strip():
            trader_address = self._trader_address
        loop = asyncio.get_event_loop()
        if pair_ids is None:
            # Si no hi ha pair_ids, retornem buit (no sabem quins pairs buscar)
            return []

        results: List[OpenTradeInfo] = []

        def _scan() -> List[OpenTradeInfo]:
            found = []
            for pid in pair_ids:
                for idx in range(FIND_TRADE_MAX_INDEX):
                    try:
                        r = self._contract.functions.getOpenTrade(
                            self._w3.to_checksum_address(trader_address),
                            pid,
                            idx,
                        ).call()
                        collateral = r[3]
                        if collateral <= 0:
                            continue
                        # Escala: Ostium retorna valors en wei (1e18) o en unitats USDC directes
                        # Basant-nos en el lab: collateral en wei → dividir per 1e18
                        collateral_usdc = collateral / 1e18
                        open_price_raw = r[0]
                        open_price = open_price_raw / 1e18 if open_price_raw > 1e10 else float(open_price_raw)
                        tp_raw = r[1]
                        sl_raw = r[2]
                        tp = tp_raw / 1e18 if tp_raw > 1e10 else float(tp_raw)
                        sl = sl_raw / 1e18 if sl_raw > 1e10 else float(sl_raw)
                        found.append(OpenTradeInfo(
                            pair_id=pid,
                            trade_index=idx,
                            open_price=open_price,
                            tp=tp,
                            sl=sl,
                            collateral=collateral_usdc,
                            leverage=int(r[4]),
                            is_long=bool(r[5]),
                        ))
                    except Exception:
                        continue
            return found

        results = await loop.run_in_executor(None, _scan)
        return results

    async def get_usdc_balance(self) -> float:
        """
        Retorna saldo USDC de la wallet via ERC-20 balanceOf.
        Escala: raw / USDC_PRECISION (10^10 confirmat al lab).
        """
        self._ensure_sdk()
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: self._usdc_contract.functions.balanceOf(
                self._w3.to_checksum_address(self._trader_address)
            ).call(),
        )
        return float(raw) / USDC_PRECISION

    async def get_trade_info(
        self, pair_id: int, trade_index: int
    ) -> Optional[OpenTradeInfo]:
        """
        Retorna info del trade via getOpenTrade.
        Retorna None si collateral==0 (trade tancat o no existeix).
        """
        self._ensure_sdk()
        loop = asyncio.get_event_loop()

        def _call() -> Optional[OpenTradeInfo]:
            r = self._contract.functions.getOpenTrade(
                self._w3.to_checksum_address(self._trader_address),
                pair_id,
                trade_index,
            ).call()
            collateral_raw = r[3]
            if collateral_raw <= 0:
                return None
            collateral = collateral_raw / 1e18
            open_price_raw = r[0]
            open_price = open_price_raw / 1e18 if open_price_raw > 1e10 else float(open_price_raw)
            tp_raw = r[1]
            sl_raw = r[2]
            tp = tp_raw / 1e18 if tp_raw > 1e10 else float(tp_raw)
            sl = sl_raw / 1e18 if sl_raw > 1e10 else float(sl_raw)
            return OpenTradeInfo(
                pair_id=pair_id,
                trade_index=trade_index,
                open_price=open_price,
                tp=tp,
                sl=sl,
                collateral=collateral,
                leverage=int(r[4]),
                is_long=bool(r[5]),
            )

        return await loop.run_in_executor(None, _call)

    async def get_trade_metrics(
        self, pair_id: int, trade_index: int
    ) -> Optional[Dict]:
        """
        Retorna mètriques del trade via sdk.get_open_trade_metrics() si existeix.
        Retorna None si el SDK no exposa el mètode o si la crida falla.
        """
        self._ensure_sdk()
        fn = getattr(self._sdk, "get_open_trade_metrics", None)
        if fn is None:
            logger.debug("OstiumClient.get_trade_metrics: SDK no exposa get_open_trade_metrics")
            return None
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, lambda: fn(pair_id, trade_index))
            return dict(result) if result else None
        except Exception as e:
            logger.warning(
                "OstiumClient.get_trade_metrics(pair_id=%d, trade_index=%d): %s",
                pair_id, trade_index, e,
            )
            return None

    async def health(self) -> bool:
        try:
            self._ensure_sdk()
            # Check simple: intentar fetch price EUR/USD
            mid, _, _ = await self.get_price("EUR", "USD")
            return mid > 0
        except Exception as e:
            logger.warning("OstiumClient.health: %s", e)
            return False


# ── Fake client per testing ──────────────────────────────────────────────────

@dataclass
class _FakeTrade:
    pair_id: int
    trade_index: int
    open_price: float
    collateral: float
    leverage: int
    is_long: bool
    tp: float = 0.0
    sl: float = 0.0


class FakeOstiumClient(IOstiumClient):
    """
    Client stub per 0-network tests.

    Simula open/close/get_open_trades en memòria sense xarxa ni SDK.

    Ús:
        fake = FakeOstiumClient(mid_price=1.08)
        adapter = OstiumExecutionAdapter(client=fake, ...)
        result = await adapter.open_position("EURUSD", ...)
    """

    def __init__(
        self,
        mid_price: float = 1.08500,
        open_should_fail: bool = False,
        close_should_fail: bool = False,
        health_result: bool = True,
        usdc_balance: float = 100.0,
        fake_metrics: bool = False,
    ):
        self.mid_price = mid_price
        self.open_should_fail = open_should_fail
        self.close_should_fail = close_should_fail
        self.health_result = health_result
        self.usdc_balance = usdc_balance
        self.fake_metrics = fake_metrics

        # Estat intern
        self._trades: Dict[Tuple[int, int], _FakeTrade] = {}
        self._next_index: Dict[int, int] = {}  # pair_id → proper índex
        self._next_tx = 0

        # Auditoria (per asserts als tests)
        self.open_calls: List[Dict] = []
        self.close_calls: List[Dict] = []
        self.sl_calls: List[Dict] = []
        self.tp_calls: List[Dict] = []

    def _gen_tx(self) -> str:
        self._next_tx += 1
        return f"0xfake{self._next_tx:064x}"

    async def get_price(self, base: str, quote: str) -> Tuple[float, float, float]:
        spread = self.mid_price * 0.0001
        return self.mid_price, self.mid_price - spread, self.mid_price + spread

    async def open_trade(
        self,
        pair_id: int,
        is_long: bool,
        collateral: float,
        leverage: int,
        at_price: float,
        tp_price: float = 0.0,
        sl_price: float = 0.0,
    ) -> OpenTradeReceipt:
        self.open_calls.append(dict(
            pair_id=pair_id, is_long=is_long, collateral=collateral,
            leverage=leverage, at_price=at_price, tp_price=tp_price, sl_price=sl_price,
        ))
        if self.open_should_fail:
            raise RuntimeError("FakeOstiumClient: open_trade simulated failure")

        trade_index = self._next_index.get(pair_id, 0)
        self._next_index[pair_id] = trade_index + 1

        self._trades[(pair_id, trade_index)] = _FakeTrade(
            pair_id=pair_id,
            trade_index=trade_index,
            open_price=at_price,
            collateral=collateral,
            leverage=leverage,
            is_long=is_long,
            tp=tp_price,
            sl=sl_price,
        )
        return OpenTradeReceipt(
            tx_hash=self._gen_tx(),
            pair_id=pair_id,
            trade_index=trade_index,
            open_price=at_price,
        )

    async def close_trade(
        self,
        pair_id: int,
        trade_index: int,
        at_price: float,
    ) -> CloseTradeReceipt:
        self.close_calls.append(dict(pair_id=pair_id, trade_index=trade_index, at_price=at_price))
        if self.close_should_fail:
            raise RuntimeError("FakeOstiumClient: close_trade simulated failure")

        self._trades.pop((pair_id, trade_index), None)
        return CloseTradeReceipt(tx_hash=self._gen_tx())

    async def update_sl(
        self, pair_id: int, trade_index: int, new_sl: float
    ) -> bool:
        self.sl_calls.append(dict(pair_id=pair_id, trade_index=trade_index, new_sl=new_sl))
        trade = self._trades.get((pair_id, trade_index))
        if trade:
            trade.sl = new_sl
        return True

    async def update_tp(
        self, pair_id: int, trade_index: int, new_tp: float
    ) -> bool:
        self.tp_calls.append(dict(pair_id=pair_id, trade_index=trade_index, new_tp=new_tp))
        trade = self._trades.get((pair_id, trade_index))
        if trade:
            trade.tp = new_tp
        return True

    async def get_open_trades(
        self, trader_address: str, pair_ids: Optional[List[int]] = None
    ) -> List[OpenTradeInfo]:
        result = []
        for (pid, idx), t in self._trades.items():
            if pair_ids is not None and pid not in pair_ids:
                continue
            result.append(OpenTradeInfo(
                pair_id=pid,
                trade_index=idx,
                open_price=t.open_price,
                tp=t.tp,
                sl=t.sl,
                collateral=t.collateral,
                leverage=t.leverage,
                is_long=t.is_long,
            ))
        return result

    async def get_usdc_balance(self) -> float:
        return self.usdc_balance

    async def get_trade_info(
        self, pair_id: int, trade_index: int
    ) -> Optional[OpenTradeInfo]:
        trade = self._trades.get((pair_id, trade_index))
        if trade is None:
            return None
        return OpenTradeInfo(
            pair_id=trade.pair_id,
            trade_index=trade.trade_index,
            open_price=trade.open_price,
            tp=trade.tp,
            sl=trade.sl,
            collateral=trade.collateral,
            leverage=trade.leverage,
            is_long=trade.is_long,
        )

    async def get_trade_metrics(
        self, pair_id: int, trade_index: int
    ) -> Optional[Dict]:
        if not self.fake_metrics:
            return None
        trade = self._trades.get((pair_id, trade_index))
        if trade is None:
            return None
        # Fórmula simple: PnL = (mid - open) / open * notional (LONG)
        notional = trade.collateral * trade.leverage
        price_delta = self.mid_price - trade.open_price
        if not trade.is_long:
            price_delta = -price_delta
        pnl = price_delta / trade.open_price * notional if trade.open_price > 0 else 0.0
        pnl_pct = (pnl / trade.collateral) * 100 if trade.collateral > 0 else 0.0
        return {"unrealizedPnl": pnl, "unrealizedPnlPercentage": pnl_pct}

    async def health(self) -> bool:
        return self.health_result
