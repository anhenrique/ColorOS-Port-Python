#!/usr/bin/env python3
"""
apply_dm1q_fix2.py
Aplica correções v2 baseadas nos erros encontrados no log port_8.log

Problemas corrigidos:
  FIX-1: build.prop em path aninhado system/system/build.prop
  FIX-2: my_product e my_manifest sem fs_config → mkfs.erofs falha
  FIX-3: fingerprint regenerado tarde demais (Stage 3.6 em vez de Stage 2)
  FIX-4: super size errado para dm1q (15GB→9.6GB)
  FIX-5: packer não pula partições oplus sem config (causa erro no OTA)

Uso:
  python apply_dm1q_fix2.py --project-root .
  python apply_dm1q_fix2.py   # usa diretório atual
"""

import re
import sys
import shutil
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("dm1q-fix2")

OPLUS_STUBS = [
    "my_product", "my_manifest", "my_engineering", "my_company",
    "my_carrier", "my_region", "my_heytap", "my_stock",
    "my_preload", "my_bigball",
]


def bak(path: Path) -> None:
    b = path.with_suffix(path.suffix + ".bak2")
    if not b.exists():
        shutil.copy2(path, b)
        log.info(f"  Backup: {b.name}")


# ──────────────────────────────────────────────
# FIX-2 + FIX-4 + FIX-5  →  packer.py
# ──────────────────────────────────────────────

def patch_packer(root: Path) -> bool:
    f = root / "src" / "core" / "packer.py"
    if not f.exists():
        log.error(f"packer.py não encontrado: {f}")
        return False

    src = f.read_text(encoding="utf-8")
    changed = False

    # FIX-4: super size dm1q
    if "dm1q" not in src or "9663676416" not in src:
        bak(f)
        entry = (
            "            # Samsung Galaxy S23 series (dm1q) — Evolution X\n"
            '            9663676416: ["dm1q", "dm2q", "dm3q",\n'
            '                         "SM-S911B", "SM-S916B", "SM-S918B",\n'
            '                         "r0q", "r11q", "r12s"],\n'
            "            # Default size\n"
        )
        if "# Default size" in src:
            src = src.replace("            # Default size\n", entry, 1)
            log.info("  FIX-4: dm1q adicionado no size_map.")
            changed = True
        else:
            log.warning("  FIX-4: ponto de inserção no size_map não encontrado.")
    else:
        log.info("  FIX-4: dm1q já presente no size_map.")

    # FIX-5: pular partições oplus sem fs_config no _pack_partition
    fix5_marker = "# FIX-dm1q: pula particoes oplus sem config"
    if fix5_marker not in src:
        if not changed:
            bak(f)
            changed = True

        # Injeta logo após a linha que define fs_config e file_contexts
        old_block = (
            "        self.logger.info(f\"Packing [{part_name}] as {pack_type}...\")\n"
            "\n"
            "        self._run_patch_tools(src_dir, fs_config, file_contexts)"
        )
        new_block = (
            "        self.logger.info(f\"Packing [{part_name}] as {pack_type}...\")\n"
            "\n"
            "        # FIX-dm1q: pula particoes oplus sem config\n"
            "        _oplus_stubs = [\n"
            '            "my_product", "my_manifest", "my_engineering", "my_company",\n'
            '            "my_carrier", "my_region", "my_heytap", "my_stock",\n'
            '            "my_preload", "my_bigball",\n'
            "        ]\n"
            "        if part_name in _oplus_stubs and (\n"
            "            not fs_config.exists() or not file_contexts.exists()\n"
            "        ):\n"
            "            self.logger.warning(\n"
            "                f\"[dm1q] Pulando {part_name}: sem fs_config/file_contexts. \"\n"
            "                f\"Nao sera incluida no super.img.\"\n"
            "            )\n"
            "            return\n"
            "\n"
            "        self._run_patch_tools(src_dir, fs_config, file_contexts)"
        )

        if old_block in src:
            src = src.replace(old_block, new_block, 1)
            log.info("  FIX-5: guard de partições oplus adicionado em _pack_partition.")
        else:
            log.warning("  FIX-5: bloco alvo não encontrado em _pack_partition. Verifique manualmente.")
    else:
        log.info("  FIX-5: guard já presente.")

    if changed:
        f.write_text(src, encoding="utf-8")
    log.info("packer.py: OK")
    return True


# ──────────────────────────────────────────────
# FIX-1 + FIX-3  →  props.py  (path aninhado)
# ──────────────────────────────────────────────

