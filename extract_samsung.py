"""
extract_samsung.py
Extrai TODAS as partições de um firmware Samsung completo (BL + AP + CSC + HOME_CSC + CP).

Uso:
    # Passa os arquivos individualmente (qualquer ordem):
    python3 extract_samsung.py BL_*.tar.md5 AP_*.tar.md5 CSC_*.tar.md5 CP_*.tar.md5

    # Ou aponta para uma pasta com todos os arquivos:
    python3 extract_samsung.py --dir /caminho/para/firmware/

Saída:
    devices/chipset/SM8550/assets/   ← imagens de firmware (boot, modem, etc.)
    roms/base_unzip/                 ← partições lógicas extraídas (system, vendor, etc.)
                                        prontas para usar como --baserom no main.py
"""

import sys
import os
import re
import tarfile
import subprocess
import shutil
import argparse
from pathlib import Path

try:
    from lpunpack import LpUnpack
    LPUNPACK_NATIVE = True
except ImportError:
    LPUNPACK_NATIVE = False
    print("⚠️  lpunpack.py não encontrado — usará binário lpunpack do sistema como fallback.")

# ──────────────────────────────────────────────────────────────
# Mapa de conteúdo esperado por arquivo de firmware Samsung
# ──────────────────────────────────────────────────────────────

# Partições lógicas dentro do super.img (A/B — sufixo _a)
LOGICAL_PARTITIONS = [
    "system", "system_ext", "product", "vendor",
    "odm", "vendor_dlkm", "odm_dlkm", "system_dlkm",
    # Partições Oplus/ColorOS (presentes em ports)
    "my_product", "my_engineering", "my_company",
    "my_carrier", "my_region", "my_heytap",
    "my_stock", "my_preload", "my_bigball", "my_manifest",
]

# Partições de firmware direto (fora do super) presentes no AP
AP_DIRECT_IMAGES = [
    "boot.img",
    "init_boot.img",
    "vendor_boot.img",
    "dtbo.img",
    "vbmeta.img",
    "vbmeta_system.img",
    "vbmeta_vendor.img",
    "super.img",          # extraído por último, pois é grande
]

# Extensões que podem ser comprimidas em LZ4
LZ4_EXTS = {".lz4"}

# Partições de modem/baseband (CP)
CP_IMAGES = [
    "NON-HLOS.bin",       # modem firmware principal
    "modem.img",
    "modem_debug.img",
]

# Partições de bootloader (BL)
BL_IMAGES = [
    "abl.elf",
    "xbl.elf",
    "xbl_config.elf",
    "tz.mbn",
    "hyp.mbn",
    "keymaster.mbn",
    "devcfg.mbn",
    "rpm.mbn",
    "sbl1.mbn",
    "BTFM.bin",
    "km4.mbn",
    "uefi.elf",
]

# Partições de CSC (carrier/regional config)
CSC_IMAGES = [
    "odm.img",
    "csc.img",
    "omr.img",
]


# ──────────────────────────────────────────────────────────────
# Utilitários
# ──────────────────────────────────────────────────────────────

def log(msg: str):
    print(msg, flush=True)

