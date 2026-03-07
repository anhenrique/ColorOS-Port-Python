"""
Handlers package for ColorOS Porting Tool

Provides modular handlers for feature modifications.
"""

from .base import BaseHandler
from .conditions import ConditionContext, ConditionEngine, condition_engine
from .xml_handler import XmlFeatureHandler
from .prop_handler import BuildPropHandler
from .smali_handler import SmaliHandler
from .registry import HandlerRegistry, registry

__all__ = [
    # Base
    "BaseHandler",
    # Conditions
    "ConditionContext",
    "ConditionEngine",
    "condition_engine",
    # Handlers
    "XmlFeatureHandler",
    "BuildPropHandler",
    "SmaliHandler",
    # Registry
    "HandlerRegistry",
    "registry",
]
