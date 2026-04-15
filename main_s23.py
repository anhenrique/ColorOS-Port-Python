#!/usr/bin/env python3
"""
main_s23.py — ColorOS Port para Galaxy S23 (dm1q/dm2q/dm3q)
============================================================
Script principal adaptado do toraidl/ColorOS-Port-Python para
dispositivos Samsung Galaxy S23 series com Snapdragon 8 Gen 2.

Uso:
    python3 main_s23.py \
        --baserom /path/stock_samsung_s23.zip \
        --portrom /path/coloros_port.zip \
        --device dm1q \
        --output /path/output \
        --pack_type super

Compatibilidade:
    - Galaxy S23 (dm1q / SM-S911B/U/U1)
    - Galaxy S23+ (dm2q / SM-S916B/U/U1)
    - Galaxy S23 Ultra (dm3q / SM-S918B/U/U1)

Base ROM (Stock Samsung):
    Baixe de samfw.com ou sammobile.com.
    Formatos suportados:
      - ZIP contendo AP_*.tar.md5 + BL_*.tar.md5 + CP_*.tar.md5 + CSC_*.tar.md5
      - AP_*.tar.md5 diretamente
    O script extrai automaticamente:
      AP_.tar.md5 → super.img.lz4 → super.img (simg2img) → lpunpack → partições
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

# Partições reais da base rom (Evolution X / Samsung AOSP)
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

def run_cmd(cmd: list[str], logger: logging.Logger, check: bool = True,
            stream: bool = False) -> subprocess.CompletedProcess:
    logger.debug(f"CMD: {' '.join(str(c) for c in cmd)}")
    if stream:
        # Modo streaming: exibe progresso em tempo real (para processos longos)
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
            logger.debug(result.stdout)
        if result.returncode != 0:
            if check:
                logger.error(f"Falhou: {' '.join(str(c) for c in cmd)}")
                logger.error(result.stderr)
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


def find_build_prop(root: Path) -> list[Path]:
    """Encontra todos os build.prop, considerando paths aninhados (system/system/)."""
    found = []
    for bp in root.rglob("build.prop"):
        # Exclui os stubs que nós mesmos geramos
        if "stub" not in bp.read_text(encoding="utf-8", errors="ignore")[:50].lower():
            found.append(bp)
    return found


def update_prop(prop_file: Path, key: str, value: str) -> bool:
    """Atualiza ou adiciona uma propriedade em build.prop."""
    if not prop_file.exists():
        return False
    content = prop_file.read_text(encoding="utf-8", errors="ignore")
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(f"{key}={value}", content)
    else:
        content = content.rstrip() + f"\n{key}={value}\n"
    prop_file.write_text(content, encoding="utf-8")
    return True


def batch_update_props(prop_file: Path, updates: dict[str, str]) -> int:
    """Atualiza múltiplas propriedades de uma vez. Retorna quantas foram alteradas."""
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
    """
    Extrai o firmware stock Samsung (formato Odin).

    Pipeline para o AP_*.tar.md5:
        ZIP → AP_*.tar.md5 → tar → super.img.lz4 → lz4 -d → super.img
        → simg2img (unsparse) → super_raw.img → lpunpack → system.img, vendor.img, ...
        → mount/extract cada .img → pastas de partição

    O BL/CP/CSC não são necessários para o port (só precisamos das partições do AP).
    """

    def __init__(self, build_dir: Path, logger: logging.Logger):
        self.build_dir = build_dir
        self.logger = logger
        self._bin = Path("bin/linux/x86_64")

    def _tool(self, name: str) -> str:
        """Localiza uma ferramenta: primeiro em bin/, depois no PATH."""
        local = self._bin / name
        if local.exists():
            local.chmod(0o755)
            return str(local)
        sys_path = shutil.which(name)
        if sys_path:
            return sys_path
        raise FileNotFoundError(
            f"'{name}' não encontrado.\n"
            f"  Instale: sudo apt install {name}  ou coloque em {self._bin}/"
        )

    # ── Detecção do tipo de input ─────────────────────────────────────────────

    def detect_input_type(self, path: Path) -> str:
        """
        Detecta o que o usuário passou como --baserom:
          'odin_zip'   → ZIP com AP_/BL_/CP_/CSC_.tar.md5 dentro
          'ap_tar'     → AP_*.tar.md5 diretamente
          'super_lz4'  → super.img.lz4 já extraído
          'super_img'  → super.img já descomprimido
          'super_raw'  → super_raw.img já unsparse
          'part_dir'   → diretório com system/, vendor/, etc. já extraídos
          'payload'    → ROM AOSP com payload.bin (Evolution X, LineageOS, etc.)
        """
        if path.is_dir():
            # Verifica se é diretório de partições já extraídas
            has_parts = any((path / p).exists() for p in ["system", "vendor", "product"])
            if has_parts:
                return "part_dir"
            # Pode ser um diretório com AP_*.tar.md5 dentro
            if any(path.glob("AP_*.tar.md5")):
                return "odin_dir"
            return "unknown_dir"

        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {path}")

        name = path.name.lower()
        if name.endswith(".zip"):
            # Inspeciona o ZIP para detectar o conteúdo
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
            has_ap = any(n.startswith("AP_") and n.endswith(".tar.md5") for n in names)
            has_payload = "payload.bin" in names
            if has_ap:
                return "odin_zip"
            if has_payload:
                return "payload_zip"
            # ZIP com super.img direto
            if any("super.img" in n for n in names):
                return "super_zip"
            return "unknown_zip"

        if "AP_" in path.name and path.name.endswith(".tar.md5"):
            return "ap_tar"
        if name.endswith("super.img.lz4"):
            return "super_lz4"
        if name == "super.img":
            return "super_img"
        if "super_raw" in name or name == "super.img.raw":
            return "super_raw"
        if name.endswith(".tar.md5"):
            return "ap_tar"  # outro tar.md5 — tenta como AP

        return "unknown"

    # ── Etapa 1: ZIP Odin → AP_*.tar.md5 ────────────────────────────────────

    def extract_odin_zip(self, zip_path: Path, work_dir: Path) -> Path:
        """
        Extrai apenas o AP_*.tar.md5 do ZIP principal do firmware Samsung.
        O AP file é o maior (8–10 GB); BL/CP/CSC são ignorados para o port.
        """
        self.logger.info("  [1/5] Extraindo AP do ZIP Odin Samsung...")
        work_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            ap_files = [n for n in zf.namelist() if n.startswith("AP_") and n.endswith(".tar.md5")]
            if not ap_files:
                # Alguns ZIPs têm os tar.md5 em subpastas
                ap_files = [n for n in zf.namelist() if "AP_" in n and ".tar.md5" in n]
            if not ap_files:
                raise ValueError(
                    "ZIP não contém AP_*.tar.md5!\n"
                    f"  Arquivos encontrados: {zf.namelist()[:10]}"
                )

            ap_name = ap_files[0]
            ap_dest = work_dir / Path(ap_name).name
            self.logger.info(f"  AP: {ap_name}")

            if not ap_dest.exists():
                self.logger.info(f"  Extraindo {ap_name} ({zf.getinfo(ap_name).file_size // 1024 // 1024} MB)...")
                with zf.open(ap_name) as src, open(ap_dest, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=16 * 1024 * 1024)
            else:
                self.logger.info(f"  AP já existe: {ap_dest.name}")

        return ap_dest

    # ── Etapa 2: AP_*.tar.md5 → super.img.lz4 ──────────────────────────────

    def extract_ap_tar(self, ap_tar: Path, work_dir: Path) -> Path:
        """
        Extrai o super.img.lz4 de dentro do AP_*.tar.md5.
        O AP também contém: boot.img.lz4, dtbo.img.lz4, vbmeta.img.lz4,
        vendor_boot.img.lz4, recovery.img.lz4 — ignoramos para o port.
        """
        self.logger.info("  [2/5] Extraindo super.img.lz4 do AP_*.tar.md5...")
        work_dir.mkdir(parents=True, exist_ok=True)

        super_lz4 = work_dir / "super.img.lz4"
        if super_lz4.exists():
            self.logger.info(f"  super.img.lz4 já existe ({super_lz4.stat().st_size // 1024 // 1024} MB)")
            return super_lz4

        import tarfile
        self.logger.info(f"  Abrindo {ap_tar.name} ({ap_tar.stat().st_size // 1024 // 1024} MB)...")

        with tarfile.open(ap_tar, "r:*") as tf:
            members = tf.getnames()
            self.logger.debug(f"  Conteúdo do AP: {members}")

            # super.img.lz4 pode estar na raiz ou em subpasta
            super_members = [m for m in members if "super.img.lz4" in m]
            if not super_members:
                raise ValueError(
                    "super.img.lz4 não encontrado no AP!\n"
                    f"  Conteúdo: {members}"
                )

            member_name = super_members[0]
            self.logger.info(f"  Extraindo: {member_name}")
            member = tf.getmember(member_name)
            member.name = "super.img.lz4"  # Normaliza o nome
            tf.extract(member, path=work_dir)

        self.logger.info(f"  super.img.lz4: {super_lz4.stat().st_size // 1024 // 1024} MB")
        return super_lz4

    # ── Etapa 3: super.img.lz4 → super.img (lz4 -d) ────────────────────────

    def decompress_lz4(self, lz4_path: Path, out_path: Path) -> Path:
        """Descomprime super.img.lz4 → super.img."""
        if out_path.exists():
            self.logger.info(f"  super.img já existe ({out_path.stat().st_size // 1024 // 1024} MB)")
            return out_path

        self.logger.info("  [3/5] Descomprimindo LZ4...")

        # Tenta lz4 do sistema
        lz4_bin = shutil.which("lz4") or shutil.which("lz4cat")
        if lz4_bin:
            self.logger.info(f"  Usando {lz4_bin}...")
            with open(out_path, "wb") as out_f:
                result = subprocess.run(
                    [lz4_bin, "-d", str(lz4_path), "-"],
                    stdout=out_f, stderr=subprocess.PIPE
                )
                if result.returncode != 0:
                    out_path.unlink(missing_ok=True)
                    raise subprocess.CalledProcessError(result.returncode, lz4_bin, result.stderr)
        else:
            # Fallback: Python lz4 (pip install lz4)
            self.logger.info("  Usando Python lz4...")
            try:
                import lz4.frame
                with open(lz4_path, "rb") as f_in, open(out_path, "wb") as f_out:
                    chunk = 16 * 1024 * 1024  # 16 MB chunks
                    ctx = lz4.frame.create_decompression_context()
                    while True:
                        data = f_in.read(chunk)
                        if not data:
                            break
                        out, _, _ = lz4.frame.decompress_chunk(ctx, data)
                        f_out.write(out)
            except ImportError:
                raise RuntimeError(
                    "lz4 não encontrado! Instale:\n"
                    "  sudo apt install lz4\n"
                    "  ou: pip install lz4"
                )

        self.logger.info(f"  super.img: {out_path.stat().st_size // 1024 // 1024} MB")
        return out_path

    # ── Etapa 4: super.img → super_raw.img (simg2img) ───────────────────────

    def unsparse_super(self, super_img: Path, raw_path: Path) -> Path:
        """
        Converte super.img sparse → raw com simg2img.
        Samsung usa sparse format — lpunpack não consegue ler diretamente.
        """
        if raw_path.exists():
            self.logger.info(f"  super_raw.img já existe ({raw_path.stat().st_size // 1024 // 1024} MB)")
            return raw_path

        self.logger.info("  [4/5] Convertendo sparse → raw (simg2img)...")

        # Verifica se é sparse de verdade
        with open(super_img, "rb") as f:
            magic = f.read(4)
        is_sparse = (magic == b'\x3a\xff\x26\xed')

        if not is_sparse:
            self.logger.info("  super.img não é sparse — usando diretamente.")
            return super_img

        simg2img = self._tool("simg2img")
        run_cmd([simg2img, str(super_img), str(raw_path)], self.logger)
        self.logger.info(f"  super_raw.img: {raw_path.stat().st_size // 1024 // 1024} MB")
        return raw_path

    # ── Etapa 5: super_raw.img → system.img, vendor.img, ... (lpunpack) ─────

    def lpunpack_super(self, raw_img: Path, imgs_dir: Path) -> dict[str, Path]:
        """
        Extrai as partições individuais do super_raw.img.
        Retorna dict: {"system": Path("system.img"), "vendor": Path("vendor.img"), ...}
        """
        imgs_dir.mkdir(parents=True, exist_ok=True)

        # Verifica se já foi extraído
        existing = {p.stem: p for p in imgs_dir.glob("*.img")}
        if existing:
            self.logger.info(f"  Partições já extraídas: {list(existing.keys())}")
            return existing

        self.logger.info("  [5/5] Extraindo partições com lpunpack...")
        lpunpack = self._tool("lpunpack")

        # Samsung usa slots A/B: --slot=0 para pegar as partições _a
        run_cmd([lpunpack, "--slot=0", str(raw_img), str(imgs_dir)], self.logger)

        imgs = {p.stem: p for p in imgs_dir.glob("*.img")}
        self.logger.info(f"  Partições extraídas: {list(imgs.keys())}")
        return imgs

    # ── Etapa 6: .img → pasta de arquivos ───────────────────────────────────

    def extract_partition_img(self, img_path: Path, dest_dir: Path) -> bool:
        """
        Extrai o conteúdo de uma imagem de partição para uma pasta.
        Suporta: ext4, f2fs, erofs.
        """
        if dest_dir.exists() and any(dest_dir.iterdir()):
            self.logger.debug(f"  {dest_dir.name}/ já extraído.")
            return True

        dest_dir.mkdir(parents=True, exist_ok=True)

        # Detecta filesystem
        file_out = subprocess.run(
            ["file", str(img_path)], capture_output=True, text=True
        ).stdout.lower()

        if "erofs" in file_out:
            return self._extract_erofs(img_path, dest_dir)
        elif "f2fs" in file_out:
            return self._extract_f2fs(img_path, dest_dir)
        else:
            # Assume ext4
            return self._extract_ext4(img_path, dest_dir)

    def _extract_ext4(self, img: Path, dest: Path) -> bool:
        """
        Extrai ext4 com debugfs via stdin pipe — método confirmado como funcional
        em servidores sem loop devices.

        Fallbacks: mount loop → 7z → ext4 Python
        """
        self.logger.info(f"  ext4: {img.name} → {dest.name}/")
        dest.mkdir(parents=True, exist_ok=True)

        # ── Método 1: debugfs via stdin pipe (mais confiável sem root) ────────
        # Sintaxe: echo "rdump / /dest" | debugfs image.img
        # NOTA: o destino precisa existir antes e ser passado como path absoluto
        debugfs = shutil.which("debugfs")
        if debugfs:
            # rdump exige que o destino exista previamente
            dest.mkdir(parents=True, exist_ok=True)
            cmd_input = f'rdump / "{dest.resolve()}"'
            r = subprocess.run(
                [debugfs, str(img)],
                input=cmd_input,
                capture_output=True,
                text=True
            )
            # debugfs sempre retorna 0; checa se extraiu algo real (além de lost+found)
            extracted = [f for f in dest.iterdir()
                         if f.name not in ("lost+found", ".", "..")]
            if extracted:
                self.logger.info(f"  debugfs pipe OK: {img.name} ({len(extracted)} itens)")
                return True
            else:
                self.logger.debug(f"  debugfs pipe: sem arquivos extraídos. stderr: {r.stderr[:200]}")

        # ── Método 2: mount loop (funciona em host com loop devices) ──────────
        mount_pt = dest.parent / f"{dest.name}_mnt"
        mount_pt.mkdir(parents=True, exist_ok=True)
        r2 = subprocess.run(
            ["sudo", "mount", "-o", "loop,ro", str(img), str(mount_pt)],
            capture_output=True, text=True
        )
        if r2.returncode == 0:
            self.logger.info(f"  mount loop OK: {img.name}")
            rsync = shutil.which("rsync")
            ok = False
            try:
                if rsync:
                    r3 = subprocess.run(
                        [rsync, "-a", "--no-owner", "--no-group",
                         str(mount_pt) + "/", str(dest) + "/"],
                        capture_output=True, text=True
                    )
                    ok = r3.returncode == 0
                if not ok:
                    shutil.copytree(str(mount_pt), str(dest),
                                    symlinks=True, dirs_exist_ok=True)
                    ok = True
            finally:
                subprocess.run(["sudo", "umount", str(mount_pt)], capture_output=True)
                try:
                    mount_pt.rmdir()
                except Exception:
                    pass
            if ok:
                return True
        else:
            self.logger.debug(f"  mount falhou: {r2.stderr.strip()[:120]}")
            try:
                mount_pt.rmdir()
            except Exception:
                pass

        # ── Método 3: 7z ─────────────────────────────────────────────────────
        for sevenzip in ["7z", "7za", "7zr"]:
            bin7z = shutil.which(sevenzip)
            if bin7z:
                self.logger.info(f"  Tentando {sevenzip}...")
                r4 = subprocess.run(
                    [bin7z, "x", str(img), f"-o{dest}", "-y"],
                    capture_output=True, text=True
                )
                if r4.returncode == 0 and any(dest.iterdir()):
                    return True
                break

        # ── Método 4: ext4 Python puro ────────────────────────────────────────
        try:
            import importlib
            ext4_mod = importlib.import_module("ext4")
            self.logger.info(f"  Tentando ext4 Python...")
            with open(img, "rb") as f_img:
                vol = ext4_mod.Volume(f_img)
                self._ext4_extract_dir(vol.root, dest)
            if any(dest.iterdir()):
                return True
        except ImportError:
            pass
        except Exception as e:
            self.logger.debug(f"  ext4 Python falhou: {e}")

        self.logger.error(
            f"  FALHA ao extrair {img.name}!\n"
            f"  Este servidor nao tem loop devices. Instale:\n"
            f"    pip install ext4       # extração Python pura, sem root\n"
            f"    sudo apt install p7zip-full  # alternativa\n"
            f"  Ou use Docker com --privileged para mount loop funcionar."
        )
        return False

    def _ext4_extract_dir(self, inode, dest: Path):
        """Extrai recursivamente um diretório de um volume ext4 Python."""
        dest.mkdir(parents=True, exist_ok=True)
        for name, child_inode, _ in inode.open_dir():
            if name in (b".", b".."):
                continue
            fname = name.decode("utf-8", errors="replace")
            child_path = dest / fname
            if child_inode.is_dir:
                self._ext4_extract_dir(child_inode, child_path)
            else:
                try:
                    child_path.write_bytes(child_inode.open_read().read())
                except Exception:
                    pass

    def _extract_erofs(self, img: Path, dest: Path) -> bool:
        """Extrai EROFS via fsck.erofs ou erofsfuse."""
        self.logger.info(f"  EROFS: {img.name} → {dest.name}/")
        # fsck.erofs --extract
        fsck = shutil.which("fsck.erofs")
        if fsck:
            result = subprocess.run(
                [fsck, f"--extract={dest}", str(img)],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                return True

        # erofsfuse (FUSE mount)
        erofsfuse = shutil.which("erofsfuse") or str(self._bin / "erofsfuse")
        if Path(erofsfuse).exists():
            mount_pt = dest.parent / f"{dest.name}_mnt"
            mount_pt.mkdir(exist_ok=True)
            subprocess.run([erofsfuse, str(img), str(mount_pt)])
            shutil.copytree(mount_pt, dest, symlinks=True)
            subprocess.run(["fusermount", "-u", str(mount_pt)], capture_output=True)
            return True

        self.logger.warning(f"  EROFS: instale erofs-utils (sudo apt install erofs-utils)")
        return False

    def _extract_f2fs(self, img: Path, dest: Path) -> bool:
        """Extrai F2FS via mount (precisa de sudo e módulo f2fs no kernel)."""
        self.logger.info(f"  F2FS: {img.name} → {dest.name}/")
        mount_pt = dest.parent / f"{dest.name}_mnt"
        mount_pt.mkdir(exist_ok=True)
        result = subprocess.run(
            ["sudo", "mount", "-t", "f2fs", "-o", "loop,ro", str(img), str(mount_pt)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            tmp = dest.parent / f"{dest.name}_copy"
            shutil.copytree(mount_pt, tmp, symlinks=True)
            subprocess.run(["sudo", "umount", str(mount_pt)])
            mount_pt.rmdir()
            tmp.rename(dest)
            return True
        self.logger.warning(
            f"  F2FS: não foi possível montar. O kernel suporta F2FS?\n"
            f"  Tente: sudo modprobe f2fs"
        )
        return False

    # ── Pipeline principal: base ROM stock Samsung ───────────────────────────

    def prepare_base_stock(self, base_input: Path) -> Path:
        """
        Pipeline completo para firmware stock Samsung.
        Aceita ZIP Odin, AP_*.tar.md5, super.img.lz4, super.img, ou super_raw.img.
        """
        self.logger.info("\n[STAGE 1a] Preparando Base ROM (Stock Samsung One UI)...")

        work = self.build_dir / "base_work"
        imgs_dir = self.build_dir / "base_imgs"
        base_dir = self.build_dir / "base"

        input_type = self.detect_input_type(base_input)
        self.logger.info(f"  Tipo de input detectado: {input_type}")

        # Atalhos se o usuário já tem um estágio mais avançado
        if input_type == "part_dir":
            self.logger.info("  Partições já extraídas — usando diretamente.")
            return base_input

        if input_type == "super_raw":
            raw_img = base_input
        elif input_type in ("super_img",):
            super_img = base_input
            raw_img = work / "super_raw.img"
            raw_img = self.unsparse_super(super_img, raw_img)
        elif input_type == "super_lz4":
            work.mkdir(parents=True, exist_ok=True)
            super_img = self.decompress_lz4(base_input, work / "super.img")
            raw_img = self.unsparse_super(super_img, work / "super_raw.img")
        elif input_type == "ap_tar":
            work.mkdir(parents=True, exist_ok=True)
            super_lz4 = self.extract_ap_tar(base_input, work)
            super_img = self.decompress_lz4(super_lz4, work / "super.img")
            raw_img = self.unsparse_super(super_img, work / "super_raw.img")
        elif input_type in ("odin_zip", "odin_dir"):
            work.mkdir(parents=True, exist_ok=True)
            if input_type == "odin_zip":
                ap_tar = self.extract_odin_zip(base_input, work)
            else:
                ap_files = list(base_input.glob("AP_*.tar.md5"))
                if not ap_files:
                    raise FileNotFoundError(f"AP_*.tar.md5 não encontrado em {base_input}")
                ap_tar = ap_files[0]
            super_lz4 = self.extract_ap_tar(ap_tar, work)
            super_img = self.decompress_lz4(super_lz4, work / "super.img")
            raw_img = self.unsparse_super(super_img, work / "super_raw.img")
        elif input_type == "payload_zip":
            # Evolution X / LineageOS / Pixel ROMs com payload.bin
            self.logger.info("  ROM AOSP detectada (payload.bin)...")
            return self._prepare_payload_base(base_input)
        else:
            raise ValueError(
                f"Formato não reconhecido: {base_input}\n"
                f"  Tipo detectado: {input_type}\n"
                f"  Suportado: ZIP Odin, AP_*.tar.md5, super.img.lz4, super.img"
            )

        # lpunpack → imagens de partição individuais
        partition_imgs = self.lpunpack_super(raw_img, imgs_dir)

        # Extrai cada imagem → pasta de arquivos
        base_dir.mkdir(parents=True, exist_ok=True)
        for part in REAL_PARTITIONS:
            # lpunpack com --slot=0 gera system_a.img, vendor_a.img etc.
            img = partition_imgs.get(part) or partition_imgs.get(f"{part}_a")
            if img and img.exists():
                dest = base_dir / part
                if not dest.exists():
                    self.extract_partition_img(img, dest)
            else:
                self.logger.debug(f"  Partição não encontrada na base: {part}")

        found = [p.name for p in base_dir.iterdir() if p.is_dir()]
        self.logger.info(f"  Base pronta: {found}")
        return base_dir

    def _prepare_payload_base(self, zip_path: Path) -> Path:
        """Extrai base ROM em formato payload.bin (AOSP)."""
        work = self.build_dir / "base_work"
        work.mkdir(parents=True, exist_ok=True)
        base_dir = self.build_dir / "base"

        # Extrai payload.bin do ZIP
        with zipfile.ZipFile(zip_path, "r") as zf:
            if "payload.bin" in zf.namelist():
                payload_path = work / "payload.bin"
                if not payload_path.exists():
                    self.logger.info("  Extraindo payload.bin...")
                    with zf.open("payload.bin") as src, open(payload_path, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=16 * 1024 * 1024)

        # Extrai com _extract_payload (tenta múltiplos métodos)
        imgs_dir = self.build_dir / "base_imgs"
        self._extract_payload(work / "payload.bin", imgs_dir)

        # Extrai imagens
        base_dir.mkdir(exist_ok=True)
        for part in REAL_PARTITIONS:
            img = imgs_dir / f"{part}.img"
            if img.exists():
                dest = base_dir / part
                if not dest.exists():
                    self.extract_partition_img(img, dest)

        return base_dir

    def _extract_payload(self, payload_path: Path, imgs_dir: Path):
        """
        Extrai payload.bin usando payload-dumper-go, ota_extractor,
        ou tenta instalar o payload-dumper automaticamente.
        """
        imgs_dir.mkdir(exist_ok=True)

        # 1. payload-dumper-go (Go binary, mais rápido)
        for tool in ["payload-dumper-go"]:
            if shutil.which(tool):
                self.logger.info(f"  Usando {tool} (isso pode demorar vários minutos)...")
                run_cmd([tool, "-o", str(imgs_dir), str(payload_path)],
                        self.logger, stream=True)
                return

        # 2. ota_extractor do otatools incluso no repo
        for candidate in [
            Path("otatools/bin/ota_extractor"),
            Path("otatools/bin/delta_generator"),
            self._bin / "ota_extractor",
        ]:
            if candidate.exists():
                self.logger.info(f"  Usando {candidate.name}...")
                candidate.chmod(0o755)
                run_cmd([str(candidate), "--payload", str(payload_path),
                         "--output_dir", str(imgs_dir)], self.logger)
                return

        # 3. Python payload_dumper (pip)
        try:
            import payload_dumper  # noqa
            self.logger.info("  Usando payload_dumper Python...")
            # Chama como subprocess para não poluir o processo atual
            result = subprocess.run(
                [sys.executable, "-m", "payload_dumper",
                 "--out", str(imgs_dir), str(payload_path)],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                return
        except ImportError:
            pass

        # 4. Tenta instalar payload-dumper-go automaticamente
        self.logger.info("  payload-dumper-go não encontrado. Tentando instalar...")
        import platform, urllib.request, tarfile as _tarfile
        arch = platform.machine()
        arch_map = {"x86_64": "amd64", "aarch64": "arm64"}
        go_arch = arch_map.get(arch, "amd64")
        url = (
            f"https://github.com/ssut/payload-dumper-go/releases/latest/download/"
            f"payload-dumper-go_linux_{go_arch}.tar.gz"
        )
        try:
            tgz = self.build_dir / "payload-dumper-go.tar.gz"
            self.logger.info(f"  Baixando {url}...")
            urllib.request.urlretrieve(url, tgz)
            with _tarfile.open(tgz) as tf:
                for member in tf.getmembers():
                    if member.name.endswith("payload-dumper-go"):
                        member.name = "payload-dumper-go"
                        tf.extract(member, path=self._bin)
                        (self._bin / "payload-dumper-go").chmod(0o755)
                        break
            tgz.unlink(missing_ok=True)
            self.logger.info("  payload-dumper-go instalado em bin/linux/x86_64/")
            run_cmd([str(self._bin / "payload-dumper-go"),
                     "-o", str(imgs_dir), str(payload_path)], self.logger)
            return
        except Exception as e:
            self.logger.warning(f"  Download falhou: {e}")

        raise RuntimeError(
            "Nenhum extrator de payload.bin encontrado!\n"
            "  Instale manualmente:\n"
            "    wget https://github.com/ssut/payload-dumper-go/releases/latest/download/payload-dumper-go_linux_amd64.tar.gz\n"
            "    tar xzf payload-dumper-go_linux_amd64.tar.gz\n"
            "    sudo mv payload-dumper-go /usr/local/bin/\n"
            "  Ou via pip:\n"
            "    pip install payload-dumper"
        )

    def prepare_port(self, port_input: Path) -> Path:
        """Extrai e prepara a Port ROM (ColorOS)."""
        self.logger.info("\n[STAGE 1b] Preparando Port ROM (ColorOS)...")

        work = self.build_dir / "port_work"
        imgs_dir = self.build_dir / "port_imgs"
        port_dir = self.build_dir / "port"

        input_type = self.detect_input_type(port_input)
        self.logger.info(f"  Tipo: {input_type}")

        if input_type == "part_dir":
            self.logger.info("  Partições ColorOS já extraídas.")
            return port_input

        work.mkdir(parents=True, exist_ok=True)

        if input_type in ("payload_zip", "odin_zip"):
            # ColorOS moderno vem como payload.bin OTA
            with zipfile.ZipFile(port_input, "r") as zf:
                names = zf.namelist()

            if "payload.bin" in names:
                payload_path = work / "payload.bin"
                if not payload_path.exists():
                    self.logger.info("  Extraindo payload.bin do port...")
                    with zipfile.ZipFile(port_input, "r") as zf:
                        with zf.open("payload.bin") as src, open(payload_path, "wb") as dst:
                            shutil.copyfileobj(src, dst, length=16 * 1024 * 1024)

                imgs_dir.mkdir(exist_ok=True)
                self._extract_payload(payload_path, imgs_dir)

            # Pode também ter super.img
            elif any("super.img" in n for n in names):
                with zipfile.ZipFile(port_input, "r") as zf:
                    super_member = next(n for n in names if "super.img" in n)
                    super_path = work / "super.img"
                    if not super_path.exists():
                        with zf.open(super_member) as src, open(super_path, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                raw = self.unsparse_super(super_path, work / "super_raw.img")
                partition_imgs = self.lpunpack_super(raw, imgs_dir)
                imgs_dir = Path(".")  # dummy, usaremos partition_imgs diretamente
                port_dir.mkdir(exist_ok=True)
                for part in REAL_PARTITIONS + OPLUS_STUB_PARTITIONS:
                    img = partition_imgs.get(part) or partition_imgs.get(f"{part}_a")
                    if img and img.exists():
                        dest = port_dir / part
                        if not dest.exists():
                            self.extract_partition_img(img, dest)
                return port_dir

        elif input_type == "ap_tar":
            # ColorOS em formato Odin (raro mas acontece)
            super_lz4 = self.extract_ap_tar(port_input, work)
            super_img = self.decompress_lz4(super_lz4, work / "super_port.img")
            raw = self.unsparse_super(super_img, work / "super_port_raw.img")
            partition_imgs = self.lpunpack_super(raw, imgs_dir)

        port_dir.mkdir(exist_ok=True)
        all_parts = REAL_PARTITIONS + OPLUS_STUB_PARTITIONS
        for part in all_parts:
            img = imgs_dir / f"{part}.img"
            if not img.exists():
                img = imgs_dir / f"{part}_a.img"
            if img.exists():
                dest = port_dir / part
                if not dest.exists():
                    self.extract_partition_img(img, dest)

        found = [p.name for p in port_dir.iterdir() if p.is_dir()]
        self.logger.info(f"  Port pronto: {found}")
        return port_dir


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 2: MERGE (Base Samsung + Port ColorOS)
# ──────────────────────────────────────────────────────────────────────────────

class RomMerger:
    """
    Faz o merge das partições:
    - Partições reais vêm da BASE (Samsung AOSP/Evolution X)
    - Partições oplus (my_*) vêm do PORT (ColorOS)
    - Sobreposições específicas do S23 são aplicadas
    """

    def __init__(self, base_dir: Path, port_dir: Path, target_dir: Path,
                 device_cfg: dict, logger: logging.Logger):
        self.base_dir = base_dir
        self.port_dir = port_dir
        self.target_dir = target_dir
        self.device_cfg = device_cfg
        self.logger = logger

    def _copy_partition(self, src: Path, dst: Path):
        if dst.exists():
            self.logger.debug(f"  Skip (já existe): {dst.name}")
            return
        self.logger.info(f"  Copiando {src.name} → target/{dst.name}")
        shutil.copytree(src, dst, symlinks=True)

    def _handle_nested_system(self, part_dir: Path) -> Path:
        """Trata path aninhado system/system/ (comum no Evolution X)."""
        nested = part_dir / part_dir.name
        if nested.exists() and (nested / "build.prop").exists():
            self.logger.debug(f"  Path aninhado detectado: {nested}")
            return nested
        return part_dir

    def merge(self) -> Path:
        self.logger.info("\n[STAGE 2] Merge das partições...")
        self.target_dir.mkdir(parents=True, exist_ok=True)

        # 1. Copia partições reais da BASE (kernel, drivers, HALs do Samsung)
        for part in REAL_PARTITIONS:
            src = self.base_dir / part
            if src.exists():
                self._copy_partition(src, self.target_dir / part)

        # 2. Copia partições oplus do PORT (interface ColorOS)
        #    Filtra diretórios _mnt que são artefatos temporários de mount
        for part in OPLUS_STUB_PARTITIONS:
            src = self.port_dir / part
            # Ignora diretórios com sufixo _mnt (artefatos de mount loop)
            if part.endswith("_mnt"):
                continue
            if src.exists():
                self._copy_partition(src, self.target_dir / part)
            else:
                self.logger.debug(f"  Particao oplus ausente no port: {part}")

        # 3. Overlay seletivo de apps ColorOS
        self._apply_coloros_overlay()

        # Conta só partições válidas (sem _mnt)
        valid = [p for p in self.target_dir.iterdir() if not p.name.endswith("_mnt")]
        self.logger.info(f"  Merge completo: {len(valid)} particoes")
        return self.target_dir

    def _apply_coloros_overlay(self):
        """Aplica arquivos seletivos do ColorOS sobre a base."""
        self.logger.info("  Aplicando overlay ColorOS...")

        # Apps e overlays visuais do ColorOS que queremos manter
        coloros_product_apps = [
            "app/OplusCamera",
            "app/OplusSystemUI",
            "priv-app/OPLauncher3",
        ]

        port_product = self.port_dir / "product"
        target_product = self.target_dir / "product"

        if port_product.exists() and target_product.exists():
            for app_path in coloros_product_apps:
                src = port_product / app_path
                dst = target_product / app_path
                if src.exists() and not dst.exists():
                    self.logger.info(f"    Overlay: product/{app_path}")
                    shutil.copytree(src, dst, symlinks=True)


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 3: PATCHES ESPECÍFICOS DO S23
# ──────────────────────────────────────────────────────────────────────────────

class S23Patcher:
    """Aplica todos os patches necessários para o Galaxy S23."""

    def __init__(self, target_dir: Path, device_cfg: dict, logger: logging.Logger):
        self.target_dir = target_dir
        self.cfg = device_cfg
        self.logger = logger

    # ── 3.1: Stubs para partições oplus ──────────────────────────────────────

    def create_oplus_stubs(self) -> bool:
        """
        Cria stubs mínimos para partições oplus que não existem na base Samsung.
        Inclui build.prop, fs_config e file_contexts — necessários para o packer.
        """
        self.logger.info("  [3.1] Criando stubs de partições oplus...")
        config_dir = self.target_dir.parent / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        for part in OPLUS_STUB_PARTITIONS:
            part_dir = self.target_dir / part
            if part_dir.exists() and (part_dir / "build.prop").exists():
                # Partição real do ColorOS — só garante fs_config
                self._generate_fs_config(part_dir, part, config_dir)
                continue

            # Cria stub mínimo
            self.logger.info(f"    Stub: {part}")
            part_dir.mkdir(parents=True, exist_ok=True)
            (part_dir / "etc").mkdir(exist_ok=True)

            stub_content = "\n".join([
                f"# {part} stub — ColorOS port S23",
                f"ro.oplus.image.{part}.type=all",
                f"ro.product.{part}.brand={self.cfg['brand']}",
                f"ro.product.{part}.device={self.cfg.get('codenames', ['dm1q'])[0]}",
                f"ro.product.{part}.model={self.cfg['model']}",
                f"ro.product.{part}.manufacturer={self.cfg['manufacturer']}", "",
            ])
            (part_dir / "build.prop").write_text(stub_content, encoding="utf-8")
            self._generate_fs_config(part_dir, part, config_dir)

        return True

    def _generate_fs_config(self, part_dir: Path, part_name: str, config_dir: Path):
        """
        Gera fs_config e file_contexts para partições oplus (my_*).

        Formato exato esperado pelo mkfs.erofs incluso no bin/:
            <path> <uid> <gid> <mode>
        Exemplos válidos:
            my_product 0 2000 0755
            my_product/build.prop 0 0 0644
            my_product/etc 0 2000 0755

        Cuidados:
        - Nunca gerar path vazio ou "." — causa "failed to find  in canned fs_config"
        - Ignorar symlinks quebrados
        - Ignorar a própria raiz do rglob (relative_to retorna PosixPath('.'))
        """
        fs_cfg = config_dir / f"{part_name}_fs_config"
        fc_cfg = config_dir / f"{part_name}_file_contexts"

        # Regenera sempre (pode ter sido gerado incorretamente antes)
        if fs_cfg.exists():
            fs_cfg.unlink()
        if fc_cfg.exists():
            fc_cfg.unlink()

        lines = []
        # Entrada da raiz da partição
        lines.append(f"{part_name} 0 2000 0755")

        for fp in sorted(part_dir.rglob("*")):
            # Ignora symlinks quebrados
            if fp.is_symlink() and not fp.exists():
                continue

            try:
                rel = fp.relative_to(part_dir)
            except ValueError:
                continue

            # Ignora a raiz (relative_to retorna PosixPath('.'))
            rel_str = str(rel)
            if rel_str in (".", ""):
                continue

            # Normaliza separadores
            rel_str = rel_str.replace("\\", "/")

            if fp.is_dir():
                lines.append(f"{part_name}/{rel_str} 0 2000 0755")
            else:
                lines.append(f"{part_name}/{rel_str} 0 0 0644")

        fs_cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.logger.debug(f"    fs_config: {fs_cfg.name} ({len(lines)} entradas)")

        # file_contexts mínimo para SELinux
        fc_lines = [
            f"/{part_name}(/.*)?             u:object_r:system_file:s0",
            f"/{part_name}/build\\.prop      u:object_r:system_prop_file:s0",
            f"/{part_name}/etc(/.*)?         u:object_r:system_file:s0",
        ]
        fc_cfg.write_text("\n".join(fc_lines) + "\n", encoding="utf-8")

    # ── 3.2: Substituição de strings (device code) ──────────────────────────

    def replace_device_strings(self, port_device_code: str) -> bool:
        """
        Substitui referências ao dispositivo OnePlus/Oplus pelo Galaxy S23.
        Opera em todos os build.prop do target.
        """
        self.logger.info("  [3.2] Substituindo strings do dispositivo...")
        device_code = self.cfg.get("codenames", ["dm1q"])[0]
        model = self.cfg["model"]
        brand = self.cfg["brand"]
        manufacturer = self.cfg["manufacturer"]

        replacements = {
            # Strings que aparecem nos build.prop do ColorOS
            port_device_code: device_code,
        }

        count = 0
        for bp in self.target_dir.rglob("build.prop"):
            content = bp.read_text(encoding="utf-8", errors="ignore")
            changed = False
            for old, new in replacements.items():
                if old and old in content:
                    content = content.replace(old, new)
                    changed = True
            if changed:
                bp.write_text(content, encoding="utf-8")
                count += 1

        self.logger.info(f"    {count} arquivos atualizados.")
        return True

    # ── 3.3: Propriedades críticas do S23 ───────────────────────────────────

    def patch_build_props(self, base_dir: Path) -> bool:
        """
        Injeta/corrige propriedades críticas para o S23:
        - Identidade do dispositivo
        - Densidade de tela
        - Fingerprint base
        - ro.product.first_api_level (critical para boot)
        """
        self.logger.info("  [3.3] Corrigindo propriedades do S23...")
        device_code = self.cfg.get("codenames", ["dm1q"])[0]
        model = self.cfg["model"]
        brand = self.cfg["brand"]
        manufacturer = self.cfg["manufacturer"]
        density = self.cfg["lcd_density"]

        # Lê first_api_level da base (crítico para SELinux e compatibilidade)
        first_api = "33"  # Android 13 para S23
        for bp in base_dir.rglob("build.prop"):
            val = read_prop(bp, "ro.product.first_api_level")
            if val:
                first_api = val
                break

        s23_props = {
            "ro.product.brand":              brand,
            "ro.product.manufacturer":       manufacturer,
            "ro.product.device":             device_code,
            "ro.product.model":              model,
            "ro.product.name":               device_code,
            "ro.product.first_api_level":    first_api,
            "ro.sf.lcd_density":             density,
            "ro.build.product":              device_code,
            "persist.sys.device_name":       device_code,
            # Play Integrity
            "ro.secure":                     "1",
            "ro.debuggable":                 "0",
            "ro.boot.selinux":               "enforcing",
        }

        # Aplica em todas as partições relevantes
        modified = 0
        for part in ["system", "product", "system_ext", "vendor", "my_product"]:
            part_dir = self.target_dir / part
            if not part_dir.exists():
                continue

            # Considera path aninhado system/system/
            search_dir = part_dir / part
            if not (search_dir.exists() and (search_dir / "build.prop").exists()):
                search_dir = part_dir

            bp = search_dir / "build.prop"
            if bp.exists():
                n = batch_update_props(bp, s23_props)
                if n > 0:
                    modified += 1
                    self.logger.debug(f"    Atualizado: {bp.relative_to(self.target_dir)}")

        self.logger.info(f"    Propriedades aplicadas em {modified} partições.")
        return True

    # ── 3.4: Fingerprint do S23 ──────────────────────────────────────────────

    def regenerate_fingerprint(self, base_dir: Path) -> bool:
        """
        Regenera o fingerprint de build para o S23.
        Lê os valores reais da base ROM para garantir consistência.
        """
        self.logger.info("  [3.4] Regenerando fingerprint...")

        device_code = self.cfg.get("codenames", ["dm1q"])[0]
        brand = self.cfg["brand"]

        # Lê da base para ter valores reais
        def read_from_base(key: str, fallback: str) -> str:
            for bp in base_dir.rglob("build.prop"):
                v = read_prop(bp, key)
                if v:
                    return v
            return fallback

        version    = read_from_base("ro.build.version.release", "15")
        build_id   = read_from_base("ro.build.id", "AP3A.240905.015")
        incremental = read_from_base("ro.build.version.incremental", "S911BXXU7EXJ1")
        build_type = "user"
        tags       = "release-keys"
        name       = device_code

        fingerprint = f"{brand}/{name}/{device_code}:{version}/{build_id}/{incremental}:{build_type}/{tags}"
        description = f"{name}-{build_type} {version} {build_id} {incremental} {tags}"

        self.logger.info(f"    Fingerprint: {fingerprint}")

        fp_props = {
            "ro.build.fingerprint":             fingerprint,
            "ro.bootimage.build.fingerprint":   fingerprint,
            "ro.system.build.fingerprint":      fingerprint,
            "ro.product.build.fingerprint":     fingerprint,
            "ro.system_ext.build.fingerprint":  fingerprint,
            "ro.vendor.build.fingerprint":      fingerprint,
            "ro.odm.build.fingerprint":         fingerprint,
            "ro.build.description":             description,
        }

        modified = 0
        for bp in self.target_dir.rglob("build.prop"):
            if batch_update_props(bp, fp_props) > 0:
                modified += 1

        self.logger.info(f"    Fingerprint aplicado em {modified} arquivos.")
        return True

    # ── 3.5: Remoção de bloatware OnePlus/Oplus ─────────────────────────────

    def remove_oplus_bloat(self) -> bool:
        """Remove apps OnePlus que são incompatíveis com hardware Samsung."""
        self.logger.info("  [3.5] Removendo bloatware OnePlus incompatível...")

        # Estes apps são específicos de hardware OnePlus e causam crash no S23
        INCOMPATIBLE_APPS = [
            # Alert slider (OnePlus exclusive)
            "app/OPOneplusDialerAlertsSlider",
            "priv-app/OPTriStateApp",
            # OnePlus-specific sensors
            "app/OPSensorService",
            # OnePlus specific telephony
            "priv-app/OPTelephony",
        ]

        removed = 0
        for part in ["product", "system", "system_ext"]:
            part_dir = self.target_dir / part
            if not part_dir.exists():
                continue
            for app in INCOMPATIBLE_APPS:
                app_path = part_dir / app
                if app_path.exists():
                    self.logger.info(f"    Removendo: {part}/{app}")
                    shutil.rmtree(app_path)
                    removed += 1

        self.logger.info(f"    {removed} itens removidos.")
        return True

    # ── 3.6: SELinux contexts ────────────────────────────────────────────────

    def patch_selinux(self, base_dir: Path) -> bool:
        """
        Usa os SELinux contexts da BASE (Samsung/AOSP) para vendor/odm.
        O ColorOS tem policies específicas do SoC Qualcomm/Oplus mas
        o hardware real do S23 precisa dos contexts originais.
        """
        self.logger.info("  [3.6] Aplicando SELinux da base Samsung...")

        # Copia file_contexts da base para vendor e odm
        for part in ["vendor", "odm"]:
            base_etc = base_dir / part / "etc" / "selinux"
            target_etc = self.target_dir / part / "etc" / "selinux"
            if base_etc.exists() and target_etc.exists():
                for ctx_file in base_etc.glob("*.cil"):
                    dst = target_etc / ctx_file.name
                    if not dst.exists():
                        shutil.copy2(ctx_file, dst)
                        self.logger.debug(f"    SELinux: {ctx_file.name}")

        return True

    def run_all(self, port_device_code: str, base_dir: Path) -> bool:
        self.logger.info("\n[STAGE 3] Aplicando patches S23...")
        ok = True
        ok &= self.create_oplus_stubs()
        ok &= self.replace_device_strings(port_device_code)
        ok &= self.patch_build_props(base_dir)
        ok &= self.regenerate_fingerprint(base_dir)
        ok &= self.remove_oplus_bloat()
        ok &= self.patch_selinux(base_dir)
        return ok


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 4: EMPACOTAMENTO
# ──────────────────────────────────────────────────────────────────────────────

class RomPacker:
    """Empacota as partições de volta em super.img ou payload.bin."""

    def __init__(self, target_dir: Path, output_dir: Path,
                 device_cfg: dict, pack_type: str, logger: logging.Logger):
        self.target_dir = target_dir
        self.output_dir = output_dir
        self.cfg = device_cfg
        self.pack_type = pack_type  # "super" ou "payload"
        self.logger = logger
        self.bin_dir = Path("bin/linux/x86_64")
        self.config_dir = target_dir.parent / "config"

    def _get_tool(self, name: str) -> str:
        local = self.bin_dir / name
        if local.exists():
            return str(local)
        system = shutil.which(name)
        if system:
            return system
        raise FileNotFoundError(f"Ferramenta não encontrada: {name}")

    def pack_partition_erofs(self, part_name: str, part_dir: Path) -> Optional[Path]:
        """
        Empacota uma partição como EROFS.

        Regras:
        - Partições reais (system/vendor/etc): SEM --fs-config-file nem --file-contexts.
          O mkfs.erofs do bin/ incluso falha com fs_config externo nessas partições grandes.
        - Partições oplus (my_*): COM fs_config gerado pelo S23Patcher, mas APENAS
          se o arquivo fs_config não tiver entradas inválidas.
        - Imagens de 0 bytes de rodadas anteriores são apagadas e recriadas.
        """
        output_img = self.output_dir / f"{part_name}.img"

        # Apaga imagem vazia de rodada anterior falha
        if output_img.exists():
            if output_img.stat().st_size > 0:
                self.logger.info(f"  EROFS: {part_name}.img ja existe "
                                 f"({output_img.stat().st_size // 1024 // 1024} MB)")
                return output_img
            else:
                self.logger.warning(f"  {part_name}.img esta vazia (rodada anterior falhou) — apagando.")
                output_img.unlink()

        # Verifica se a partição tem conteúdo real
        if not part_dir.exists():
            self.logger.warning(f"  Skip {part_name}: diretorio nao existe")
            return None
        try:
            first = next(part_dir.iterdir())  # noqa — só verifica se há algo
        except StopIteration:
            self.logger.warning(f"  Skip {part_name}: diretorio vazio")
            return None

        # Partições oplus sem fs_config gerado — não inclui no super
        fs_config     = self.config_dir / f"{part_name}_fs_config"
        file_contexts = self.config_dir / f"{part_name}_file_contexts"
        if part_name in OPLUS_STUB_PARTITIONS:
            if not fs_config.exists() or not file_contexts.exists():
                self.logger.warning(f"  Skip {part_name}: sem fs_config gerado")
                return None

        try:
            mkfs_erofs = self._get_tool("mkfs.erofs")
        except FileNotFoundError:
            self.logger.error("mkfs.erofs nao encontrado! Instale erofs-utils.")
            return None

        cmd = [mkfs_erofs]

        # fs_config/file_contexts APENAS para partições oplus
        # (partições reais do Samsung não precisam e o mkfs.erofs falha com elas)
        if part_name in OPLUS_STUB_PARTITIONS:
            cmd += ["--fs-config-file", str(fs_config)]
            cmd += ["--file-contexts",  str(file_contexts)]

        cmd += [str(output_img), str(part_dir)]

        try:
            run_cmd(cmd, self.logger)
            size_mb = output_img.stat().st_size // 1024 // 1024
            if output_img.stat().st_size == 0:
                self.logger.error(f"  mkfs.erofs produziu imagem vazia para {part_name}!")
                output_img.unlink()
                return None
            self.logger.info(f"  EROFS: {part_name}.img ({size_mb} MB)")
            return output_img
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.strip() if e.stderr else "(sem mensagem)"
            self.logger.error(f"  Falha ao empacotar {part_name}: {stderr[:300]}")
            # Limpa arquivo parcial
            output_img.unlink(missing_ok=True)
            return None

    def _align_size(self, size: int, block: int = 512) -> int:
        """Alinha tamanho para múltiplo de block bytes (requerido pelo lpmake)."""
        return ((size + block - 1) // block) * block

    def pack_super(self, partition_imgs: list[Path]) -> Optional[Path]:
        """
        Monta super.img a partir das imagens de partição.
        Filtra imagens de tamanho 0 (partições que falharam na extração)
        e alinha tamanhos para múltiplos de 512 bytes (obrigatório pelo lpmake).
        """
        super_img = self.output_dir / "super.img"
        super_size = self.cfg["super_size"]

        try:
            lpmake = self._get_tool("lpmake")
        except FileNotFoundError:
            self.logger.error("lpmake nao encontrado!")
            return None

        # Filtra imagens vazias — lpmake recusa size=0 com --image associado
        valid_imgs = [img for img in partition_imgs if img.stat().st_size > 0]
        skipped    = [img.stem for img in partition_imgs if img.stat().st_size == 0]
        if skipped:
            self.logger.warning(f"  Ignorando imagens vazias (extracao falhou): {skipped}")
            self.logger.warning("  ATENCAO: ROM incompleta — partições vão estar vazias no dispositivo!")
        if not valid_imgs:
            self.logger.error("  Nenhuma imagem valida para montar o super.img!")
            return None

        total = sum(img.stat().st_size for img in valid_imgs)
        self.logger.info(f"  Partições validas: {len(valid_imgs)} | "
                         f"Total: {total // 1024 // 1024} MB / {super_size // 1024 // 1024} MB")

        if total > super_size:
            self.logger.error(
                f"  ERRO: {total // 1024 // 1024} MB excede super size "
                f"({super_size // 1024 // 1024} MB)!"
            )
            return None

        group_a = "qti_dynamic_partitions_a"
        group_b = "qti_dynamic_partitions_b"

        cmd = [
            lpmake,
            "--metadata-size", "65536",
            "--super-name",    "super",
            "--metadata-slots", "2",
            "--device",        f"super:{super_size}",
            "--group",         f"{group_a}:{super_size}",
            "--group",         f"{group_b}:0",
        ]

        for img in valid_imgs:
            part_name    = img.stem
            # Tamanho alinhado a 512 bytes — obrigatório pelo lpmake
            aligned_size = self._align_size(img.stat().st_size)
            self.logger.debug(f"    {part_name}: {img.stat().st_size} → {aligned_size} bytes")
            cmd += [
                "--partition", f"{part_name}_a:{aligned_size}:{group_a}",
                "--image",     f"{part_name}_a={img}",
                "--partition", f"{part_name}_b:0:{group_b}",
            ]

        cmd += ["--sparse", "--output", str(super_img)]

        try:
            run_cmd(cmd, self.logger)
            size_mb = super_img.stat().st_size // 1024 // 1024
            self.logger.info(f"  super.img gerado: {size_mb} MB")
            return super_img
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.strip() if e.stderr else "(sem mensagem)"
            self.logger.error(f"  lpmake falhou: {stderr[:400]}")
            return None

    def create_flashable_zip(self, super_img: Path) -> Path:
        """Cria um zip flashável via TWRP/Magisk."""
        output_zip = self.output_dir / f"ColorOS_Port_S23_{self.cfg['model']}.zip"
        self.logger.info(f"  Criando zip flashável: {output_zip.name}")

        updater_script = """#!/sbin/sh