def run(cmd: list, desc: str, check: bool = True) -> bool:
    log(f"  ⏳ {desc}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and check:
        log(f"  ❌ Falhou: {' '.join(str(c) for c in cmd)}")
        if result.stderr:
            log(f"     {result.stderr.strip()[:300]}")
        return False
    return True

def decompress_lz4(src: Path, dst: Path) -> bool:
    """Descomprime um arquivo .lz4 para dst."""
    log(f"  ⚡ Descomprimindo {src.name} → {dst.name}")
    ok = run(["lz4", "-d", "-f", str(src), str(dst)],
             f"lz4 -d {src.name}", check=False)
    if not ok:
        # Tenta com python-lz4 como fallback
        try:
            import lz4.frame
            with open(src, "rb") as f_in, open(dst, "wb") as f_out:
                f_out.write(lz4.frame.decompress(f_in.read()))
            log(f"  ✅ Descomprimido via python-lz4")
            return True
        except Exception as e:
            log(f"  ❌ Falha no fallback python-lz4: {e}")
            return False
    return True

def normalize_name(name: str) -> str:
    """Remove sufixo .lz4 e retorna o nome base."""
    return name.removesuffix(".lz4").removesuffix(".md5")

def detect_firmware_type(tar_path: Path) -> str:
    """
    Detecta o tipo do arquivo de firmware pelo nome.
    Retorna: 'AP', 'BL', 'CSC', 'HOME_CSC', 'CP', 'UNKNOWN'
    """
    name = tar_path.name.upper()
    if name.startswith("AP_"):
        return "AP"
    if name.startswith("BL_"):
        return "BL"
    if name.startswith("HOME_CSC_") or name.startswith("HOME-CSC"):
        return "HOME_CSC"
    if name.startswith("CSC_"):
        return "CSC"
    if name.startswith("CP_"):
        return "CP"
    return "UNKNOWN"

def list_tar_contents(tar_path: Path) -> list[str]:
    """Lista todos os arquivos dentro de um TAR sem extrair."""
    try:
        with tarfile.open(str(tar_path), "r:*") as tf:
            return [m.name for m in tf.getmembers() if m.isfile()]
    except Exception as e:
        log(f"  ⚠️  Não foi possível listar {tar_path.name}: {e}")
        return []

def extract_from_tar(tar_path: Path, files: list[str], dest_dir: Path) -> list[Path]:
    """
    Extrai arquivos específicos (ou todos se files=[]) de um TAR para dest_dir.
    Retorna lista dos arquivos extraídos.
    """
    extracted = []
    try:
        with tarfile.open(str(tar_path), "r:*") as tf:
            members = tf.getmembers()
            if files:
                # Filtra apenas os membros desejados
                to_extract = [
                    m for m in members
                    if any(
                        m.name == f or m.name.endswith("/" + f)
                        or normalize_name(m.name) == f
                        or normalize_name(m.name).endswith("/" + f)
                        for f in files
                    )
                ]
            else:
                to_extract = [m for m in members if m.isfile()]

            for member in to_extract:
                # Extrai mantendo só o basename (sem subpastas do TAR)
                member_copy = tarfile.TarInfo(name=Path(member.name).name)
                member_copy.size = member.size
                member_copy.mode = member.mode
                src_f = tf.extractfile(member)
                if src_f is None:
                    continue
                out_path = dest_dir / Path(member.name).name
                with open(out_path, "wb") as f_out:
                    shutil.copyfileobj(src_f, f_out)
                extracted.append(out_path)
                log(f"  📄 Extraído: {out_path.name}")

    except Exception as e:
        log(f"  ❌ Erro ao extrair de {tar_path.name}: {e}")

    return extracted

def extract_all_from_tar(tar_path: Path, dest_dir: Path) -> list[Path]:
    """Extrai TODOS os arquivos de um TAR para dest_dir."""
    return extract_from_tar(tar_path, [], dest_dir)

def unpack_super(super_img: Path, out_dir: Path) -> list[Path]:
    """
    Extrai partições lógicas do super.img.
    Tenta LpUnpack nativo primeiro, depois binário lpunpack do sistema.
    """
    log(f"  🔪 Desempacotando super.img ({super_img.stat().st_size // 1024 // 1024} MB)...")
    out_dir.mkdir(parents=True, exist_ok=True)

    if LPUNPACK_NATIVE:
        try:
            unpacker = LpUnpack(
                SUPER_IMAGE=str(super_img),
                OUTPUT_DIR=str(out_dir),
                SHOW_INFO=False,
            )
            unpacker.unpack()
            log("  ✅ LpUnpack nativo concluído.")
        except Exception as e:
            log(f"  ⚠️  LpUnpack nativo falhou ({e}), tentando binário...")
            _lpunpack_binary(super_img, out_dir)
    else:
        _lpunpack_binary(super_img, out_dir)

    # Coleta tudo que foi gerado
    return list(out_dir.glob("*.img"))

def _lpunpack_binary(super_img: Path, out_dir: Path):
    """Fallback: usa binário lpunpack instalado no sistema."""
    lpunpack_bin = shutil.which("lpunpack")
    if not lpunpack_bin:
        # Tenta no diretório bin/ do projeto
        for candidate in [
            Path("bin/linux/x86_64/lpunpack"),
            Path("bin/lpunpack"),
        ]:
            if candidate.exists():
                lpunpack_bin = str(candidate)
                break

    if not lpunpack_bin:
        log("  ❌ lpunpack não encontrado nem no PATH nem em bin/. Instale com: apt install android-tools-mkbootimg")
        return

    run([lpunpack_bin, str(super_img), str(out_dir)],
        "lpunpack super.img", check=False)


def handle_sparse_image(img_path: Path) -> Path:
    """
    Converte imagem sparse (simg) para raw se necessário.
    Retorna o path da imagem raw.
    """
    # Verifica magic de sparse image: 0xed26ff3a
    try:
        with open(img_path, "rb") as f:
            magic = f.read(4)
        if magic == b"\x3a\xff\x26\xed":
            raw_path = img_path.with_suffix(".raw.img")
            log(f"  🔄 Convertendo sparse → raw: {img_path.name}")
            simg2img = shutil.which("simg2img") or "bin/linux/x86_64/simg2img"
            ok = run([simg2img, str(img_path), str(raw_path)],
                     f"simg2img {img_path.name}", check=False)
            if ok and raw_path.exists():
                img_path.unlink()
                raw_path.rename(img_path)
    except Exception:
        pass
    return img_path


# ──────────────────────────────────────────────────────────────
# Processadores por tipo de firmware
# ──────────────────────────────────────────────────────────────

def process_ap(tar_path: Path, temp_dir: Path, assets_dir: Path, logical_out: Path):
    """
    AP: contém boot, init_boot, vendor_boot, dtbo, vbmeta*, super.img
    O super.img é desempacotado em logical_out (roms/base_unzip).
    """
    log(f"\n{'─'*55}")
    log(f"📦 AP: {tar_path.name}")
    log(f"{'─'*55}")

    # Lista o conteúdo do TAR para descobrir o que tem
    contents = list_tar_contents(tar_path)
    log(f"  📋 {len(contents)} arquivo(s) encontrado(s) no TAR")

    ap_temp = temp_dir / "ap"
    ap_temp.mkdir(exist_ok=True)

    # Extrai TUDO do AP
    extracted = extract_all_from_tar(tar_path, ap_temp)

    # Descomprime LZ4
    for f in list(ap_temp.glob("*.lz4")):
        raw_name = f.name.removesuffix(".lz4")
        dst = ap_temp / raw_name
        if decompress_lz4(f, dst):
            f.unlink()

    # Move imagens de firmware direto para assets
    for img_name in AP_DIRECT_IMAGES:
        if img_name == "super.img":
            continue  # processado separadamente
        src = ap_temp / img_name
        if src.exists():
            handle_sparse_image(src)
            shutil.move(str(src), str(assets_dir / img_name))
            log(f"  ✅ Firmware → assets: {img_name}")

    # Processa super.img
    super_img = ap_temp / "super.img"
    if super_img.exists():
        handle_sparse_image(super_img)
        log(f"\n  🗜️  Extraindo partições lógicas do super.img...")
        logical_imgs = unpack_super(super_img, logical_out / "images")

        # Normaliza sufixos _a/_b → sem sufixo
        _normalize_ab_suffixes(logical_out / "images")

        log(f"\n  📂 Partições lógicas extraídas ({len(logical_imgs)}):")
        for img in sorted((logical_out / "images").glob("*.img")):
            log(f"     • {img.name}")

        super_img.unlink()
    else:
        log("  ⚠️  super.img não encontrado no AP!")

    # Move qualquer .img restante para assets (dtbo, vbmeta etc. que não foram listados)
    for leftover in ap_temp.glob("*.img"):
        dst = assets_dir / leftover.name
        if not dst.exists():
            shutil.move(str(leftover), str(dst))
            log(f"  📁 Extra → assets: {leftover.name}")

    shutil.rmtree(ap_temp, ignore_errors=True)


def process_bl(tar_path: Path, assets_dir: Path):
    """
    BL: bootloader — abl, xbl, tz, hyp, keymaster, devcfg, rpm, etc.
    """
    log(f"\n{'─'*55}")
    log(f"🔒 BL: {tar_path.name}")
    log(f"{'─'*55}")

    bl_temp = assets_dir.parent / "temp_bl"
    bl_temp.mkdir(exist_ok=True)

    extracted = extract_all_from_tar(tar_path, bl_temp)

    # Descomprime LZ4 se houver
    for f in list(bl_temp.glob("*.lz4")):
        dst = bl_temp / f.name.removesuffix(".lz4")
        if decompress_lz4(f, dst):
            f.unlink()

    # Move tudo para firmware-update dentro de assets
    fw_dir = assets_dir / "firmware-update"
    fw_dir.mkdir(exist_ok=True)
    moved = 0
    for f in bl_temp.iterdir():
        if f.is_file():
            shutil.move(str(f), str(fw_dir / f.name))
            moved += 1

    log(f"  ✅ {moved} arquivo(s) de bootloader → assets/firmware-update/")
    shutil.rmtree(bl_temp, ignore_errors=True)


def process_cp(tar_path: Path, assets_dir: Path):
    """
    CP: modem/baseband — NON-HLOS.bin, modem.img, etc.
    """
    log(f"\n{'─'*55}")
    log(f"📡 CP (Modem): {tar_path.name}")
    log(f"{'─'*55}")

    cp_temp = assets_dir.parent / "temp_cp"
    cp_temp.mkdir(exist_ok=True)

    extracted = extract_all_from_tar(tar_path, cp_temp)

    for f in list(cp_temp.glob("*.lz4")):
        dst = cp_temp / f.name.removesuffix(".lz4")
        if decompress_lz4(f, dst):
            f.unlink()

    fw_dir = assets_dir / "firmware-update"
    fw_dir.mkdir(exist_ok=True)
    moved = 0
    for f in cp_temp.iterdir():
        if f.is_file():
            shutil.move(str(f), str(fw_dir / f.name))
            moved += 1

    log(f"  ✅ {moved} arquivo(s) de modem → assets/firmware-update/")
    shutil.rmtree(cp_temp, ignore_errors=True)


def process_csc(tar_path: Path, assets_dir: Path, logical_out: Path, fw_type: str):
    """
    CSC / HOME_CSC: configurações regionais, odm do operador, omr.
    HOME_CSC é preferível pois não reseta o device durante o flash.
    """
    label = "🌍 HOME_CSC" if fw_type == "HOME_CSC" else "🌍 CSC"
    log(f"\n{'─'*55}")
    log(f"{label}: {tar_path.name}")
    log(f"{'─'*55}")

    csc_temp = assets_dir.parent / "temp_csc"
    csc_temp.mkdir(exist_ok=True)

    extracted = extract_all_from_tar(tar_path, csc_temp)

    for f in list(csc_temp.glob("*.lz4")):
        dst = csc_temp / f.name.removesuffix(".lz4")
        if decompress_lz4(f, dst):
            f.unlink()

    moved_assets = 0
    moved_logical = 0

    for f in csc_temp.iterdir():
        if not f.is_file():
            continue

        name_lower = f.name.lower()

        # odm.img do CSC vai para imagens lógicas (substitui o do AP se existir)
        if name_lower in ("odm.img", "csc.img", "omr.img"):
            handle_sparse_image(f)
            dst = logical_out / "images" / f.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dst))
            log(f"  📂 Lógica CSC → base_unzip/images: {f.name}")
            moved_logical += 1
        else:
            # Resto vai para firmware-update
            fw_dir = assets_dir / "firmware-update"
            fw_dir.mkdir(exist_ok=True)
            shutil.move(str(f), str(fw_dir / f.name))
            moved_assets += 1

    log(f"  ✅ {moved_logical} imagem(ns) lógica(s), {moved_assets} firmware(s) de CSC processados.")
    shutil.rmtree(csc_temp, ignore_errors=True)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _normalize_ab_suffixes(images_dir: Path):
    """
    Renomeia system_a.img → system.img, vendor_b.img → ignora, etc.
    Mantém apenas as partições _a (slot A) e remove o sufixo.
    """
    for img in list(images_dir.glob("*_a.img")):
        new_name = img.name.replace("_a.img", ".img")
        new_path = images_dir / new_name
        if not new_path.exists():
            img.rename(new_path)

    # Remove slot B se existir
    for img in list(images_dir.glob("*_b.img")):
        img.unlink()
        log(f"  🗑️  Removido slot B: {img.name}")


