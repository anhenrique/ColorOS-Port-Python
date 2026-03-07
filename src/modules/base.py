from abc import ABC, abstractmethod
import logging
from typing import Any, Optional

class BaseModule(ABC):
    """
    Base class for high-level porting features (modules).
    Modules represent major functional changes like 'GMS Fix', 'CN Bloatware Removal', etc.
    """
    name: str = "base_module"
    description: str = "Base Feature Module"
    priority: int = 100

    def __init__(self, context: Any, logger: Optional[logging.Logger] = None):
        self.ctx = context
        self.logger = logger or logging.getLogger(f"Module:{self.name}")
        self.enabled = True

    @abstractmethod
    def run(self) -> bool:
        """
        Execute the module logic.
        Returns:
            bool: True if successful, False otherwise.
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', priority={self.priority})"
