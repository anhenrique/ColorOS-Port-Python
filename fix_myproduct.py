#!/usr/bin/env python3
"""
fix_myproduct.py
Remove/corrige todas as referências a my_product para base Samsung (Evolution X).

A Samsung não tem my_product — apenas product.
my_product é uma partição exclusiva de ROMs Oplus/ColorOS (OnePlus, OPPO, Realme).

Ao usar Evolution X como base, my_product não existe e não deve ser:
  - listada em possible_super_list
  - listada em partition_to_port
  - listada em baserom_partitions
  - criada como stub pelo módulo de compat
  - empacotada pelo packer

Este script corrige:
  [1] devices/common/port_config.json  — remove my_* das listas base
  [2] src/modules/dm1q_aosp_compat.py  — remove criação de stub my_product
  [3] src/core/props.py                — não tenta reconstruir my_product props
  [4] devices/target/dm1q/port_config.json — garante que está correto

Uso:
    python3 fix_myproduct.py        # roda da raiz do projeto
"""

import json
import re
import sys
import shutil
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("fix-myproduct")

ROOT = Path(".").resolve()

# Partições Oplus que NÃO existem em base Samsung/AOSP
OPLUS_ONLY_PARTS = [
    "my_product", "my_engineering", "my_company", "my_carrier",
    "my_region", "my_heytap", "my_stock", "my_preload",
    "my_bigball", "my_manifest",
]


def bak(p: Path):
    b = p.with_suffix(p.suffix + ".bak_mp")
    if not b.exists():
        shutil.copy2(p, b)
        log.info(f"  Backup: {b.name}")


# ─────────────────────────────────────────────────────────────
# FIX 1: devices/common/port_config.json
# Remove my_* de possible_super_list e partition_to_port
# ─────────────────────────────────────────────────────────────

def fix_common_port_config() -> bool:
    cfg_path = ROOT / "devices" / "common" / "port_config.json"
    if not cfg_path.exists():
        log.warning(f"  Não encontrado: {cfg_path} — pulando.")
        return True

    with open(cfg_path) as f:
        data = json.load(f)

    changed = False

    for key in ["possible_super_list", "partition_to_port", "baserom_partitions",
                "reusabe_partition_list", "reusable_partition_list"]:
        if key in data:
            original = data[key]
            filtered = [p for p in original if p not in OPLUS_ONLY_PARTS]
            if filtered != original:
                removed = [p for p in original if p in OPLUS_ONLY_PARTS]
                log.info(f"  common/{key}: removido {removed}")
                data[key] = filtered
                changed = True

    if changed:
        bak(cfg_path)
        with open(cfg_path, "w") as f:
            json.dump(data, f, indent=4)
        log.info("  devices/common/port_config.json: ✓ atualizado")
    else:
        log.info("  devices/common/port_config.json: já correto")

    return True


# ─────────────────────────────────────────────────────────────
# FIX 2: devices/target/dm1q/port_config.json
# Garante que my_* não aparece e que possible_super_list está correto
# ─────────────────────────────────────────────────────────────

def fix_dm1q_port_config() -> bool:
    cfg_path = ROOT / "devices" / "target" / "dm1q" / "port_config.json"
    if not cfg_path.exists():
        log.warning(f"  Não encontrado: {cfg_path}")
        return True

    with open(cfg_path) as f:
        data = json.load(f)

    changed = False
    for key in ["possible_super_list", "partition_to_port", "baserom_partitions",
                "reusabe_partition_list", "reusable_partition_list"]:
        if key in data:
            original = data[key]
            filtered = [p for p in original if p not in OPLUS_ONLY_PARTS]
            if filtered != original:
                data[key] = filtered
                changed = True
                log.info(f"  dm1q/{key}: removidas partições oplus")

    # Garante possible_super_list correto para S23
    correct_super = ["system", "system_ext", "product", "vendor", "odm", "vendor_dlkm"]
    if data.get("possible_super_list") != correct_super:
        data["possible_super_list"] = correct_super
        changed = True
        log.info(f"  dm1q/possible_super_list: definido para {correct_super}")

    if changed:
        bak(cfg_path)
        with open(cfg_path, "w") as f:
            json.dump(data, f, indent=4)
        log.info("  devices/target/dm1q/port_config.json: ✓ atualizado")
    else:
        log.info("  devices/target/dm1q/port_config.json: já correto")

    return True


# ─────────────────────────────────────────────────────────────
# FIX 3: src/modules/dm1q_aosp_compat.py
# Remove stub de my_product e _generate_fs_config_for_stubs
# A Samsung não precisa de nenhum dos dois
# ─────────────────────────────────────────────────────────────

