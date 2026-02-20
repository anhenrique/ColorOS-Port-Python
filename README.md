<div align="center">

# ColorOS Port Python

A Python-based porting tool for ColorOS, created by Gemini CLI.

</div>

<p align="center">
  <a href="./README.md">English</a> | <a href="./README_zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/github/stars/toraidl/ColorOS-Port-Python?style=flat&logo=github" alt="Stars">
  <img src="https://img.shields.io/github/forks/toraidl/ColorOS-Port-Python?style=flat&logo=github" alt="Forks">
  <img src="https://img.shields.io/github/issues/toraidl/ColorOS-Port-Python" alt="Issues">
  <img src="https://img.shields.io/github/license/toraidl/ColorOS-Port-Python" alt="License">
</p>

## ✨ Features

- **Context-Aware Architecture**: Uses a `Context` object to manage the entire porting lifecycle.
- **Modular Design**: Separates concerns into distinct modules (`rom`, `props`, `patcher`, `packer`).
- **Configuration Driven**: Uses JSON configuration files for device-specific settings.
- **Automated Patching**:
    - `PropertyModifier`: Automatically syncs properties between Base and Port ROMs.
    - `SmaliPatcher`: Decompiles and patches `services.jar` and `framework.jar`.
- **Advanced Repacking**: Supports packing partitions as EROFS or EXT4, and generating `super.img` or OTA `payload.bin`.

## 📱 Supported Devices

This tool is designed to theoretically support Qualcomm Snapdragon chips beyond **SM8250**.

**Currently Expected Supported Models:**
-   **OnePlus SM8250 Series**: OnePlus 8, OnePlus 8 Pro, OnePlus 8T
-   **Oppo Find X3** (SM8350)
-   **OnePlus SM8350 Series**: OnePlus 9, OnePlus 9 Pro

**Important Note for ColorOS 16:**
ColorOS 16 requires specific kernel support. Please ensure your device's kernel is compatible if attempting to port ColorOS 16.


## 🚀 Getting Started

This section will guide you on how to set up and run the tool.

### Prerequisites

- **Operating System**: A Linux distribution (e.g., Ubuntu, Arch) on an x86_64 architecture.
- **Python**: Python 3.10 or newer.
- **Java**: Java Development Kit (JDK) 11 or newer.
- **Docker**: (Recommended) For a hassle-free setup.

### Option 1: Deploying with Docker (Recommended)

Using Docker is the recommended way to run this tool. It creates a self-contained environment with all the necessary dependencies pre-installed.

1.  **Build the Docker image:**
    ```bash
    docker build -t coloros-port .
    ```

2.  **Run the container:**
    Mount your local folders into the container so the script can access your ROMs and write the output back to your machine.
    ```bash
    # Example:
    docker run --rm -it \
      -v /path/to/your/roms:/roms \
      -v $(pwd)/build:/app/build \
      coloros-port \
      python3 main.py --baserom /roms/base_rom.zip --portrom /roms/port_rom.zip
    ```
    - **Remember to replace `/path/to/your/roms` with the actual path on your computer.**
    - The output will be in the `build` directory on your host machine.

### Option 2: Manual Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/toraidl/ColorOS-Port-Python.git
    cd ColorOS-Port-Python
    ```

2.  **Set file permissions:**
    ```bash
    chmod +x -R bin/linux/x86_64/
    ```
    
3.  **Run the script:**
    - **Basic Usage:**
        ```bash
        python3 main.py --baserom <path/to/base.zip> --portrom <path/to/port.zip>
        ```
    - **Advanced Usage (with arguments):**
        ```bash
        # Specify device code, pack type, and enable debug logging
        python3 main.py \
          --baserom <path/to/base.zip> \
          --portrom <path/to/port.zip> \
          --device_code OP4E7L1 \
          --pack_type super \
          --debug
        ```
    - The output will be in the `build` directory by default.

## 🛠️ Hierarchical Configuration System

The project uses a powerful three-layer inheritance system for ROM modifications, allowing for easy expansion and multi-device support without duplicate logic. Modifications are loaded and merged in the following order:

1.  **Common Layer (`devices/common/`)**: Global patches for all devices.
2.  **Chipset Layer (`devices/chipset/<FAMILY>/`)**: Chipset-specific modifications.
3.  **Target Layer (`devices/target/<DEVICE>/`)**: Device-specific hardware patches.

> See the `devices` directory for examples like `features.json` and `replacements.json`.

## ⚠️ Disclaimer

The binary tools included in this project are for the **Linux x86_64** architecture only. The author is not responsible for any damage to your device.

## 📄 License

This project is licensed under the MIT License.
