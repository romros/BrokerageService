"""
Blockchain transaction errors

Classifies Web3 exceptions into actionable categories.
"""


from typing import Optional


class TxError(Exception):
    """Base exception for transaction errors"""
    def __init__(self, message: str, tx_hash: Optional[str] = None):
        super().__init__(message)
        self.tx_hash = tx_hash


class TxRevertError(TxError):
    """Transaction reverted (status=0 in receipt)"""
    def __init__(self, message: str, tx_hash: str, revert_reason: Optional[str] = None):
        super().__init__(message, tx_hash)
        self.revert_reason = revert_reason


class TxTimeoutError(TxError):
    """Transaction receipt not received within timeout"""
    pass


class TxNonceTooLowError(TxError):
    """Nonce already used"""
    pass


class TxUnderpricedError(TxError):
    """Gas price too low for mempool"""
    pass


class TxInsufficientFundsError(TxError):
    """Insufficient ETH for gas + value"""
    pass


class TxEstimationError(TxError):
    """Gas estimation failed (usually means tx would revert)"""
    def __init__(self, message: str, revert_reason: Optional[str] = None):
        super().__init__(message)
        self.revert_reason = revert_reason


def classify_web3_error(e: Exception, tx_hash: Optional[str] = None) -> TxError:
    """
    Classify Web3 exception into specific TxError subclass

    Args:
        e: Original exception from web3.py
        tx_hash: Transaction hash if known

    Returns:
        Specific TxError subclass
    """
    err_str = str(e).lower()

    # Nonce errors
    if "nonce too low" in err_str or "already known" in err_str:
        return TxNonceTooLowError(f"Nonce already used: {e}", tx_hash)

    # Gas price errors
    if "underpriced" in err_str or "replacement transaction underpriced" in err_str:
        return TxUnderpricedError(f"Gas price too low: {e}", tx_hash)

    # Insufficient funds
    if "insufficient funds" in err_str or "out of gas" in err_str:
        return TxInsufficientFundsError(f"Insufficient funds: {e}", tx_hash)

    # Estimation errors (usually means revert)
    if "execution reverted" in err_str or "gas required exceeds allowance" in err_str:
        return TxEstimationError(f"Estimation failed (tx would revert): {e}")

    # Generic error
    return TxError(f"Transaction error: {e}", tx_hash)