def fix_compat_module() -> bool:
    mod_path = ROOT / "src" / "modules" / "dm1q_aosp_compat.py"
    if not mod_path.exists():
        log.warning(f"  Módulo não encontrado: {mod_path}")
        return True

    src = mod_path.read_text(encoding="utf-8")

    # Verifica se ainda tem referência a stub de my_product
    if "_create_stub_my_product" not in src and "_generate_fs_config_for_stubs" not in src:
        log.info("  dm1q_aosp_compat.py: já sem stub de my_product")
        return True

    bak(mod_path)

    # Substitui o método _create_stub_my_product por versão que não faz nada
    # (mantém a assinatura para não quebrar chamadas existentes no run())
    new_stub = '''    def _create_stub_my_product(self, target_dir: Path) -> bool:
        """
        CORRIGIDO: Samsung/Evolution X usa 'product', nao 'my_product'.
        my_product e particao exclusiva de ROMs Oplus (OnePlus, OPPO, Realme).
        Este metodo foi desativado — nao cria mais nenhum stub.
        """
        my_product_dir = target_dir / "my_product"
        if my_product_dir.exists():
            logger.info(
                "my_product encontrado (veio da ColorOS como portrom). "
                "Nao sera empacotado — base Samsung usa apenas 'product'."
            )
        return True

    def _generate_fs_config_for_stubs(self, target_dir: Path) -> bool:
        """
        CORRIGIDO: Samsung nao tem my_product.
        fs_config nao e necessario para particoes que nao serao empacotadas.
        """
        return True

'''

    # Substitui ambos os métodos usando regex
    pattern = re.compile(
        r"( {4}def _create_stub_my_product\(self.*?)(?=\n {4}def |\Z)",
        re.DOTALL
    )
    if pattern.search(src):
        src = pattern.sub(new_stub, src, count=1)
        log.info("  _create_stub_my_product: desativado")
    else:
        # Append se não achou
        src = src.rstrip() + "\n\n" + new_stub
        log.info("  _create_stub_my_product: adicionado como no-op")

    # Remove _generate_fs_config_for_stubs se existir separadamente
    pattern2 = re.compile(
        r"\n {4}def _generate_fs_config_for_stubs\(self[^)]*\).*?(?=\n {4}def |\Z)",
        re.DOTALL
    )
    if pattern2.search(src):
        src = pattern2.sub("", src)
        log.info("  _generate_fs_config_for_stubs: removido (já inline no stub)")

    # Remove chamada de _generate_fs_config_for_stubs do run() se houver
    src = re.sub(
        r"\s*self\._generate_fs_config_for_stubs\(target_dir\)\n?",
        "\n",
        src
    )

    mod_path.write_text(src, encoding="utf-8")
    log.info("  dm1q_aosp_compat.py: ✓ atualizado")
    return True


# ─────────────────────────────────────────────────────────────
# FIX 4: src/core/props.py
# _reconstruct_my_product_props → pula silenciosamente se base for AOSP
# e se my_product não existir no target (Samsung)
# ─────────────────────────────────────────────────────────────

