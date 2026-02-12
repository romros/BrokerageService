"""
BrokerageService Configuration
"""


from datetime import datetime
from enum import Enum
from typing import Optional
import os

from pydantic import BaseModel, Field


class BrokerageMode(str, Enum):
    """Brokerage operation mode"""
    LIVE = "live"
    PAPER = "paper"
    BACKTEST = "backtest"


class BrokerageConfig(BaseModel):
    """
    Configuration for BrokerageService

    Loaded from environment variables with sensible defaults
    """

    # ============ MODE ============
    mode: BrokerageMode = Field(
        default=BrokerageMode.PAPER,
        description="Operation mode: live, paper, or backtest"
    )

    # ============ API SERVER ============
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8080, description="API port")
    ws_port: int = Field(default=8081, description="WebSocket port")

    # ============ OSTIUM (Live/Paper) ============
    ostium_network: str = Field(
        default="testnet",
        description="Ostium network: mainnet or testnet"
    )
    ostium_private_key: Optional[str] = Field(
        default=None,
        description="Private key for blockchain transactions"
    )
    ostium_rpc_url: Optional[str] = Field(
        default=None,
        description="RPC URL for Arbitrum network"
    )
    price_poll_interval: int = Field(
        default=30,
        description="Seconds between price polls (live/paper)"
    )

    # ============ BACKTEST ============
    backtest_speed: int = Field(
        default=1000,
        description="Speed multiplier for backtest (1000x = 1000x faster)"
    )
    backtest_data_path: str = Field(
        default="data/candles",
        description="Path to historical candle data"
    )
    backtest_start_date: Optional[datetime] = Field(
        default=None,
        description="Backtest start date"
    )
    backtest_end_date: Optional[datetime] = Field(
        default=None,
        description="Backtest end date"
    )
    backtest_initial_balance: float = Field(
        default=10000.0,
        description="Initial USDC balance for backtest"
    )

    # ============ PAPER TRADING ============
    paper_initial_balance: float = Field(
        default=10000.0,
        description="Initial USDC balance for paper trading"
    )
    paper_slippage_percent: float = Field(
        default=0.1,
        description="Simulated slippage percentage for paper trading"
    )

    # ============ LOGGING ============
    log_level: str = Field(default="INFO", description="Logging level")
    log_dir: str = Field(default="logs", description="Log directory")

    @classmethod
    def from_env(cls) -> "BrokerageConfig":
        """
        Load configuration from environment variables

        Environment variables:
        - MODE: live | paper | backtest
        - OSTIUM_NETWORK: mainnet | testnet
        - OSTIUM_PRIVATE_KEY: Private key
        - OSTIUM_RPC_URL: RPC URL
        - PRICE_POLL_INTERVAL: Seconds
        - BACKTEST_SPEED: Multiplier
        - BACKTEST_DATA_PATH: Path
        - BACKTEST_START_DATE: ISO format
        - BACKTEST_END_DATE: ISO format
        - BACKTEST_INITIAL_BALANCE: Float
        - PAPER_INITIAL_BALANCE: Float
        - PAPER_SLIPPAGE_PERCENT: Float
        - LOG_LEVEL: DEBUG | INFO | WARNING | ERROR
        """
        config_dict = {
            "mode": os.getenv("MODE", "paper"),
            "api_host": os.getenv("API_HOST", "0.0.0.0"),
            "api_port": int(os.getenv("API_PORT", "8080")),
            "ws_port": int(os.getenv("WS_PORT", "8081")),
            "ostium_network": os.getenv("OSTIUM_NETWORK", "testnet"),
            "ostium_private_key": os.getenv("OSTIUM_PRIVATE_KEY"),
            "ostium_rpc_url": os.getenv("OSTIUM_RPC_URL"),
            "price_poll_interval": int(os.getenv("PRICE_POLL_INTERVAL", "30")),
            "backtest_speed": int(os.getenv("BACKTEST_SPEED", "1000")),
            "backtest_data_path": os.getenv("BACKTEST_DATA_PATH", "data/candles"),
            "backtest_initial_balance": float(
                os.getenv("BACKTEST_INITIAL_BALANCE", "10000.0")
            ),
            "paper_initial_balance": float(
                os.getenv("PAPER_INITIAL_BALANCE", "10000.0")
            ),
            "paper_slippage_percent": float(
                os.getenv("PAPER_SLIPPAGE_PERCENT", "0.1")
            ),
            "log_level": os.getenv("LOG_LEVEL", "INFO"),
            "log_dir": os.getenv("LOG_DIR", "logs"),
        }

        # Parse dates if provided
        start_date_str = os.getenv("BACKTEST_START_DATE")
        if start_date_str:
            config_dict["backtest_start_date"] = datetime.fromisoformat(
                start_date_str
            )

        end_date_str = os.getenv("BACKTEST_END_DATE")
        if end_date_str:
            config_dict["backtest_end_date"] = datetime.fromisoformat(end_date_str)

        return cls(**config_dict)

    def validate_for_mode(self) -> None:
        """
        Validate configuration for current mode

        Raises:
            ValueError: If required fields are missing
        """
        if self.mode == BrokerageMode.LIVE:
            if not self.ostium_private_key:
                raise ValueError("OSTIUM_PRIVATE_KEY required for live mode")
            if not self.ostium_rpc_url:
                raise ValueError("OSTIUM_RPC_URL required for live mode")

        elif self.mode == BrokerageMode.PAPER:
            if not self.ostium_rpc_url:
                raise ValueError("OSTIUM_RPC_URL required for paper mode")

        elif self.mode == BrokerageMode.BACKTEST:
            if not self.backtest_start_date:
                raise ValueError("BACKTEST_START_DATE required for backtest mode")
            if not self.backtest_end_date:
                raise ValueError("BACKTEST_END_DATE required for backtest mode")