# ColorOS Port para Galaxy S23
# Flash via TWRP

ui_print "ColorOS Port - Galaxy S23 Series"
ui_print "Instalando..."

# Verifica dispositivo
DEVICE=$(getprop ro.product.device)
if [ "$DEVICE" != "dm1q" ] && [ "$DEVICE" != "dm2q" ] && [ "$DEVICE" != "dm3q" ]; then
    ui_print "ERRO: Dispositivo incompatível: $DEVICE"
    exit 1
fi

ui_print "Dispositivo: $DEVICE"

# Instala super.img
ui_print "Instalando super.img..."
dd if=/dev/block/bootdevice/by-name/super of=/dev/null bs=4096 count=1 2>/dev/null
dd if=super.img of=/dev/block/bootdevice/by-name/super bs=4096

ui_print "Instalação concluída!"
ui_print "Reiniciando..."
"""

        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(super_img, "super.img")
            zf.writestr("META-INF/com/google/android/update-binary", updater_script)
            zf.writestr("META-INF/com/google/android/updater-script", "")

        self.logger.info(f"  ZIP criado: {output_zip.stat().st_size // 1024 // 1024} MB")
        return output_zip

    def pack(self) -> bool:
        self.logger.info("\n[STAGE 4] Empacotando ROM...")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Verifica se as partições reais foram extraídas corretamente
        # (se estiverem vazias, o mkfs.erofs vai gerar imagens mínimas)
        empty_real = []
        for part in REAL_PARTITIONS:
            part_dir = self.target_dir / part
            if part_dir.exists():
                try:
                    next(part_dir.iterdir())
                except StopIteration:
                    empty_real.append(part)
        if empty_real:
            self.logger.warning(
                f"  ATENCAO: partições reais VAZIAS (extracao ext4 falhou): {empty_real}\n"
                f"  O super.img sera gerado mas as partições estarao em branco no dispositivo.\n"
                f"  Para corrigir, rode antes:\n"
                f"    pip install ext4\n"
                f"  Ou execute com Docker --privileged para mount loop funcionar."
            )

        imgs = []
        all_parts = REAL_PARTITIONS + OPLUS_STUB_PARTITIONS
        for part in all_parts:
            part_dir = self.target_dir / part
            # Ignora diretórios _mnt (artefatos de mount temporário)
            if part.endswith("_mnt"):
                continue
            if not part_dir.exists():
                continue
            img = self.pack_partition_erofs(part, part_dir)
            if img:
                imgs.append(img)

        if not imgs:
            self.logger.error("Nenhuma partição empacotada!")
            return False

        if self.pack_type == "super":
            super_img = self.pack_super(imgs)
            if super_img:
                self.create_flashable_zip(super_img)
        else:
            self.logger.info("  pack_type 'payload' — gerando super.img como fallback")
            self.pack_super(imgs)

        return True


# ──────────────────────────────────────────────────────────────────────────────
# DETECÇÃO AUTOMÁTICA DO DEVICE CODE DO PORT ROM
# ──────────────────────────────────────────────────────────────────────────────

def detect_port_device_code(port_dir: Path, logger: logging.Logger) -> str:
    """Detecta automaticamente o device code do ROM de port (ex: OP4E7L1)."""
    for bp in port_dir.rglob("build.prop"):
        for key in ["ro.product.device", "ro.vendor.product.device", "ro.product.vendor.device"]:
            val = read_prop(bp, key)
            if val and "oplus" not in val.lower() and len(val) > 2:
                logger.info(f"  Device code do port: {val} (de {bp.relative_to(port_dir)})")
                return val
    return "OP4E7L1"  # Fallback OnePlus 9


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ColorOS Port para Galaxy S23 (dm1q/dm2q/dm3q)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # ZIP Odin completo do SamFW/SamMobile (recomendado)
  python3 main_s23.py \
    --baserom SM-S911B_XXU8CYB4_stock.zip \
    --portrom coloros15_port.zip

  # AP_*.tar.md5 diretamente (mais rápido, sem reextração do ZIP)
  python3 main_s23.py \
    --baserom AP_S911BXXU8CYB4_CL12345_QB12345_REV00_user_low_ship.tar.md5 \
    --portrom coloros15_port.zip

  # Já tem super.img.lz4 extraído
  python3 main_s23.py --baserom super.img.lz4 --portrom coloros.zip

  # Retomando de build parcial (sem reextrair)
  python3 main_s23.py \
    --baserom ... --portrom ... \
    --skip_extract --debug
        """
    )
    parser.add_argument("--baserom",    required=True,  help="Base ROM (Evolution X / AOSP para S23)")
    parser.add_argument("--portrom",    required=True,  help="Port ROM (ColorOS zip)")
    parser.add_argument("--device",     default="dm1q",
                        choices=list(DEVICE_CONFIG.keys()),
                        help="Codename do dispositivo (default: dm1q = S23)")
    parser.add_argument("--output",     default="./build_s23", help="Diretório de output")
    parser.add_argument("--pack_type",  default="super",
                        choices=["super", "payload"],
                        help="Tipo de empacotamento final")
    parser.add_argument("--clean",      action="store_true", help="Limpa build anterior")
    parser.add_argument("--skip_extract", action="store_true",
                        help="Pula extração (usa build/ existente)")
    parser.add_argument("--debug",      action="store_true", help="Log verboso")
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
    logger.info(f"  Super size:  {device_cfg['super_size'] // 1024 // 1024 // 1024:.1f} GB")

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

    # ── Stage 1: Extração ────────────────────────────────────────────────────
    extractor = SamsungStockExtractor(build_dir, logger)

    if args.skip_extract:
        logger.info("\n[STAGE 1] Pulando extração (--skip_extract)")
        base_dir = build_dir / "base"
        port_dir = build_dir / "port"
    else:
        base_dir = extractor.prepare_base_stock(base_input)
        port_dir = extractor.prepare_port(port_input)

    # ── Detecta device code do port ──────────────────────────────────────────
    port_device_code = detect_port_device_code(port_dir, logger)

    # ── Stage 2: Merge ───────────────────────────────────────────────────────
    target_dir = build_dir / "target"
    merger = RomMerger(base_dir, port_dir, target_dir, device_cfg, logger)
    merger.merge()

    # ── Stage 3: Patches S23 ─────────────────────────────────────────────────
    patcher = S23Patcher(target_dir, device_cfg, logger)
    ok = patcher.run_all(port_device_code, base_dir)
    if not ok:
        logger.warning("Alguns patches falharam, continuando...")

    # ── Stage 4: Empacotamento ───────────────────────────────────────────────
    output_dir = build_dir / "output"
    packer = RomPacker(target_dir, output_dir, device_cfg, args.pack_type, logger)
    packer.pack()

    logger.info("\n" + "=" * 60)
    logger.info("  PORT CONCLUÍDO!")
    logger.info(f"  Output: {output_dir}")
    logger.info("=" * 60)
    logger.info("""
PRÓXIMOS PASSOS:
  1. Verifique o zip em output/
  2. Boot no TWRP (ou outro recovery compatível com dm1q)
  3. Wipe: Dalvik, Cache, System, Data (NÃO wipe Vendor!)
  4. Flash o zip gerado
  5. Reboot

ATENÇÃO — Stock Samsung como base:
  - Knox será trigado ao modificar partições (normal num port)
  - A câmera stock Samsung FUNCIONARÁ (blobs originais)
  - Modem/RIL vem da stock — sem problemas de sinal
  - Se bootloop: verifique se a versão do Android da stock
    é compatível com a do ColorOS (mesmo major version)
""")


if __name__ == "__main__":
    main()
