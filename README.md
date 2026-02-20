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
    
    ## ⚠️ Disclaimer
    
    The binary tools included in this project (`bin/linux/x86_64`) are compiled exclusively for the **Linux x86_64** architecture. This tool will **not** work on Windows, macOS, or ARM-based Linux systems.
    
    ## Requirements
    
    - **Operating System**: A Linux distribution (e.g., Ubuntu, Arch) on an x86_64 architecture.
    - **Python**: Python 3.10 or newer.
    - **Java**: Java Development Kit (JDK) 11 or newer.
        - You can verify your Java version with `java --version`.
    - **General Tools**: `git` for cloning the repository.
    
    ## Setup
    
    1.  **Clone the repository:**
        *(You will need to replace `your-username` with the actual repository owner's username)*
        ```bash
        git clone https://github.com/your-username/ColorOS-Port-Python.git
        cd ColorOS-Port-Python
        ```
    
    2.  **Set file permissions:**
        The project relies on external tools that need to be executable. Run the following command to grant the necessary permissions:
        ```bash
        chmod +x -R bin/linux/x86_64/
        ```
    
    3.  **Python Dependencies:**
        This project has no external Python dependencies, so you don't need to `pip install` anything.
    
    ## Deploying with Docker (Recommended)
    
    Using Docker is the recommended way to run this tool. It creates a self-contained environment with all the necessary dependencies (Python, Java, etc.) pre-installed, avoiding any setup issues on your host machine.
    
    1.  **Build the Docker image:**
        From the project's root directory, run the following command. This will create a Docker image named `coloros-port`.
        ```bash
        docker build -t coloros-port .
        ```
    
    2.  **Run the container:**
        The key is to "mount" your local folders into the container so the script can access your ROMs and write the output back to your machine.
    
        **Example:**
        Let's say your ROMs are in `/home/user/roms` on your computer.
        ```bash
        docker run --rm -it \
          -v /home/user/roms:/roms \
          -v $(pwd)/build:/app/build \
          coloros-port \
          python3 main.py --baserom /roms/base_rom.zip --portrom /roms/port_rom.zip
        ```
    
        **Understanding the command:**
        - `docker run --rm -it`: Runs a container. `--rm` cleans it up after exit, and `-it` makes it interactive.
        - `-v /home/user/roms:/roms`: Mounts your local ROMs directory to the `/roms` directory inside the container. **Remember to replace `/home/user/roms` with the actual path on your computer.**
        - `-v $(pwd)/build:/app/build`: Mounts the project's `build` directory on your host to the `/app/build` directory inside the container. This ensures that the output files are written directly to your host machine.
        - `coloros-port`: The name of the image to run.
        - `python3 main.py ...`: The command to execute inside the container. Note that the file paths (`/roms/base_rom.zip`) are relative to the *inside* of the container.    
    ## Usage
    
    1.  **Prepare your ROMs:**
        Place your Base ROM zip file and Port ROM zip file in a convenient location.
    
    2.  **Run the script:**
        The main script is `main.py`. It requires the paths to the base and port ROMs.
    
        **Basic Usage:**
        The tool will attempt to auto-detect the device code from the ROM filename.
        ```bash
        python3 main.py --baserom <path/to/your/base_rom.zip> --portrom <path/to/your/port_rom.zip>
        ```
        *Example:*
        ```bash
        python3 main.py --baserom ~/roms/ColorOS_OP4E7L1_...zip --portrom ~/roms/OxygenOS_14_...zip
        ```
    
        **Advanced Usage:**
    
        *   **Specify Device Code Manually:** Override auto-detection if it fails or if you need to use a specific configuration.
            ```bash
            python3 main.py --baserom <base.zip> --portrom <port.zip> --device_code OP4E7L1
            ```
    
        *   **Specify Output Pack Type:** You can choose to pack the final ROM as a fastboot-flashable `super.img` or an OTA-style `payload.bin`.
            -   `--pack_type super` (for fastboot)
            -   `--pack_type payload` (default, for OTA)
            ```bash
            python3 main.py --baserom <base.zip> --portrom <port.zip> --pack_type super
            ```
    
        *   **Enable Debug Logging:** If you encounter issues, run with the `--debug` flag to get a detailed `port.log` in the `build/` directory.
            ```bash
            python3 main.py --baserom <base.zip> --portrom <port.zip> --debug
            ```
    
    3.  **Find the output:**
        All temporary files and final output files will be located in the `build/` directory by default. The final flashable file will be in `build/repack/`.
    
    ## Directory Structure
    
    - `src/core/`: Core logic (Context, ROM extraction, patching, packing).
    - `src/utils/`: Utility functions (Shell execution).
    - `devices/`: Device-specific configurations (JSON).
    - `bin/`: External binary tools (`payload-dumper`, `apktool`, `mkfs.erofs`, `lpmake`, etc.).
    ## License

MIT
