# ColorOS Port Python

A Python-based tool for porting ColorOS ROMs to various Android devices, built with AI assistance.

## Features

- **Modular Architecture**: Clean separation of concerns with ROM extraction, property modification, patching, and repacking modules
- **Configuration-Driven**: JSON-based configuration system for device-specific settings
- **Performance Optimized**: Caching, batch processing, and exclusion patterns for fast execution
- **Multi-Device Support**: Hierarchical configuration system supporting common, chipset, and device-specific layers
- **Advanced Patching**: Automated Smali patching for framework jars and services
- **Flexible Output**: Support for both super.img (Fastboot) and payload.bin (OTA) formats
- **Error Handling**: Comprehensive logging and graceful error recovery

## Supported Devices

Theoretically supports Qualcomm Snapdragon chips beyond SM8250. Currently tested with:

- OnePlus 8/8 Pro/8T (SM8250)
- Oppo Find X3 (SM8350)
- OnePlus 9/9 Pro (SM8350)

**Note**: ColorOS 16 requires kernel compatibility.

## Quick Start

### Prerequisites

- Linux x86_64 (Ubuntu, Arch, etc.)
- Python 3.10+
- JDK 11+
- Docker (recommended)

### Using Docker (Recommended)

```bash
# Build image
docker build -t coloros-port .

# Run container
docker run --rm -it \
  -v /path/to/roms:/roms \
  -v $(pwd)/build:/app/build \
  coloros-port \
  python3 main.py --baserom /roms/base.zip --portrom /roms/port.zip
```

### Manual Setup

```bash
# Clone repo
git clone https://github.com/toraidl/ColorOS-Port-Python.git
cd ColorOS-Port-Python

# Set permissions
chmod +x -R bin/linux/x86_64/

# Run
python3 main.py --baserom path/to/base.zip --portrom path/to/port.zip
```

## Usage

```bash
python3 main.py \
  --baserom <base_rom.zip> \
  --portrom <port_rom.zip> \
  [--device_code <device>] \
  [--pack_type super|payload] \
  [--debug] \
  [--clean]
```

## Configuration

The tool uses a three-layer configuration system:

1. **Common** (`devices/common/`): Global settings
2. **Chipset** (`devices/chipset/<chipset>/`): Chipset-specific configs
3. **Target** (`devices/target/<device>/`): Device-specific overrides

Key config files:
- `features.json`: Feature flags and build properties
- `replacements.json`: File replacement rules
- `port_config.json`: Port configuration
- `props.json`: Property modification rules

## Project Structure

```
├── bin/                    # Binary tools
├── build/                  # Working directory
├── devices/                # Configuration files
│   ├── common/            # Global configs
│   ├── chipset/           # Chipset-specific
│   └── target/            # Device-specific
├── otatools/              # OTA tools
├── src/                   # Source code
│   ├── core/              # Core modules
│   ├── handlers/          # File handlers
│   ├── modules/           # Extension modules
│   └── utils/             # Utilities
├── main.py                # Entry point
└── requirements.txt       # Dependencies
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## Disclaimer

The included binary tools are for Linux x86_64 only. Use at your own risk - the author is not responsible for any damage to your device.

## License

MIT License</content>
<parameter name="filePath">\\wsl.localhost\Ubuntu-24.04\home\guedessaurus\ColorOS-Port-Python\README_new.md