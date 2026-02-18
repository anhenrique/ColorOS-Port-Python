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
