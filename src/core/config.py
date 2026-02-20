import json
from pathlib import Path

class Config:
    def __init__(self, config_data):
        self.partition_to_port = config_data.get("partition_to_port", [])
        self.possible_super_list = config_data.get("possible_super_list", [])
        self.repack_with_ext4 = config_data.get("repack_with_ext4", True)
        self.super_extended = config_data.get("super_extended", False)
        self.pack_with_dsu = config_data.get("pack_with_dsu", False)
        self.pack_method = config_data.get("pack_method", "erofs")
        self.ddr_type = config_data.get("ddr_type", "ddr4")
        self.reusabe_partition_list = config_data.get("reusabe_partition_list", [])
        self.system_dlkm_enabled = config_data.get("system_dlkm_enabled", False)
        self.vendor_dlkm_enabled = config_data.get("vendor_dlkm_enabled", False)
        self.assets_base_url = config_data.get("assets_base_url", "https://github.com/toraidl/ColorOS-Port-Python/releases/download/assets")

    @classmethod
    def load(cls, device_code=None):
        base_config_path = Path("devices/common/port_config.json")
        if not base_config_path.exists():
            raise FileNotFoundError("Base configuration not found in devices/common/port_config.json")

        with open(base_config_path, 'r') as f:
            config_data = json.load(f)

        if device_code:
            device_config_path = Path(f"devices/{device_code}/port_config.json")
            if device_config_path.exists():
                with open(device_config_path, 'r') as f:
                    device_data = json.load(f)
                    config_data.update(device_data)
        
        return cls(config_data)
