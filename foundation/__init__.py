"""
Foundation layer - Base infrastructure
"""


from .config import BrokerageConfig, BrokerageMode
from .lifecycle import IService, ServiceManager
from .logging import get_logger