def fix_props_my_product() -> bool:
    props_path = ROOT / "src" / "core" / "props.py"
    if not props_path.exists():
        log.warning(f"  Não encontrado: {props_path}")
        return True

    src = props_path.read_text(encoding="utf-8")

    marker = "# FIX-samsung: pula my_product se nao existir no target"
    if marker in src:
        log.info("  props.py: fix my_product já aplicado")
        return True

    bak(props_path)

    # Injeta guard no início de _reconstruct_my_product_props
    old_start = (
        "    def _reconstruct_my_product_props(self):\n"
        "        \"\"\"\n"
        "        Reconstructs my_product/build.prop by using baserom as base\n"
    )
    new_start = (
        "    def _reconstruct_my_product_props(self):\n"
        "        \"\"\"\n"
        "        Reconstructs my_product/build.prop by using baserom as base\n"
    )

    # Abordagem mais robusta: injeta logo após a abertura do método
    inject = (
        "\n        # FIX-samsung: pula my_product se nao existir no target\n"
        "        # Samsung/Evolution X usa apenas 'product', nao 'my_product'\n"
        "        target_my_product = self.target_dir / \"my_product\"\n"
        "        if not target_my_product.exists():\n"
        "            return\n"
    )

    # Encontra a linha de retorno antigo (primeira verificação do método)
    old_guard = (
        "        target_my_product = self.target_dir / \"my_product\"\n"
        "        if not target_my_product.exists():\n"
        "            return\n"
    )

    if old_guard in src:
        # Guard já existe, só adiciona o comentário explicativo
        src = src.replace(
            old_guard,
            "        # FIX-samsung: pula my_product se nao existir no target\n"
            "        # Samsung/Evolution X usa apenas 'product', nao 'my_product'\n"
            + old_guard,
            1
        )
        log.info("  props.py: comentário explicativo adicionado ao guard existente")
    else:
        # Injeta guard logo no início do método, antes de qualquer lógica
        target_line = "        logger.info(\"Reconstructing my_product properties...\")"
        if target_line in src:
            src = src.replace(
                target_line,
                "        # FIX-samsung: my_product nao existe em base Samsung/AOSP\n"
                "        if not (self.target_dir / \"my_product\").exists():\n"
                "            return\n"
                "        # FIX-samsung: pula my_product se nao existir no target\n"
                "\n"
                + target_line,
                1
            )
            log.info("  props.py: guard my_product adicionado")
        else:
            log.warning("  props.py: ponto de inserção não encontrado — verifique manualmente")

    props_path.write_text(src, encoding="utf-8")

    # Valida sintaxe
    import ast
    try:
        ast.parse(src)
        log.info("  props.py: ✓ sintaxe OK")
    except SyntaxError as e:
        log.error(f"  props.py: ERRO de sintaxe após patch: {e}")
        # Restaura backup
        bak_path = props_path.with_suffix(".py.bak_mp")
        if bak_path.exists():
            shutil.copy2(bak_path, props_path)
            log.error("  props.py: backup restaurado")
        return False

    return True


# ─────────────────────────────────────────────────────────────
# FIX 5: packer.py — garante que my_product está nos oplus_stubs
# (já deve estar, mas confirma)
# ─────────────────────────────────────────────────────────────

def verify_packer() -> bool:
    packer_path = ROOT / "src" / "core" / "packer.py"
    if not packer_path.exists():
        log.warning(f"  Não encontrado: {packer_path}")
        return True

    src = packer_path.read_text(encoding="utf-8")

    if "_oplus_stubs" in src and "my_product" in src:
        log.info("  packer.py: guard oplus_stubs presente ✓")
    else:
        log.warning("  packer.py: guard oplus_stubs NÃO encontrado — rode o fix_dm1q_direct.py primeiro")

    if "dm1q" in src and "9663676416" in src:
        log.info("  packer.py: dm1q no size_map ✓")
    else:
        log.warning("  packer.py: dm1q ausente do size_map — rode o fix_dm1q_direct.py primeiro")

    return True


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info("fix_myproduct.py — Remove my_product para base Samsung")
    log.info("=" * 55)

    if not (ROOT / "main.py").exists():
        log.error(f"Execute da raiz do projeto! Atual: {ROOT}")
        sys.exit(1)

    results = {}

    log.info("\n[1/5] devices/common/port_config.json ...")
    results["common/port_config"] = fix_common_port_config()

    log.info("\n[2/5] devices/target/dm1q/port_config.json ...")
    results["dm1q/port_config"] = fix_dm1q_port_config()

    log.info("\n[3/5] src/modules/dm1q_aosp_compat.py ...")
    results["dm1q_aosp_compat"] = fix_compat_module()

    log.info("\n[4/5] src/core/props.py ...")
    results["props.py"] = fix_props_my_product()

    log.info("\n[5/5] src/core/packer.py (verificação) ...")
    results["packer.py"] = verify_packer()

    log.info("\n" + "=" * 55)
    all_ok = all(results.values())
    for k, v in results.items():
        log.info(f"  {'OK  ' if v else 'FAIL'} {k}")

    if all_ok:
        log.info("""
Pronto! Após aplicar, a ROM vai:
  ✓ Não criar stub de my_product
  ✓ Não tentar empacotar my_product no super.img
  ✓ Não tentar reconstruir props de my_product inexistente
  ✓ super_list correto: system, system_ext, product, vendor, odm, vendor_dlkm

Nota: my_product e my_manifest que vieram da ColorOS (portrom)
ainda serão ignorados pelo guard do packer.py.

Rode o porting:
  python3 main.py --baserom roms/base_unzip/ \\
                  --portrom roms/op12r-16.zip \\
                  --device_code dm1q --clean
""")
    else:
        log.warning("Alguns fixes falharam. Veja acima.")
        sys.exit(1)


if __name__ == "__main__":
    main()
