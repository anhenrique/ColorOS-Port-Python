"""
Condition Engine Module

Provides flexible condition evaluation for feature handlers.
"""

import re
from typing import Dict, Any, List, Callable, Optional, Union
from dataclasses import dataclass, field
from enum import Enum


class ComparisonOp(Enum):
    """Comparison operators"""

    EQ = "eq"  # Equal
    NE = "ne"  # Not equal
    GT = "gt"  # Greater than
    GTE = "gte"  # Greater than or equal
    LT = "lt"  # Less than
    LTE = "lte"  # Less than or equal
    CONTAINS = "contains"  # String contains
    REGEX = "regex"  # Regular expression match
    IN = "in"  # In list
    NIN = "nin"  # Not in list


@dataclass
class ConditionContext:
    """
    Context object for condition evaluation.
    Contains all properties that can be used in conditions.
    """

    # Android versions
    base_android_version: int = 0
    port_android_version: int = 0
    base_android_sdk: int = 0
    port_android_sdk: int = 0

    # Device codes
    base_device_code: str = ""
    port_device_code: str = ""
    base_product_device: str = ""
    port_product_device: str = ""

    # ROM info
    port_rom_version: str = ""
    base_rom_version: str = ""
    security_patch: str = ""

    # ROM type flags
    port_is_coloros: bool = False
    port_is_coloros_global: bool = False
    port_is_oos: bool = False
    port_is_realme_ui: bool = False

    # Region and brand
    base_regionmark: str = ""
    port_area: str = ""
    port_brand: str = ""

    # Additional context (for extensibility)
    extra: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get attribute by name, supporting nested keys"""
        if hasattr(self, key):
            return getattr(self, key)
        if key in self.extra:
            return self.extra[key]

        # Support nested keys like "build.version"
        if "." in key:
            parts = key.split(".")
            value = self
            for part in parts:
                if hasattr(value, part):
                    value = getattr(value, part)
                elif isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return default
            return value

        return default


class ConditionEngine:
    """
    Condition evaluation engine.

    Supports various comparison operators and logical combinations.
    """

    def __init__(self):
        self.operators: Dict[str, Callable] = {
            # Comparison operators
            "eq": self._eq,
            "ne": self._ne,
            "gt": self._gt,
            "gte": self._gte,
            "lt": self._lt,
            "lte": self._lte,
            "contains": self._contains,
            "regex": self._regex,
            "in": self._in,
            "nin": self._nin,
            # Logical operators
            "not": self._not,
            "and": self._and,
            "or": self._or,
        }

    def evaluate(
        self, condition: Union[Dict, List, Any], context: ConditionContext
    ) -> bool:
        """
        Evaluate a condition against the given context.

        Args:
            condition: Condition specification
                Examples:
                - Simple: {"base_android_version": 15}
                - Comparison: {"gte": {"field": "base_android_version", "value": 15}}
                - Logical: {"and": [{"eq": {...}}, {"contains": {...}}]}
            context: Condition context with all available properties

        Returns:
            True if condition is met, False otherwise
        """
        if condition is None or condition == {}:
            return True

        # Handle list (treat as OR)
        if isinstance(condition, list):
            return any(self.evaluate(c, context) for c in condition)

        if not isinstance(condition, dict):
            # Simple value comparison against a field
            return bool(condition)

        # Check for operators
        for op, value in condition.items():
            if op in self.operators:
                return self.operators[op](value, context)

        # Shorthand form: {"base_android_version": 15} means eq
        for field, expected in condition.items():
            actual = context.get(field)
            if actual != expected:
                return False

        return True

    def register(self, name: str, handler: Callable) -> None:
        """Register a custom operator"""
        self.operators[name] = handler

    # Comparison operators
    def _eq(self, spec: Dict, context: ConditionContext) -> bool:
        """Equal comparison"""
        field = spec.get("field")
        value = spec.get("value")
        actual = context.get(field)
        return actual == value

    def _ne(self, spec: Dict, context: ConditionContext) -> bool:
        """Not equal comparison"""
        field = spec.get("field")
        value = spec.get("value")
        actual = context.get(field)
        return actual != value

    def _gt(self, spec: Dict, context: ConditionContext) -> bool:
        """Greater than comparison"""
        field = spec.get("field")
        value = spec.get("value")
        actual = context.get(field)
        try:
            return float(actual) > float(value)
        except (TypeError, ValueError):
            return False

    def _gte(self, spec: Dict, context: ConditionContext) -> bool:
        """Greater than or equal comparison"""
        field = spec.get("field")
        value = spec.get("value")
        actual = context.get(field)
        try:
            return float(actual) >= float(value)
        except (TypeError, ValueError):
            return False

    def _lt(self, spec: Dict, context: ConditionContext) -> bool:
        """Less than comparison"""
        field = spec.get("field")
        value = spec.get("value")
        actual = context.get(field)
        try:
            return float(actual) < float(value)
        except (TypeError, ValueError):
            return False

    def _lte(self, spec: Dict, context: ConditionContext) -> bool:
        """Less than or equal comparison"""
        field = spec.get("field")
        value = spec.get("value")
        actual = context.get(field)
        try:
            return float(actual) <= float(value)
        except (TypeError, ValueError):
            return False

    def _contains(self, spec: Dict, context: ConditionContext) -> bool:
        """String contains check"""
        field = spec.get("field")
        substring = spec.get("value")
        actual = str(context.get(field, ""))
        return substring in actual

    def _regex(self, spec: Dict, context: ConditionContext) -> bool:
        """Regular expression match"""
        field = spec.get("field")
        pattern = spec.get("pattern")
        actual = str(context.get(field, ""))
        try:
            return re.search(pattern, actual) is not None
        except re.error:
            return False

    def _in(self, spec: Dict, context: ConditionContext) -> bool:
        """Check if value is in list"""
        field = spec.get("field")
        values = spec.get("values", [])
        actual = context.get(field)
        return actual in values

    def _nin(self, spec: Dict, context: ConditionContext) -> bool:
        """Check if value is not in list"""
        field = spec.get("field")
        values = spec.get("values", [])
        actual = context.get(field)
        return actual not in values

    # Logical operators
    def _not(self, condition: Dict, context: ConditionContext) -> bool:
        """Logical NOT"""
        return not self.evaluate(condition, context)

    def _and(self, conditions: List[Dict], context: ConditionContext) -> bool:
        """Logical AND"""
        return all(self.evaluate(c, context) for c in conditions)

    def _or(self, conditions: List[Dict], context: ConditionContext) -> bool:
        """Logical OR"""
        return any(self.evaluate(c, context) for c in conditions)


# Global condition engine instance
condition_engine = ConditionEngine()
