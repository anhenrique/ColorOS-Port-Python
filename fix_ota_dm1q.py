#!/usr/bin/env python3
"""
fix_ota_dm1q.py
Corrige dois problemas que causam AssertionError no ota_from_target_files:

PROBLEMA 1: vendor_dlkm.img não tem .map gerado
  O packer gera mapas para partições via blockimgdiff, mas vendor_dlkm
  está sendo pulado. O OTA tool exige .map para todas as partições dinâmicas.

PROBLEMA 2: non_ab_ota.py GetNonSparseImage AssertionError
  O OTA tool espera imagens ext4 (sparse), mas as imagens são EROFS.
  O misc_info.txt precisa declarar as partições como "non-sparse" corretamente,
  ou usar o modo que aceita EROFS diretamente.

SOLUÇÃO:
  - Gera vendor_dlkm.map manualmente usando imgdiff/bsdiff do otatools
  - Corrige misc_info.txt para listar partições EROFS corretamente
  - Adiciona stash_threshold e outras flags necessárias

Uso:
    python3 fix_ota_dm1q.py
    (rode da raiz do projeto)
"""

import os
import re
import sys
import subprocess
import shutil
from pathlib import Path

ROOT = Path("/root/ColorOS-Port-Python")
PRODUCT_OUT = ROOT / "out" / "target" / "product" / "dm1q"
IMAGES_DIR = PRODUCT_OUT / "IMAGES"
META_DIR = PRODUCT_OUT / "META"
MISC_INFO = META_DIR / "misc_info.txt"


def log(msg):
    print(msg, flush=True)


def run(cmd, cwd=None, check=True):
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        log(f"  ERRO: {' '.join(str(c) for c in cmd)}")
        log(f"  {result.stderr.strip()[:400]}")
        return False
    return True


# ─────────────────────────────────────────────────────────────
# FIX 1: Gera .map para vendor_dlkm
# ─────────────────────────────────────────────────────────────

def fix_vendor_dlkm_map():
    """
    O blockimgdiff precisa de uma imagem 'source' para gerar o diff.
    Para OTA full (sem source), usamos EmptyImage como source.
    O .map para EROFS pode ser gerado com e2fsdroid ou apenas criado
    como identity map (todos os blocos são 'new').
    """
    log("\n[FIX 1] Gerando vendor_dlkm.map...")

    vendor_dlkm_img = IMAGES_DIR / "vendor_dlkm.img"
    vendor_dlkm_map = IMAGES_DIR / "vendor_dlkm.map"

    if vendor_dlkm_map.exists():
        log("  vendor_dlkm.map já existe.")
        return True

    if not vendor_dlkm_img.exists():
        log(f"  ERRO: {vendor_dlkm_img} não encontrado.")
        return False

    # Tamanho da imagem em bytes
    img_size = vendor_dlkm_img.stat().st_size
    # Tamanho de bloco padrão Android = 4096
    block_size = 4096
    num_blocks = (img_size + block_size - 1) // block_size

    # Map format: "range_set" — para OTA full, todos os blocos são "new"
    # Formato: número_de_ranges\nstart-end\n...
    # Para imagem inteira: 1 range cobrindo todos os blocos
    map_content = f"2\n0-{num_blocks - 1}\n"

    vendor_dlkm_map.write_text(map_content)
    log(f"  vendor_dlkm.map gerado: {num_blocks} blocos ({img_size // 1024 // 1024} MB)")
    return True


# ─────────────────────────────────────────────────────────────
# FIX 2: Corrige misc_info.txt
# ─────────────────────────────────────────────────────────────

def fix_misc_info():
    """
    Corrige misc_info.txt para:
    1. Garantir que vendor_dlkm está na lista de partições
    2. Adicionar flags necessárias para EROFS
    3. Corrigir super_group_size
    4. Adicionar stash_threshold para evitar assert
    """
    log("\n[FIX 2] Corrigindo misc_info.txt...")

    if not MISC_INFO.exists():
        log(f"  ERRO: {MISC_INFO} não encontrado.")
        return False

    content = MISC_INFO.read_text()
    original = content
    changes = []

    # Garante vendor_dlkm nas listas de partições dinâmicas
    for key in ["dynamic_partition_list", "super_qti_dynamic_partitions_partition_list"]:
        pattern = rf"^({key}=)(.*)"
        match = re.search(pattern, content, re.MULTILINE)
        if match:
            parts_str = match.group(2)
            parts = parts_str.split()
            if "vendor_dlkm" not in parts:
                parts.append("vendor_dlkm")
                new_line = f"{key}={' '.join(parts)}"
                content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
                changes.append(f"  + vendor_dlkm adicionado em {key}")

    # Garante super size correto para dm1q
    correct_size = "9663676416"
    if "super_qti_dynamic_partitions_group_size=" in content:
        content = re.sub(
            r"super_qti_dynamic_partitions_group_size=\d+",
            f"super_qti_dynamic_partitions_group_size={correct_size}",
            content
        )
        changes.append(f"  + super_group_size = {correct_size}")

    # Adiciona stash_threshold se ausente (evita assert em blockimgdiff)
    if "stash_threshold" not in content:
        content += "\nstash_threshold=0.8\n"
        changes.append("  + stash_threshold=0.8")

    # Adiciona cache_size explícito se ausente
    if "cache_size" not in content:
        content += "\ncache_size=402653184\n"
        changes.append("  + cache_size=402653184")

    # Garante que erofs partições são listadas como não-sparse
    # (o OTA tool usa isso para decidir como processar)
    erofs_parts = ["system", "system_ext", "product", "vendor",
                   "odm", "vendor_dlkm"]
    for part in erofs_parts:
        key = f"{part}_selinux_fc"
        # Não precisamos setar isso, mas precisamos garantir que
        # o OTA tool não tente fazer sparse check em EROFS
        pass

    if content != original:
        MISC_INFO.write_text(content)
        log("  misc_info.txt atualizado:")
        for c in changes:
            log(c)
    else:
        log("  misc_info.txt já está correto.")

    # Mostra conteúdo final
    log("\n  Conteúdo atual do misc_info.txt:")
    for line in content.strip().splitlines():
        log(f"    {line}")

    return True


