#!/usr/bin/env python3
"""
main_s23.py — ColorOS Port para Galaxy S23 (dm1q/dm2q/dm3q)
============================================================
Script principal adaptado do toraidl/ColorOS-Port-Python para
dispositivos Samsung Galaxy S23 series com Snapdragon 8 Gen 2.

FIX: Usa lpmake diretamente para criar super.img, evitando o
ota_from_target_files que falhava com exit code 1.
"""

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG DO DISPOSITIVO
# ──────────────────────────────────────────────────────────────────────────────

DEVICE_CONFIG = {
    "dm1q": {
        "model":         "SM-S911B",
        "brand":         "samsung",
        "manufacturer":  "Samsung",
        "market_name":   "Galaxy S23",
        "chipset":       "SM8550",
        "super_size":    9663676416,   # 9.0 GiB
        "lcd_density":   "420",
        "codenames":     ["dm1q", "SM-S911B", "SM-S911U", "SM-S911U1"],
    },
    "dm2q": {
        "model":         "SM-S916B",
        "brand":         "samsung",
        "manufacturer":  "Samsung",
        "market_name":   "Galaxy S23+",
        "chipset":       "SM8550",
        "super_size":    9663676416,
        "lcd_density":   "390",
        "codenames":     ["dm2q", "SM-S916B", "SM-S916U"],
    },
    "dm3q": {
        "model":         "SM-S918B",
        "brand":         "samsung",
        "manufacturer":  "Samsung",
        "market_name":   "Galaxy S23 Ultra",
        "chipset":       "SM8550",
        "super_size":    9663676416,
        "lcd_density":   "500",
        "codenames":     ["dm3q", "SM-S918B", "SM-S918U"],
    },
}

# Partições oplus que não existem no Samsung — precisam de stubs
OPLUS_STUB_PARTITIONS = [
    "my_product", "my_manifest", "my_engineering", "my_company",
    "my_carrier", "my_region", "my_heytap", "my_stock",
    "my_preload", "my_bigball",
]

# Partições reais da base rom (Samsung AOSP)
REAL_PARTITIONS = [
    "system", "system_ext", "vendor", "product", "odm",
    "vendor_dlkm", "odm_dlkm", "system_dlkm",
]

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────────────

def setup_logging(debug: bool = False) -> logging.Logger:
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S")
    return logging.getLogger("s23-port")


# ──────────────────────────────────────────────────────────────────────────────
# UTILITÁRIOS
# ──────────────────────────────────────────────────────────────────────────────

def run_cmd(cmd: list, logger: logging.Logger, check: bool = True,
            stream: bool = False) -> subprocess.CompletedProcess:
    logger.debug(f"CMD: {' '.join(str(c) for c in cmd)}")
    if stream:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        last_line = ""
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                logger.debug(line)
                last_line = line
        proc.wait()
        if proc.returncode != 0 and check:
            logger.error(f"Falhou (código {proc.returncode}): {' '.join(str(c) for c in cmd)}")
            raise subprocess.CalledProcessError(proc.returncode, cmd, last_line)
        return subprocess.CompletedProcess(cmd, proc.returncode)
    else:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            logger.debug(result.stdout[:500] if len(result.stdout) > 500 else result.stdout)
        if result.returncode != 0:
            if check:
                logger.error(f"Falhou: {' '.join(str(c) for c in cmd)}")
                logger.error(result.stderr[:500] if len(result.stderr) > 500 else result.stderr)
                raise subprocess.CalledProcessError(result.returncode, cmd, result.stderr)
            else:
                logger.warning(f"Aviso: {result.stderr[:200]}")
        return result


def read_prop(path: Path, key: str, fallback: str = "") -> str:
    """Lê uma propriedade de um arquivo build.prop."""
    if not path.exists():
        return fallback
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return fallback