def setup_base_unzip_structure(logical_out: Path):
    """
    Cria a estrutura de diretórios esperada pelo main.py como --baserom.
    roms/base_unzip/
        images/          ← .img files (extraídos do super)
        extracted/       ← criado pelo RomPackage ao extrair
        source_file.hash ← hash de bypass para LOCAL_DIR mode
    """
    (logical_out / "images").mkdir(parents=True, exist_ok=True)
    (logical_out / "extracted").mkdir(exist_ok=True)

    # Hash bypass para modo LOCAL_DIR (evita re-extração)
    hash_file = logical_out / "source_file.hash"
    if not hash_file.exists():
        hash_file.write_text("local_directory_hash_bypass")


def print_summary(assets_dir: Path, logical_out: Path):
    """Exibe resumo final do que foi extraído."""
    log(f"\n{'═'*55}")
    log("📊 RESUMO DA EXTRAÇÃO")
    log(f"{'═'*55}")

    fw_dir = assets_dir / "firmware-update"
    images_dir = logical_out / "images"

    if fw_dir.exists():
        fw_files = list(fw_dir.iterdir())
        log(f"\n🔒 Firmware (bootloader + modem): {len(fw_files)} arquivo(s)")
        for f in sorted(fw_files):
            size_mb = f.stat().st_size / 1024 / 1024
            log(f"   • {f.name:<35} {size_mb:6.1f} MB")

    direct_imgs = [f for f in assets_dir.glob("*.img")]
    if direct_imgs:
        log(f"\n💾 Imagens diretas (boot, dtbo, vbmeta): {len(direct_imgs)} arquivo(s)")
        for f in sorted(direct_imgs):
            size_mb = f.stat().st_size / 1024 / 1024
            log(f"   • {f.name:<35} {size_mb:6.1f} MB")

    if images_dir.exists():
        logical_imgs = list(images_dir.glob("*.img"))
        log(f"\n📂 Partições lógicas (base_unzip/images): {len(logical_imgs)} partição(ões)")
        for f in sorted(logical_imgs):
            size_mb = f.stat().st_size / 1024 / 1024
            log(f"   • {f.name:<35} {size_mb:6.1f} MB")

    log(f"\n{'═'*55}")
    log("✅ EXTRAÇÃO CONCLUÍDA!")
    log(f"{'═'*55}")
    log(f"\n▶  Para usar como base ROM no porting:")
    log(f"   python main.py \\")
    log(f"     --baserom {logical_out} \\")
    log(f"     --portrom  /caminho/coloros_port.zip \\")
    log(f"     --device_code dm1q \\")
    log(f"     --pack_type payload")


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extrai firmware Samsung completo (BL + AP + CSC + CP → partições prontas)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Arquivos individuais (qualquer ordem):
  python3 extract_samsung.py BL_S911B*.tar.md5 AP_S911B*.tar.md5 CSC_*.tar.md5 CP_*.tar.md5

  # Pasta com todos os arquivos:
  python3 extract_samsung.py --dir /home/user/S23_firmware/

  # Só AP (extrai partições lógicas):
  python3 extract_samsung.py AP_S911BXXU5CXB1*.tar.md5
        """
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Arquivos .tar.md5 do firmware (BL, AP, CSC, HOME_CSC, CP)"
    )
    parser.add_argument(
        "--dir",
        help="Pasta contendo todos os arquivos de firmware",
        type=Path
    )
    parser.add_argument(
        "--assets",
        default="devices/chipset/SM8550/assets",
        help="Pasta de saída para firmware (default: devices/chipset/SM8550/assets)"
    )
    parser.add_argument(
        "--output",
        default="roms/base_unzip",
        help="Pasta de saída para partições lógicas (default: roms/base_unzip)"
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Não apaga arquivos temporários após extração"
    )

    args = parser.parse_args()

    # Coleta arquivos de firmware
    firmware_files: list[Path] = []

    if args.dir:
        d = Path(args.dir)
        if not d.is_dir():
            log(f"❌ Pasta não encontrada: {d}")
            sys.exit(1)
        firmware_files = sorted(d.glob("*.tar.md5")) + sorted(d.glob("*.tar"))
        if not firmware_files:
            log(f"❌ Nenhum arquivo .tar.md5 encontrado em {d}")
            sys.exit(1)

    for f in args.files:
        p = Path(f)
        if not p.exists():
            log(f"⚠️  Arquivo não encontrado: {f}")
            continue
        firmware_files.append(p)

    if not firmware_files:
        parser.print_help()
        sys.exit(1)

    # Diretórios de saída
    assets_dir = Path(args.assets)
    logical_out = Path(args.output)
    temp_dir = Path("temp_samsung_extract")

    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "firmware-update").mkdir(exist_ok=True)
    setup_base_unzip_structure(logical_out)
    temp_dir.mkdir(exist_ok=True)

    log("=" * 55)
    log("🚀 Samsung Firmware Extractor — dm1q (Galaxy S23)")
    log("=" * 55)
    log(f"   Firmware files : {len(firmware_files)}")
    log(f"   Assets dir     : {assets_dir}")
    log(f"   Base ROM dir   : {logical_out}")
    log("")

    # Classifica e processa cada arquivo
    # Ordem: BL → CP → CSC/HOME_CSC → AP (AP por último pois é o maior)
    order = {"BL": 0, "CP": 1, "CSC": 2, "HOME_CSC": 3, "AP": 4, "UNKNOWN": 5}
    firmware_files.sort(key=lambda p: order.get(detect_firmware_type(p), 5))

    has_home_csc = any(detect_firmware_type(p) == "HOME_CSC" for p in firmware_files)

    for fw_file in firmware_files:
        fw_type = detect_firmware_type(fw_file)

        # Se temos HOME_CSC, pula o CSC normal (HOME_CSC é preferível)
        if fw_type == "CSC" and has_home_csc:
            log(f"\n⏭️  Pulando {fw_file.name} (HOME_CSC disponível, preferível)")
            continue

        if fw_type == "AP":
            process_ap(fw_file, temp_dir, assets_dir, logical_out)
        elif fw_type == "BL":
            process_bl(fw_file, assets_dir)
        elif fw_type == "CP":
            process_cp(fw_file, assets_dir)
        elif fw_type in ("CSC", "HOME_CSC"):
            process_csc(fw_file, assets_dir, logical_out, fw_type)
        else:
            log(f"\n⚠️  Tipo desconhecido: {fw_file.name} — tentando extração genérica...")
            generic_out = assets_dir / "firmware-update"
            extract_all_from_tar(fw_file, generic_out)

    # Limpeza
    if not args.keep_temp:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print_summary(assets_dir, logical_out)


if __name__ == "__main__":
    main()