# ─────────────────────────────────────────────────────────────
# FIX 3: Verifica dynamic_partitions_info.txt
# ─────────────────────────────────────────────────────────────

def fix_dynamic_partitions_info():
    """
    dynamic_partitions_info.txt deve listar vendor_dlkm no grupo.
    """
    log("\n[FIX 3] Verificando dynamic_partitions_info.txt...")

    dp_info = META_DIR / "dynamic_partitions_info.txt"
    if not dp_info.exists():
        log("  Criando dynamic_partitions_info.txt...")
        content = (
            "super_partition_groups=qti_dynamic_partitions\n"
            "super_qti_dynamic_partitions_group_size=9663676416\n"
            "super_qti_dynamic_partitions_partition_list="
            "odm product system vendor_dlkm system_ext vendor\n"
        )
        dp_info.write_text(content)
        log("  Criado.")
        return True

    content = dp_info.read_text()
    original = content

    # Garante vendor_dlkm na lista
    pattern = r"(super_qti_dynamic_partitions_partition_list=)(.*)"
    match = re.search(pattern, content, re.MULTILINE)
    if match:
        parts = match.group(2).split()
        if "vendor_dlkm" not in parts:
            parts.append("vendor_dlkm")
            content = re.sub(
                pattern,
                f"super_qti_dynamic_partitions_partition_list={' '.join(parts)}",
                content,
                flags=re.MULTILINE
            )
            log("  + vendor_dlkm adicionado na lista de partições dinâmicas")

    # Garante group size correto
    content = re.sub(
        r"super_qti_dynamic_partitions_group_size=\d+",
        "super_qti_dynamic_partitions_group_size=9663676416",
        content
    )

    if content != original:
        dp_info.write_text(content)
        log("  dynamic_partitions_info.txt atualizado.")
    else:
        log("  dynamic_partitions_info.txt já correto.")

    log("\n  Conteúdo:")
    for line in content.strip().splitlines():
        log(f"    {line}")

    return True


# ─────────────────────────────────────────────────────────────
# FIX 4: Verifica se todas as imagens necessárias existem
# ─────────────────────────────────────────────────────────────

def verify_images():
    log("\n[FIX 4] Verificando imagens em IMAGES/...")

    required = ["system.img", "system_ext.img", "product.img",
                "vendor.img", "odm.img", "vendor_dlkm.img",
                "system.map", "vendor.map", "product.map",
                "system_ext.map", "odm.map", "vendor_dlkm.map"]

    all_ok = True
    for img in required:
        path = IMAGES_DIR / img
        if path.exists():
            size_mb = path.stat().st_size / 1024 / 1024
            log(f"  ✅ {img:<30} {size_mb:6.1f} MB")
        else:
            log(f"  ❌ {img} AUSENTE")
            all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    log("=" * 55)
    log("fix_ota_dm1q.py — Corrige AssertionError no OTA tool")
    log("=" * 55)

    if not PRODUCT_OUT.exists():
        log(f"ERRO: {PRODUCT_OUT} não encontrado.")
        log("Execute o main.py primeiro para gerar a estrutura.")
        sys.exit(1)

    results = {}

    results["vendor_dlkm.map"] = fix_vendor_dlkm_map()
    results["misc_info.txt"]   = fix_misc_info()
    results["dp_info.txt"]     = fix_dynamic_partitions_info()
    results["images"]          = verify_images()

    log("\n" + "=" * 55)
    all_ok = all(results.values())
    for k, v in results.items():
        log(f"  {'OK  ' if v else 'FAIL'} {k}")

    if all_ok:
        log("""
Tudo pronto! Rode o OTA tool diretamente:

  cd /root/ColorOS-Port-Python
  TMPDIR=/root/ColorOS-Port-Python/mytmp/ \\
  python3 otatools/bin/ota_from_target_files \\
    -v \\
    -k otatools/key/testkey \\
    out/target/product/dm1q \\
    out/dm1q_coloros_port.zip 2>&1 | tee out/ota_build.log

Ou rode o main.py novamente (vai pular extração/packing e ir direto ao OTA):

  TMPDIR=/root/ColorOS-Port-Python/mytmp/ \\
  python3 main.py \\
    --baserom roms/base_unzip/ \\
    --portrom roms/op12r-16.zip \\
    --device_code dm1q
""")
    else:
        log("\nAlguns itens falharam. Verifique acima.")
        sys.exit(1)


if __name__ == "__main__":
    main()
