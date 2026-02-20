<div align="center">

# ColorOS 移植工具 (Python版)

一个基于 Python 的 ColorOS 移植工具，由 Gemini CLI 制作。

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

## ✨ 特性

- **上下文感知架构**: 使用 `Context` 对象管理整个移植生命周期。
- **模块化设计**: 将不同功能分离到独立的模块中 (`rom`, `props`, `patcher`, `packer`)。
- **配置驱动**: 使用 JSON 配置文件进行设备特定的设置。
- **自动化修补**:
    - `PropertyModifier`: 自动同步底包和移植包之间的属性。
    - `SmaliPatcher`: 反编译并修补 `services.jar` 和 `framework.jar`。
- **高级打包**: 支持将分区打包为 EROFS 或 EXT4，并生成 `super.img` 或 OTA `payload.bin`。

## 🚀 开始使用

本节将指导你如何设置并运行此工具。

### 先决条件

- **操作系统**: Linux 发行版 (如 Ubuntu, Arch)，x86_64 架构。
- **Python**: Python 3.10 或更高版本。
- **Java**: Java Development Kit (JDK) 11 或更高版本。
- **Docker**: (推荐) 用于无痛安装。

### 方案一: 使用 Docker 部署 (推荐)

我们推荐使用 Docker 来运行此工具。它会创建一个包含所有必需依赖项的自给自足的环境。

1.  **构建 Docker 镜像:**
    ```bash
    docker build -t coloros-port .
    ```

2.  **运行容器:**
    通过挂载本地文件夹，使容器可以访问你的 ROM 文件并将输出写回你的电脑。
    ```bash
    # 示例:
    docker run --rm -it 
      -v /path/to/your/roms:/roms 
      -v $(pwd)/build:/app/build 
      coloros-port 
      python3 main.py --baserom /roms/base_rom.zip --portrom /roms/port_rom.zip
    ```
    - **请记得将 `/path/to/your/roms` 替换为你电脑上的实际路径。**
    - 输出文件将位于你主机的 `build` 目录中。

### 方案二: 手动设置

1.  **克隆仓库:**
    ```bash
    git clone https://github.com/toraidl/ColorOS-Port-Python.git
    cd ColorOS-Port-Python
    ```

2.  **设置文件权限:**
    ```bash
    chmod +x -R bin/linux/x86_64/
    ```
    
3.  **运行脚本:**
    - **基本用法:**
        ```bash
        python3 main.py --baserom <path/to/base.zip> --portrom <path/to/port.zip>
        ```
    - **高级用法 (带参数):**
        ```bash
        # 指定设备代号, 打包类型, 并启用调试日志
        python3 main.py 
          --baserom <path/to/base.zip> 
          --portrom <path/to/port.zip> 
          --device_code OP4E7L1 
          --pack_type super 
          --debug
        ```
    - 默认情况下，输出文件将位于 `build` 目录中。

## 🛠️ 分层配置系统

该项目使用强大的三层继承系统进行 ROM 修改，从而轻松实现扩展和多设备支持，无需重复逻辑。修改按以下顺序加载和合并：

1.  **通用层 (`devices/common/`)**: 适用于所有设备的全局补丁。
2.  **芯片组层 (`devices/chipset/<FAMILY>/`)**: 特定于芯片组的修改。
3.  **目标层 (`devices/target/<DEVICE>/`)**: 特定于设备的硬件补丁。

> 更多示例，如 `features.json` 和 `replacements.json`，请参阅 `devices` 目录。

## ⚠️ 免责声明

本项目中包含的二进制工具仅适用于 **Linux x86_64** 架构。作者对你的设备可能发生的任何损坏概不负责。

## 📄 许可证

本项目基于 MIT 许可证授权。
