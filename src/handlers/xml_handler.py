"""
XML Feature Handler Module

Handles adding/removing features from XML files in my_product/etc.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import re
import logging

from .base import BaseHandler
from .conditions import ConditionContext, condition_engine


class XmlFeatureHandler(BaseHandler):
    """
    Handler for XML feature modifications.

    Supports adding and removing features from various XML files
    in the my_product/etc directory.
    """

    # Feature type definitions
    FEATURE_TYPES = {
        "oplus_feature": {
            "dir": "my_product/etc/extension",
            "base_file": "com.oplus.oplus-feature",
            "root_tag": "oplus-config",
            "node_tag": "oplus-feature",
        },
        "app_feature": {
            "dir": "my_product/etc/extension",
            "base_file": "com.oplus.app-features",
            "root_tag": "extend_features",
            "node_tag": "app_feature",
        },
        "permission_feature": {
            "dir": "my_product/etc/permissions",
            "base_file": "com.oplus.android-features",
            "root_tag": "permissions",
            "node_tag": "feature",
        },
        "permission_oplus_feature": {
            "dir": "my_product/etc/permissions",
            "base_file": "oplus.feature-android",
            "root_tag": "oplus-config",
            "node_tag": "oplus-feature",
        },
    }

    def __init__(self):
        super().__init__()
        self.condition_engine = condition_engine

    def can_handle(self, config: Dict[str, Any]) -> bool:
        """Check if config contains XML feature definitions"""
        xml_keys = set(self.FEATURE_TYPES.keys())
        xml_keys.update({k for k in config.keys() if k.endswith("_feature")})
        return bool(xml_keys.intersection(config.keys()))

    def validate(self, config: Dict[str, Any]) -> List[str]:
        """Validate XML feature configuration"""
        errors = []

        for feature_type in self.FEATURE_TYPES.keys():
            if feature_type not in config:
                continue

            features = config[feature_type]
            if not isinstance(features, list):
                errors.append(f"{feature_type} must be a list")
                continue

            for i, feature in enumerate(features):
                if isinstance(feature, dict):
                    if "name" not in feature:
                        errors.append(f"{feature_type}[{i}]: missing 'name' field")
                elif not isinstance(feature, str):
                    errors.append(f"{feature_type}[{i}]: must be string or dict")

        return errors

    def apply(self, config: Dict[str, Any], context: Any) -> None:
        """Apply XML feature modifications"""
        # Build condition context
        condition_ctx = self._build_condition_context(context)

        # Process additions
        for feature_type in self.FEATURE_TYPES.keys():
            if feature_type not in config:
                continue

            features = config[feature_type]
            meta = self.FEATURE_TYPES[feature_type]

            self.logger.info(f"Processing {len(features)} {feature_type}(s)")

            for feature_config in features:
                feature = self._parse_feature(feature_config)

                # Check condition
                if feature.get("condition"):
                    if not self.condition_engine.evaluate(
                        feature["condition"], condition_ctx
                    ):
                        self.logger.debug(
                            f"Skipping {feature['name']}: condition not met"
                        )
                        continue

                self._add_feature(context, feature, meta)

        # Process removals
        self._process_removals(config, context)

    def _parse_feature(self, config: Union[str, Dict]) -> Dict[str, Any]:
        """Parse feature configuration from various formats"""
        if isinstance(config, str):
            # Legacy format: "feature^comment^args"
            parts = config.split("^")
            return {
                "name": parts[0].strip(),
                "comment": parts[1].strip() if len(parts) > 1 else "",
                "args": parts[2].strip() if len(parts) > 2 else "",
                "condition": None,
            }
        elif isinstance(config, dict):
            # New format: structured dict
            return {
                "name": config["name"],
                "comment": config.get("comment", ""),
                "args": config.get("args", ""),
                "condition": config.get("condition"),
            }
        else:
            raise ValueError(f"Unsupported feature config type: {type(config)}")

    def _add_feature(self, context: Any, feature: Dict[str, str], meta: Dict) -> None:
        """Add a single feature to XML"""
        xml_path = self._get_xml_path(context, meta)

        # Check if already exists
        if xml_path.exists():
            tree = ET.parse(xml_path)
            root = tree.getroot()
            if self._feature_exists(root, feature["name"], meta["node_tag"]):
                self.logger.debug(f"Feature {feature['name']} already exists")
                return
        else:
            # Create new XML
            root = ET.Element(meta["root_tag"])
            tree = ET.ElementTree(root)

        root = tree.getroot()

        # Add comment if present
        if feature["comment"]:
            comment = ET.Comment(f" {feature['comment']} ")
            root.append(comment)

        # Add feature node
        node = ET.SubElement(root, meta["node_tag"])
        node.set("name", feature["name"])

        # Parse and add args
        if feature["args"]:
            self._parse_args(node, feature["args"])

        # Write with proper formatting
        self._write_xml(tree, xml_path)
        self.logger.info(f"Added feature: {feature['name']}")

    def _process_removals(self, config: Dict[str, Any], context: Any) -> None:
        """Process feature removals"""
        if "features_remove" not in config and "features_remove_force" not in config:
            return

        features_remove = config.get("features_remove", [])
        features_remove_force = config.get("features_remove_force", [])

        target_dir = context.target_dir / "my_product" / "etc"

        for feature_name in features_remove + features_remove_force:
            self._remove_feature(
                context, feature_name, force=feature_name in features_remove_force
            )

    def _remove_feature(
        self, context: Any, feature_name: str, force: bool = False
    ) -> None:
        """Remove a feature from XML files"""
        my_product_etc = context.target_dir / "my_product" / "etc"

        if not my_product_etc.exists():
            return

        # Check baserom unless force mode
        if not force and hasattr(context, "baserom"):
            if self._feature_in_baserom(context, feature_name):
                self.logger.info(
                    f"Feature {feature_name} exists in baserom, skipping removal"
                )
                return

        # Remove from all XML files
        for xml_file in my_product_etc.rglob("*.xml"):
            try:
                tree = ET.parse(xml_file)
                root = tree.getroot()

                modified = False
                for node in list(root):
                    if node.get("name") == feature_name:
                        root.remove(node)
                        modified = True

                if modified:
                    self._write_xml(tree, xml_file)
                    self.logger.info(
                        f"Removed feature {feature_name} from {xml_file.name}"
                    )

            except Exception as e:
                self.logger.warning(f"Failed to process {xml_file}: {e}")

    def _get_xml_path(self, context: Any, meta: Dict) -> Path:
        """Get the XML file path for a feature type"""
        target_dir = context.target_dir
        xml_dir = target_dir / meta["dir"]
        xml_dir.mkdir(parents=True, exist_ok=True)
        return xml_dir / f"{meta['base_file']}-ext.xml"

    def _feature_exists(
        self, root: ET.Element, feature_name: str, node_tag: str
    ) -> bool:
        """Check if a feature already exists in XML"""
        for node in root.findall(f".//{node_tag}"):
            if node.get("name") == feature_name:
                return True
        return False

    def _feature_in_baserom(self, context: Any, feature_name: str) -> bool:
        """Check if feature exists in baserom"""
        if not hasattr(context, "baserom") or not context.baserom:
            return False

        baserom_etc = context.baserom.extracted_dir / "my_product" / "etc"
        if not baserom_etc.exists():
            return False

        for xml_file in baserom_etc.rglob("*.xml"):
            try:
                tree = ET.parse(xml_file)
                root = tree.getroot()
                for node in root.iter():
                    if node.get("name") == feature_name:
                        return True
            except:
                pass

        return False

    def _parse_args(self, node: ET.Element, args: str) -> None:
        """Parse args string and add as attributes"""
        # Handle format: args="boolean:true" or just "boolean:true"
        if args.startswith("args="):
            args = args[5:].strip("\"'")

        # Parse key=value pairs
        for pair in args.split():
            if "=" in pair:
                key, value = pair.split("=", 1)
                node.set(key, value.strip("\"'"))

    def _write_xml(self, tree: ET.ElementTree, path: Path) -> None:
        """Write XML with proper formatting"""
        self._indent(tree.getroot())
        tree.write(path, encoding="utf-8", xml_declaration=True)

    def _indent(self, elem: ET.Element, level: int = 0) -> None:
        """Add indentation to XML elements"""
        i = "\n" + level * "    "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "    "
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for child in elem:
                self._indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    def _build_condition_context(self, context: Any) -> ConditionContext:
        """Build condition context from build context"""
        return ConditionContext(
            base_android_version=int(getattr(context, "base_android_version", 0) or 0),
            port_android_version=int(getattr(context, "port_android_version", 0) or 0),
            base_product_device=getattr(context, "base_product_device", ""),
            port_product_device=getattr(context, "port_product_device", ""),
            port_rom_version=getattr(context, "target_rom_version", ""),
            port_is_coloros=getattr(context, "port_is_coloros", False),
            port_is_coloros_global=getattr(context, "port_is_coloros_global", False),
            port_is_oos=getattr(context, "port_is_oos", False),
            port_is_realme_ui=getattr(context, "port_is_realme_ui", False),
            base_regionmark=getattr(context, "base_regionmark", ""),
            port_area=getattr(context, "port_area", ""),
            port_brand=getattr(context, "port_brand", ""),
        )
