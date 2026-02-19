# ColorOS Port Python

A Python-based porting tool for ColorOS, inspired by the HyperOS-Port-Python project.

## Features

- **Context-Aware Architecture**: Uses a `Context` object to manage the entire porting lifecycle.
- **Modular Design**: Separates concerns into distinct modules (`rom`, `props`, `patcher`, `packer`).
- **Configuration Driven**: Uses JSON configuration files (`devices/common/port_config.json`) for device-specific settings.
- **Cross-Platform Tooling**: Includes a `ToolManager` to handle binary tools across Linux/Windows/macOS (currently focused on Linux x86_64).
- **Automated Patching**:
    - `PropertyModifier`: Automatically syncs properties between Base and Port ROMs.
    - `SmaliPatcher`: Decompiles and patches `services.jar` and `framework.jar` for signature verification and other fixes.
- **Advanced Repacking**: Supports packing partitions as EROFS or EXT4, and generating `super.img` (including Virtual A/B support).

## Hierarchical Configuration System

The project uses a powerful three-layer inheritance system for ROM modifications, allowing for easy expansion and multi-device support without duplicate logic.

### Inheritance Layers

Modifications are loaded and merged in the following order (lower layers override higher ones):

1.  **Common Layer (`devices/common/`)**: Global patches and features applied to all devices (e.g., standard GMS unlock, universal debloating).
2.  **Chipset Layer (`devices/chipset/<FAMILY>/`)**: Chipset-specific modifications (e.g., `OPSM8250` for Snapdragon 865, `OPSM8350` for 888). Identifies via `ro.build.device_family`.
3.  **Target Layer (`devices/target/<DEVICE>/`)**: Specific hardware patches for a single device model (e.g., `ONEPLUS9PRO`, `OP4E7L1`). Identifies via `ro.product.device` (Project ID).

> **Note**: Directory names for Chipset and Target layers must be in **ALL CAPS**.

### Configuration Files

-   **`features.json`**: Controls system features (oplus-features, app-features), build.prop modifications, and feature removals.
    -   `oplus_feature`: Adds entries to `com.oplus.oplus-feature-ext.xml`.
    -   `app_feature`: Adds entries to `com.oplus.app-features-ext.xml`.
    -   `build_props`: Key-value pairs to be injected into specific partition's `build.prop`.
    -   `features_remove`: List of features to be stripped from the Port ROM.
-   **`replacements.json`**: Handles file system operations.
    -   `type: "unzip_override"`: Extracts a ZIP over the ROM with optional conditional logic and file removals.
        - `condition_android_version`: Executes rules only for specific Base Android versions (e.g., `13`, `14`).
        - `condition_port_android_version`: Executes rules for specific Port ROM Android versions (e.g., `15`, `16`).
        - `condition_base_android_version_lt`: Executes if Base Android version is less than X.
        - `condition_port_is_coloros`, `condition_port_is_oos`, `condition_port_is_coloros_global`: Boolean flags to target specific ROM types.
        - `condition_regionmark`: Matches `ro.vendor.oplus.regionmark` (e.g., `"CN"`).
        - `condition_file_exists`: Executes only if the specified local file (relative to project root) exists.
    -   **Wildcard Support**: `removes` and `files` arrays support standard glob patterns (e.g., `my_product/overlay/aon*.apk`).
    
    ## Usage
    
    ```bash
# Basic usage (auto-detects device code from filename)
python3 main.py --baserom <path_to_base_rom.zip> --portrom <path_to_port_rom.zip>

# Specify device code manually
python3 main.py --baserom <base.zip> --portrom <port.zip> --device_code <CODE>
```

## Directory Structure

- `src/core/`: Core logic (Context, ROM extraction, patching, packing).
- `src/utils/`: Utility functions (Shell execution).
- `devices/`: Device-specific configurations (JSON).
- `bin/`: External binary tools (`payload-dumper`, `apktool`, `mkfs.erofs`, `lpmake`, etc.).

## Requirements

- Python 3.10+
- Linux environment (recommended)
- `java` (for apktool)
- Standard build tools (`zip`, `unzip`, `7z`)

## License

MIT
