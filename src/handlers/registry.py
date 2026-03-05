"""
Handlers Registry Module

Provides centralized handler registration and management.
"""

from typing import Dict, Any, List
import logging

from .base import BaseHandler


class HandlerRegistry:
    """
    Central registry for all feature handlers.

    Manages handler registration, validation, and execution.
    """

    def __init__(self):
        self.handlers: List[BaseHandler] = []
        self.logger = logging.getLogger(self.__class__.__name__)

    def register(self, handler: BaseHandler) -> "HandlerRegistry":
        """
        Register a handler.

        Args:
            handler: Handler instance to register

        Returns:
            Self for method chaining
        """
        self.handlers.append(handler)
        self.logger.debug(f"Registered handler: {handler.__class__.__name__}")
        return self

    def apply_all(self, config: Dict[str, Any], context: Any) -> None:
        """
        Apply all applicable handlers to the configuration.

        Args:
            config: Configuration dictionary
            context: BuildContext object
        """
        for handler in self.handlers:
            if handler.can_handle(config):
                try:
                    errors = handler.validate(config)
                    if errors:
                        self.logger.warning(
                            f"{handler.__class__.__name__} validation failed:"
                        )
                        for error in errors:
                            self.logger.warning(f"  - {error}")
                        continue

                    handler.apply(config, context)
                    self.logger.debug(
                        f"{handler.__class__.__name__} applied successfully"
                    )

                except Exception as e:
                    self.logger.error(
                        f"{handler.__class__.__name__} failed: {e}", exc_info=True
                    )

    def validate_all(self, config: Dict[str, Any]) -> List[str]:
        """
        Validate configuration against all handlers.

        Args:
            config: Configuration dictionary

        Returns:
            List of all validation errors
        """
        all_errors = []

        for handler in self.handlers:
            if handler.can_handle(config):
                errors = handler.validate(config)
                if errors:
                    all_errors.extend(
                        [f"{handler.__class__.__name__}: {e}" for e in errors]
                    )

        return all_errors


# Global registry instance
registry = HandlerRegistry()