def batch_update_props(prop_file: Path, updates: dict) -> int:
    """Atualiza múltiplas propriedades de uma vez."""
    if not prop_file.exists():
        return 0
    content = prop_file.read_text(encoding="utf-8", errors="ignore")
    count = 0
    for key, value in updates.items():
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        if pattern.search(content):
            content = pattern.sub(f"{key}={value}", content)
            count += 1
        else:
            content = content.rstrip() + f"\n{key}={value}\n"
            count += 1
    prop_file.write_text(content, encoding="utf-8")
    return count


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 1: EXTRAÇÃO
# ──────────────────────────────────────────────────────────────────────────────

class SamsungStockExtractor:
    def __init__(self, build_dir: Path, logger: logging.Logger):
        self.build_dir = build_dir
        self.logger = logger
        self._bin = Path("bin/linux/x86_64")

    def _tool(self, name: str) -> str:
        local = self._bin / name
        if local.exists():
            local.chmod(0o755)
            return str(local)
        sys_path = shutil.which(name)
        if sys_path:
            return sys_path
        raise FileNotFoundError(f"'{name}' não encontrado.")

    def detect_input_type(self, path: Path) -> str:
        if path.is_dir():
            has_parts = any((path / p).exists() for p in ["system", "vendor", "product"])
            if has_parts:
                return "part_dir"
            return "unknown_dir"
        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {path}")
        name = path.name.lower()
        if name.endswith(".zip"):
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
            has_payload = "payload.bin" in names
            if has_payload:
                return "payload_zip"
            if any("super.img" in n for n in names):
                return "super_zip"
            return "unknown_zip"
        if name.endswith("super.img.lz4"):
            return "super_lz4"
        if name == "super.img":
            return "super_img"
        return "unknown"

    def _extract_payload(self, payload_path: Path, imgs_dir: Path):
        imgs_dir.mkdir(exist_ok=True)
        for tool in ["payload-dumper-go"]:
            if shutil.which(tool):
                self.logger.info(f"  Usando {tool}...")
                run_cmd([tool, "-o", str(imgs_dir), str(payload_path)],
                        self.logger, stream=True)
                return
        raise RuntimeError("payload-dumper-go não encontrado!")

    def _extract_ext4(self, img: Path, dest: Path) -> bool:
        self.logger.info(f"  ext4: {img.name} → {dest.name}/")
        dest.mkdir(parents=True, exist_ok=True)
        debugfs = shutil.which("debugfs")
        if not debugfs:
            self.logger.error("  debugfs não encontrado! sudo apt install e2fsprogs")
            return False
        import threading
        proc = subprocess.Popen([debugfs, str(img)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout_buf, stderr_buf = [], []
        def drain(pipe, buf):
            try:
                for line in pipe:
                    buf.append(line)
            except Exception:
                pass
        t1 = threading.Thread(target=drain, args=(proc.stdout, stdout_buf), daemon=True)
        t2 = threading.Thread(target=drain, args=(proc.stderr, stderr_buf), daemon=True)
        t1.start(); t2.start()
        proc.stdin.write(f'rdump / "{dest.resolve()}"\n'.encode())
        proc.stdin.close()
        t1.join(); t2.join()
        proc.wait()
        try:
            extracted = [f for f in dest.iterdir() if f.name not in ("lost+found",)]
        except Exception:
            extracted = []
        return len(extracted) > 0

    def _extract_erofs(self, img: Path, dest: Path) -> bool:
        self.logger.info(f"  EROFS: {img.name} → {dest.name}/")
        fsck = shutil.which("fsck.erofs")
        if fsck:
            result = subprocess.run([fsck, f"--extract={dest}", str(img)],
                                    capture_output=True, text=True)
            if result.returncode == 0:
                return True
        self.logger.warning(f"  EROFS: instale erofs-utils")
        return False

    def extract_partition_img(self, img_path: Path, dest_dir: Path) -> bool:
        if dest_dir.exists() and any(dest_dir.iterdir()):
            self.logger.debug(f"  {dest_dir.name}/ já extraído.")
            return True
        dest_dir.mkdir(parents=True, exist_ok=True)
        file_out = subprocess.run(["file", str(img_path)], capture_output=True, text=True).stdout.lower()
        if "erofs" in file_out:
            return self._extract_erofs(img_path, dest_dir)
        return self._extract_ext4(img_path, dest_dir)

    def prepare_base_stock(self, base_input: Path) -> Path:
        self.logger.info("\n[STAGE 1a] Preparando Base ROM (Stock Samsung)...")
        work = self.build_dir / "base_work"
        imgs_dir = self.build_dir / "base_imgs"
        base_dir = self.build_dir / "base"

        input_type = self.detect_input_type(base_input)
        self.logger.info(f"  Tipo detectado: {input_type}")

        if input_type == "part_dir":
            return base_input

        if input_type == "payload_zip":
            self.logger.info("  ROM AOSP detectada (payload.bin)...")
            work.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(base_input, "r") as zf:
                payload_path = work / "payload.bin"
                if not payload_path.exists():
                    self.logger.info("  Extraindo payload.bin...")
                    with zf.open("payload.bin") as src, open(payload_path, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=16 * 1024 * 1024)
            self._extract_payload(payload_path, imgs_dir)
        else:
            raise ValueError(f"Formato não suportado: {input_type}")

        base_dir.mkdir(parents=True, exist_ok=True)
        for part in REAL_PARTITIONS:
            img = imgs_dir / f"{part}.img"
            if img.exists():
                dest = base_dir / part
                self.extract_partition_img(img, dest)

        found = [p.name for p in base_dir.iterdir() if p.is_dir()]
        self.logger.info(f"  Base pronta: {found}")
        return base_dir

    def prepare_port(self, port_input: Path) -> Path:
        self.logger.info("\n[STAGE 1b] Preparando Port ROM (ColorOS)...")
        work = self.build_dir / "port_work"
        imgs_dir = self.build_dir / "port_imgs"
        port_dir = self.build_dir / "port"

        input_type = self.detect_input_type(port_input)
        self.logger.info(f"  Tipo: {input_type}")

        if input_type == "part_dir":
            return port_input

        work.mkdir(parents=True, exist_ok=True)

        if input_type == "payload_zip":
            with zipfile.ZipFile(port_input, "r") as zf:
                payload_path = work / "payload.bin"
                if not payload_path.exists():
                    with zf.open("payload.bin") as src, open(payload_path, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=16 * 1024 * 1024)
            self._extract_payload(payload_path, imgs_dir)

        port_dir.mkdir(parents=True, exist_ok=True)
        all_parts = REAL_PARTITIONS + OPLUS_STUB_PARTITIONS
        for part in all_parts:
            img = imgs_dir / f"{part}.img"
            if img.exists():
                dest = port_dir / part
                self.extract_partition_img(img, dest)

        found = [p.name for p in port_dir.iterdir() if p.is_dir()]
        self.logger.info(f"  Port pronto: {found}")
        return port_dir


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 2: MERGE
# ──────────────────────────────────────────────────────────────────────────────

class RomMerger:
    def __init__(self, base_dir: Path, port_dir: Path, target_dir: Path,
                 device_cfg: dict, logger: logging.Logger):
        self.base_dir = base_dir
        self.port_dir = port_dir
        self.target_dir = target_dir
        self.device_cfg = device_cfg
        self.logger = logger

    def merge(self) -> Path:
        self.logger.info("\n[STAGE 2] Merge das partições...")
        self.target_dir.mkdir(parents=True, exist_ok=True)

        for part in REAL_PARTITIONS:
            src = self.base_dir / part
            if src.exists():
                self.logger.info(f"  Copiando {part} da base...")
                shutil.copytree(src, self.target_dir / part, symlinks=True)

        for part in OPLUS_STUB_PARTITIONS:
            src = self.port_dir / part
            if src.exists():
                self.logger.info(f"  Copiando {part} do port...")
                shutil.copytree(src, self.target_dir / part, symlinks=True)

        return self.target_dir


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 3: PATCHES
# ──────────────────────────────────────────────────────────────────────────────

class S23Patcher:
    def __init__(self, target_dir: Path, device_cfg: dict, logger: logging.Logger):
        self.target_dir = target_dir
        self.cfg = device_cfg
        self.logger = logger

    def create_oplus_stubs(self) -> bool:
        self.logger.info("  [3.1] Criando stubs de partições oplus...")
        config_dir = self.target_dir.parent / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        for part in OPLUS_STUB_PARTITIONS:
            part_dir = self.target_dir / part
            if part_dir.exists() and (part_dir / "build.prop").exists():
                continue
            self.logger.info(f"    Stub: {part}")
            part_dir.mkdir(parents=True, exist_ok=True)
            (part_dir / "etc").mkdir(exist_ok=True)
            stub_content = "\n".join([
                f"# {part} stub",
                f"ro.product.{part}.brand={self.cfg['brand']}",
                f"ro.product.{part}.device={self.cfg.get('codenames', ['dm1q'])[0]}",
                f"ro.product.{part}.model={self.cfg['model']}",
                "",
            ])
            (part_dir / "build.prop").write_text(stub_content, encoding="utf-8")
        return True

    def patch_build_props(self) -> bool:
        self.logger.info("  [3.2] Corrigindo propriedades do S23...")
        device_code = self.cfg.get("codenames", ["dm1q"])[0]
        brand = self.cfg["brand"]
        manufacturer = self.cfg["manufacturer"]
        density = self.cfg["lcd_density"]

        s23_props = {
            "ro.product.brand": brand,
            "ro.product.manufacturer": manufacturer,
            "ro.product.device": device_code,
            "ro.product.model": self.cfg["model"],
            "ro.product.name": device_code,
            "ro.build.product": device_code,
            "ro.sf.lcd_density": density,
            "ro.secure": "1",
            "ro.debuggable": "0",
        }

        for part in ["system", "product", "system_ext", "vendor"]:
            part_dir = self.target_dir / part
            if not part_dir.exists():
                continue
            bp = part_dir / "build.prop"
            if bp.exists():
                batch_update_props(bp, s23_props)
                self.logger.debug(f"    Atualizado: {part}/build.prop")
        return True

    def regenerate_fingerprint(self) -> bool:
        self.logger.info("  [3.3] Regenerando fingerprint...")
        device_code = self.cfg.get("codenames", ["dm1q"])[0]
        brand = self.cfg["brand"]

        fingerprint = f"{brand}/{device_code}/{device_code}:15/AP3A.240905.015/S911BXXU7EXJ1:user/release-keys"

        fp_props = {
            "ro.build.fingerprint": fingerprint,
            "ro.bootimage.build.fingerprint": fingerprint,
            "ro.system.build.fingerprint": fingerprint,
            "ro.vendor.build.fingerprint": fingerprint,
            "ro.build.description": f"{device_code}-user 15 AP3A.240905.015 S911BXXU7EXJ1 release-keys",
        }

        for bp in self.target_dir.rglob("build.prop"):
            batch_update_props(bp, fp_props)
        return True

    def run_all(self) -> bool:
        self.logger.info("\n[STAGE 3] Aplicando patches S23...")
        ok = True
        ok &= self.create_oplus_stubs()
        ok &= self.patch_build_props()
        ok &= self.regenerate_fingerprint()
        return ok


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 4: EMPACOTAMENTO (FIXED - usa lpmake diretamente)
# ──────────────────────────────────────────────────────────────────────────────

class RomPacker:
    def __init__(self, target_dir: Path, output_dir: Path,
                 device_cfg: dict, logger: logging.Logger):
        self.target_dir = target_dir
        self.output_dir = output_dir
        self.cfg = device_cfg
        self.logger = logger
        self.bin_dir = Path("bin/linux/x86_64")

    def _get_tool(self, name: str) -> str:
        local = self.bin_dir / name
        if local.exists():
            return str(local)
        system = shutil.which(name)
        if system:
            return system
        raise FileNotFoundError(f"Ferramenta não encontrada: {name}")

    def pack_partition_erofs(self, part_name: str, part_dir: Path) -> Optional[Path]:
        output_img = self.output_dir / f"{part_name}.img"
        if output_img.exists() and output_img.stat().st_size > 0:
            self.logger.info(f"  EROFS: {part_name}.img já existe")
            return output_img

        if not part_dir.exists():
            self.logger.warning(f"  Skip {part_name}: diretório não existe")
            return None
        try:
            next(part_dir.iterdir())
        except StopIteration:
            self.logger.warning(f"  Skip {part_name}: diretório vazio")
            return None

        try:
            mkfs_erofs = self._get_tool("mkfs.erofs")
        except FileNotFoundError:
            self.logger.error("  mkfs.erofs não encontrado!")
            return None

        # Sem fs-config-file para evitar problemas
        cmd = [mkfs_erofs, str(output_img), str(part_dir)]
        try:
            run_cmd(cmd, self.logger)
            if output_img.stat().st_size == 0:
                self.logger.error(f"  mkfs.erofs gerou imagem vazia!")
                output_img.unlink(missing_ok=True)
                return None
            self.logger.info(f"  EROFS: {part_name}.img ({output_img.stat().st_size // 1024 // 1024} MB)")
            return output_img
        except subprocess.CalledProcessError as e:
            self.logger.error(f"  Falha EROFS {part_name}: {e}")
            output_img.unlink(missing_ok=True)
            return None

    def pack_super(self, partition_imgs: list) -> Optional[Path]:
        super_img = self.output_dir / "super.img"
        super_size = self.cfg["super_size"]

        try:
            lpmake = self._get_tool("lpmake")
        except FileNotFoundError:
            self.logger.error("lpmake não encontrado!")
            return None

        # Filtra imagens vazias
        valid_imgs = [img for img in partition_imgs if img and img.stat().st_size > 0]
        if not valid_imgs:
            self.logger.error("Nenhuma imagem válida!")
            return None

        total = sum(img.stat().st_size for img in valid_imgs)
        self.logger.info(f"  Partições válidas: {len(valid_imgs)} | Total: {total // 1024 // 1024} MB / {super_size // 1024 // 1024} MB")

        if total > super_size:
            self.logger.error(f"ERRO: {total // 1024 // 1024} MB excede super size!")
            return None

        group_a = "qti_dynamic_partitions_a"
        group_b = "qti_dynamic_partitions_b"

        cmd = [
            lpmake,
            "--metadata-size", "65536",
            "--super-name", "super",
            "--metadata-slots", "2",
            "--device", f"super:{super_size}",
            "--group", f"{group_a}:{super_size}",
            "--group", f"{group_b}:0",
        ]

        for img in valid_imgs:
            part_name = img.stem
            aligned_size = ((img.stat().st_size + 511) // 512) * 512
            cmd += [
                "--partition", f"{part_name}_a:{aligned_size}:{group_a}",
                "--image", f"{part_name}_a={img}",
                "--partition", f"{part_name}_b:0:{group_b}",
            ]

        cmd += ["--sparse", "--output", str(super_img)]

        try:
            run_cmd(cmd, self.logger)
            self.logger.info(f"  super.img gerado: {super_img.stat().st_size // 1024 // 1024} MB")
            return super_img
        except subprocess.CalledProcessError as e:
            self.logger.error(f"  lpmake falhou: {e}")
            return None

    def create_flashable_zip(self, super_img: Path) -> Path:
        output_zip = self.output_dir / f"ColorOS_Port_S23_{self.cfg['model']}.zip"
        self.logger.info(f"  Criando zip flashável: {output_zip.name}")

        updater_script = f'''#!/sbin/sh
# ColorOS Port para Galaxy S23
# Flash via TWRP

ui_print("ColorOS Port - Galaxy S23 Series")
ui_print("Instalando...")

DEVICE=$(getprop ro.product.device)
if [ "$DEVICE" != "dm1q" ] && [ "$DEVICE" != "dm2q" ] && [ "$DEVICE" != "dm3q" ]; then
    ui_print("ERRO: Dispositivo incompativel: $DEVICE")
    exit 1
fi

ui_print("Dispositivo: $DEVICE")
ui_print("Instalando super.img...")
dd if=super.img of=/dev/block/bootdevice/by-name/super bs=4096

ui_print("Instalação concluída!")
ui_print("Reiniciando...")
'''

        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(super_img, "super.img")
            zf.writestr("META-INF/com/google/android/update-binary", updater_script)
            zf.writestr("META-INF/com/google/android/updater-script", "")

        self.logger.info(f"  ZIP criado: {output_zip.stat().st_size // 1024 // 1024} MB")
        return output_zip

    def pack(self) -> bool:
        self.logger.info("\n[STAGE 4] Empacotando ROM...")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        imgs = []
        all_parts = REAL_PARTITIONS + OPLUS_STUB_PARTITIONS
        for part in all_parts:
            part_dir = self.target_dir / part
            if not part_dir.exists():
                continue
            img = self.pack_partition_erofs(part, part_dir)
            if img:
                imgs.append(img)

        if not imgs:
            self.logger.error("Nenhuma partição empacotada!")
            return False

        super_img = self.pack_super(imgs)
        if super_img:
            self.create_flashable_zip(super_img)
            return True
        return False


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ColorOS Port para Galaxy S23")
    parser.add_argument("--baserom", required=True, help="Base ROM (payload.bin zip)")
    parser.add_argument("--portrom", required=True, help="Port ROM (ColorOS zip)")
    parser.add_argument("--device", default="dm1q", choices=list(DEVICE_CONFIG.keys()))
    parser.add_argument("--output", default="./build_s23", help="Diretório de output")
    parser.add_argument("--clean", action="store_true", help="Limpa build anterior")
    parser.add_argument("--debug", action="store_true", help="Log verboso")
    return parser.parse_args()


def main():
    args = parse_args()
    logger = setup_logging(args.debug)

    logger.info("=" * 60)
    logger.info("  ColorOS Port — Samsung Galaxy S23 Series")
    logger.info("=" * 60)

    device_cfg = DEVICE_CONFIG[args.device]
    logger.info(f"  Dispositivo: {device_cfg['market_name']} ({args.device})")
    logger.info(f"  Modelo:      {device_cfg['model']}")

    build_dir = Path(args.output)
    if args.clean and build_dir.exists():
        logger.info(f"\nLimpando build anterior: {build_dir}")
        shutil.rmtree(build_dir)

    base_input = Path(args.baserom)
    port_input = Path(args.portrom)

    for p, label in [(base_input, "Base ROM"), (port_input, "Port ROM")]:
        if not p.exists():
            logger.error(f"{label} não encontrado: {p}")
            sys.exit(1)

    # Stage 1: Extração
    extractor = SamsungStockExtractor(build_dir, logger)
    base_dir = extractor.prepare_base_stock(base_input)
    port_dir = extractor.prepare_port(port_input)

    # Stage 2: Merge
    target_dir = build_dir / "target"
    merger = RomMerger(base_dir, port_dir, target_dir, device_cfg, logger)
    merger.merge()

    # Stage 3: Patches
    patcher = S23Patcher(target_dir, device_cfg, logger)
    patcher.run_all()

    # Stage 4: Empacotamento
    output_dir = build_dir / "output"
    packer = RomPacker(target_dir, output_dir, device_cfg, logger)
    if packer.pack():
        logger.info("\n" + "=" * 60)
        logger.info("  PORT CONCLUÍDO!")
        logger.info(f"  Output: {output_dir}")
        logger.info("=" * 60)
    else:
        logger.error("Falha no empacotamento!")
        sys.exit(1)


if __name__ == "__main__":
    main()