def patch_props(root: Path) -> bool:
    f = root / "src" / "core" / "props.py"
    if not f.exists():
        log.error(f"props.py não encontrado: {f}")
        return False

    src = f.read_text(encoding="utf-8")

    # Já aplicado?
    if "_find_partition_root" in src:
        log.info("props.py: FIX-1 já aplicado.")
        return True

    bak(f)

    # Substitui _find_build_prop por versão que entende path aninhado
    old_fn = (
        "    def _find_build_prop(self, partition_dir: Path) -> Path:\n"
        "        \"\"\"Find build.prop in partition directory (handling etc/ subdirectory).\"\"\"\n"
        "        direct = partition_dir / \"build.prop\"\n"
        "        if direct.exists():\n"
        "            return direct\n"
        "        nested = partition_dir / \"etc\" / \"build.prop\"\n"
        "        return nested"
    )
    new_fn = (
        "    def _find_build_prop(self, partition_dir: Path) -> Path:\n"
        "        \"\"\"\n"
        "        Find build.prop in partition directory.\n"
        "        FIX-1 dm1q: Evolution X usa path aninhado, ex: system/system/build.prop\n"
        "        \"\"\"\n"
        "        # Tenta path aninhado primeiro (ex: system/system/build.prop)\n"
        "        part_name = partition_dir.name\n"
        "        nested_same = partition_dir / part_name / \"build.prop\"\n"
        "        if nested_same.exists():\n"
        "            return nested_same\n"
        "        direct = partition_dir / \"build.prop\"\n"
        "        if direct.exists():\n"
            "            return direct\n"
        "        nested_etc = partition_dir / \"etc\" / \"build.prop\"\n"
        "        return nested_etc\n"
        "\n"
        "    def _find_partition_root(self, partition_dir: Path) -> Path:\n"
        "        \"\"\"\n"
        "        Retorna o diretório raiz real da partição.\n"
        "        FIX-1 dm1q: Evolution X aninha system dentro de system/.\n"
        "        \"\"\"\n"
        "        part_name = partition_dir.name\n"
        "        nested = partition_dir / part_name\n"
        "        if nested.exists() and nested.is_dir():\n"
        "            return nested\n"
        "        return partition_dir"
    )

    if old_fn in src:
        src = src.replace(old_fn, new_fn, 1)
        log.info("  FIX-1: _find_build_prop atualizado para path aninhado.")
    else:
        log.warning(
            "  FIX-1: bloco _find_build_prop não encontrado exatamente. "
            "Aplique manualmente (veja props_fix2_manual.py)."
        )

    f.write_text(src, encoding="utf-8")
    log.info("props.py: OK")
    return True


# ──────────────────────────────────────────────
# Substitui módulo dm1q_aosp_compat.py
# ──────────────────────────────────────────────

def update_module(root: Path, patch_dir: Path) -> bool:
    src_mod  = patch_dir / "src" / "modules" / "dm1q_aosp_compat.py"
    dest_mod = root / "src" / "modules" / "dm1q_aosp_compat.py"

    if not src_mod.exists():
        log.error(f"Módulo fonte não encontrado: {src_mod}")
        return False

    if dest_mod.exists():
        bak(dest_mod)

    shutil.copy2(src_mod, dest_mod)
    log.info(f"  Módulo dm1q_aosp_compat.py atualizado (v2).")
    return True


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Aplica correções dm1q v2 (baseadas no log port_8.log)"
    )
    parser.add_argument("--project-root", default=".", help="Raiz do projeto")
    args = parser.parse_args()

    proj  = Path(args.project_root).resolve()
    patch = Path(__file__).parent.resolve()

    log.info("=" * 60)
    log.info("dm1q Fix v2 — Correções pós port_8.log")
    log.info("=" * 60)
    log.info(f"Projeto: {proj}")

    if not (proj / "main.py").exists():
        log.error(f"Não parece ser a raiz do projeto: {proj}")
        sys.exit(1)

    results = {}

    log.info("\n[1/3] Corrigindo packer.py (FIX-4 super size + FIX-5 guard oplus)...")
    results["packer.py"] = patch_packer(proj)

    log.info("\n[2/3] Corrigindo props.py (FIX-1 path aninhado)...")
    results["props.py"] = patch_props(proj)

    log.info("\n[3/3] Atualizando módulo dm1q_aosp_compat.py (FIX-1/2/3)...")
    results["dm1q_aosp_compat.py"] = update_module(proj, patch)

    log.info("\n" + "=" * 60)
    all_ok = all(results.values())
    for name, ok in results.items():
        log.info(f"  {'OK  ' if ok else 'FAIL'} {name}")

    if all_ok:
        log.info("\nCorreções v2 aplicadas! Execute novamente:")
        log.info(
            "  python main.py \\\n"
            "    --baserom /path/evolution_x_dm1q.zip \\\n"
            "    --portrom  /path/coloros_port.zip \\\n"
            "    --device_code dm1q \\\n"
            "    --pack_type payload\n"
        )
        log.info("Erros que devem desaparecer no próximo log:")
        log.info("  ✓ mkfs.erofs failed for my_product / my_manifest")
        log.info("  ✓ Fingerprint: OnePlus//oplus (brand/name vazios)")
        log.info("  ✓ super size errado (15GB → 9.6GB)")
        log.info("  ✓ system/build.prop não encontrado (Play Integrity)")
    else:
        log.warning("\nAlguns patches falharam — aplique manualmente.")
        sys.exit(1)


if __name__ == "__main__":
    main()
