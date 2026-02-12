"""
IService interface

Interface for services that need lifecycle management:
- start() - Allocate resources
- stop() - Cleanup resources
- health_check() - Verify service health
"""


from abc import ABC, abstractmethod


class IService(ABC):
    """Interface for services with lifecycle"""

    @abstractmethod
    async def start(self) -> None:
        """
        Start service and allocate resources

        Called once when service initializes.
        Should be idempotent (safe to call multiple times).
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop service and cleanup resources

        Called once when service shuts down.
        Should cleanup all allocated resources.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if service is healthy

        Returns:
            True if service is operational, False otherwise
        """
        pass

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Check if service is currently running"""
        pass
