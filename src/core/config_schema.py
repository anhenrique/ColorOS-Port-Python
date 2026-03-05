"""
简化版配置验证模块
"""
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional


def validate_replacements(data: Dict) -> List[str]:
    """验证 replacements.json"""
    errors = []
    if "replacements" not in data:
        errors.append("Missing required field 'replacements'")
        return errors
    
    for i, rule in enumerate(data["replacements"]):
        if "description" not in rule:
            errors.append(f"Rule [{i}]: Missing 'description'")
        if "type" not in rule:
            errors.append(f"Rule [{i}]: Missing 'type'")
    return errors


def validate_features(data: Dict) -> List[str]:
    """验证 features.json"""
    errors = []
    valid_keys = {
        "oplus_feature", "app_feature", "permission_feature",
        "permission_oplus_feature", "features_remove", "features_remove_force",
        "features_remove_conditional", "xml_features", "build_props",
        "props_remove", "props_add"
    }
    for key in data.keys():
        if key not in valid_keys:
            errors.append(f"Unknown field: '{key}'")
    return errors


def validate_port_config(data: Dict) -> List[str]:
    """验证 port_config.json"""
    errors = []
    required = ["partition_to_port", "possible_super_list"]
    for field in required:
        if field not in data:
            errors.append(f"Missing required field: '{field}'")
    return errors


def validate_config(config_path: str) -> Tuple[bool, List[str]]:
    """验证单个配置文件"""
    path = Path(config_path)
    if not path.exists():
        return False, [f"File not found: {config_path}"]
    
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]
    
    filename = path.name
    errors = []
    
    if filename == "replacements.json":
        errors = validate_replacements(data)
    elif filename == "features.json":
        errors = validate_features(data)
    elif filename == "port_config.json":
        errors = validate_port_config(data)
    else:
        return True, []
    
    return len(errors) == 0, errors


def validate_all_configs(base_dir: str = "devices") -> Dict[str, Tuple[bool, List[str]]]:
    """验证所有配置文件"""
    results = {}
    base = Path(base_dir)
    
    for pattern in ["**/replacements.json", "**/features.json", "**/port_config.json"]:
        for config_file in base.glob(pattern):
            is_valid, errors = validate_config(str(config_file))
            results[str(config_file)] = (is_valid, errors)
    
    return results
