"""
Lifecycle module - Service lifecycle management

Exports:
- IService: Interface for services with lifecycle
- ServiceManager: Manages all services (singleton)
"""


from .manager import ServiceManager
from .service import IService

