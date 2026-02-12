"""
ServiceManager - Manages lifecycle of all services

Singleton that:
- Registers services
- Starts all services in order
- Stops all services in reverse order
- Health checks all services
"""


from typing import Dict, Optional

from .service import IService

from foundation.logging import get_logger


logger = get_logger(__name__)


class ServiceManager:
    """
    Manages lifecycle of all services (Singleton)

    Usage:
        manager = ServiceManager()
        manager.register("data", data_service)
        await manager.start_all()
        # ... application runs ...
        await manager.stop_all()
    """

    _instance: Optional['ServiceManager'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._services = {}
            cls._instance._started = False
        return cls._instance

    def __init__(self):
        # Prevent re-initialization
        pass

    def register(self, name: str, service: IService) -> None:
        """
        Register service

        Args:
            name: Service name (unique identifier)
            service: Service instance implementing IService
        """
        if name in self._services:
            logger.warning(f"Service '{name}' already registered, replacing")

        self._services[name] = service
        logger.info(f"Registered service: {name}")

    def unregister(self, name: str) -> None:
        """Unregister service"""
        if name in self._services:
            del self._services[name]
            logger.info(f"Unregistered service: {name}")

    async def start_all(self) -> None:
        """
        Start all services in registration order

        Raises:
            Exception: If any service fails to start
        """
        if self._started:
            logger.warning("Services already started")
            return

        logger.info("Starting all services...")

        for name, service in self._services.items():
            try:
                await service.start()
                logger.info(f"✓ Started: {name}")
            except Exception as e:
                logger.error(f"✗ Failed to start {name}: {e}")
                # Stop already started services
                await self._stop_started_services(name)
                raise

        self._started = True
        logger.info("All services started successfully")

    async def _stop_started_services(self, failed_service: str) -> None:
        """Stop services that were started before failure"""
        logger.info("Rolling back started services...")

        for name, service in self._services.items():
            if name == failed_service:
                break

            try:
                if service.is_running:
                    await service.stop()
                    logger.info(f"✓ Stopped: {name}")
            except Exception as e:
                logger.error(f"✗ Failed to stop {name} during rollback: {e}")

    async def stop_all(self) -> None:
        """Stop all services in reverse order"""
        if not self._started:
            logger.warning("Services not started")
            return

        logger.info("Stopping all services...")

        # Stop in reverse order
        for name, service in reversed(list(self._services.items())):
            try:
                await service.stop()
                logger.info(f"✓ Stopped: {name}")
            except Exception as e:
                logger.error(f"✗ Failed to stop {name}: {e}")
                # Continue stopping other services even if one fails

        self._started = False
        logger.info("All services stopped")

    async def health_check_all(self) -> Dict[str, bool]:
        """
        Check health of all services

        Returns:
            Dict mapping service name to health status
        """
        results = {}

        for name, service in self._services.items():
            try:
                health = await service.health_check()
                results[name] = health

                if health:
                    logger.debug(f"✓ {name}: healthy")
                else:
                    logger.warning(f"✗ {name}: unhealthy")

            except Exception as e:
                logger.error(f"✗ {name}: health check failed - {e}")
                results[name] = False

        return results

    @property
    def is_started(self) -> bool:
        """Check if services are started"""
        return self._started

    def list_services(self) -> list[str]:
        """Get list of registered service names"""
        return list(self._services.keys())
