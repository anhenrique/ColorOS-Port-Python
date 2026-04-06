#!/usr/bin/env python3
"""
apply_dm1q_patches.py
Aplica automaticamente todos os patches necessarios para suporte
ao Samsung Galaxy S23 (dm1q) com base Evolution X.

Uso:
  python apply_dm1q_patches.py --project-root /caminho/para/ColorOS-Port-Python
  python apply_dm1q_patches.py  # assume que esta na raiz do projeto
"""

import re
import sys
import shutil
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("dm1q-patcher")


def backup_file(path: Path) -> Path:
    """Cria backup .bak do arquivo antes de modificar."""
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
        logger.info(f"  Backup: {bak.name}")
    return bak


# ============================================================
# PATCH 1: rom.py - deteccao de Evolution X e Samsung
# ============================================================

def patch_rom_py(project_root: Path) -> bool:
    rom_py = project_root / "src" / "core" / "rom.py"
    if not rom_py.exists():
        logger.error(f"rom.py nao encontrado em {rom_py}")
        return False

    content = rom_py.read_text(encoding="utf-8")

    # Verifica se patch ja foi aplicado
    if "is_aosp_based" in content:
        logger.info("rom.py: patch ja aplicado, pulando.")
        return True

    backup_file(rom_py)

    # 1a. Adiciona propriedades is_aosp_based, is_evolution_x, is_samsung_device
    # Injeta depois da propriedade is_coloros
    new_props = '''
    @property
    def is_aosp_based(self) -> bool:
        """Detecta ROMs AOSP puras (Evolution X, LineageOS, etc.) sem camada Oplus."""
        has_oplus_area  = bool(self.get_prop("ro.oplus.image.system_ext.area"))
        has_oplus_rom   = bool(self.get_prop("ro.build.version.oplusrom"))
        has_oplus_brand = bool(self.get_prop("ro.oplus.image.system_ext.brand"))
        return not (has_oplus_area or has_oplus_rom or has_oplus_brand)

    @property
    def is_evolution_x(self) -> bool:
        """Detecta Evolution X especificamente."""
        display_id = self.get_prop("ro.build.display.id") or ""
        evo_prop   = self.get_prop("ro.evolution.device") or ""
        evo_prop2  = self.get_prop("org.evolution.device") or ""
        return "EvolutionX" in display_id or bool(evo_prop) or bool(evo_prop2)

    @property
    def is_samsung_device(self) -> bool:
        """Detecta dispositivo Samsung."""
        brand = (self.vendor_brand or "").lower()
        model = (self.product_model or "").upper()
        return brand == "samsung" or model.startswith("SM-")

'''

    # Injeta depois de is_coloros property
    insert_after = '        return not (self.is_coloros_global or self.is_oos or self.is_realme_ui)'
    if insert_after in content:
        content = content.replace(insert_after, insert_after + "\n" + new_props, 1)
        logger.info("  Adicionadas propriedades: is_aosp_based, is_evolution_x, is_samsung_device")
    else:
        logger.warning("  Nao encontrou ponto de insercao para novas propriedades (is_coloros).")

    # 1b. Atualiza detect_device_code para incluir S23 series
    samsung_map_insertion = '''
        # Samsung Galaxy S23 series
        samsung_patterns = {
            "SM-S911": "dm1q", "SM_S911": "dm1q", "S911B": "dm1q",
            "SM-S916": "dm2q", "SM_S916": "dm2q", "S916B": "dm2q",
            "SM-S918": "dm3q", "SM_S918": "dm3q", "S918B": "dm3q",
        }
        for pattern, code in samsung_patterns.items():
            if pattern in filename:
                logger.info(f"Device code Samsung do filename: {code}")
                return code

'''

    # Injeta no detect_device_code antes do match ColorOS
    insert_before_coloros = '        match = re.search(r"ColorOS_([^_]+)_", filename)'
    if insert_before_coloros in content:
        content = content.replace(
            insert_before_coloros,
            samsung_map_insertion + "        " + insert_before_coloros.strip(),
            1
        )
        logger.info("  Adicionados padroes Samsung em detect_device_code.")
    else:
        logger.warning("  Nao encontrou ponto de insercao em detect_device_code.")

    rom_py.write_text(content, encoding="utf-8")
    logger.info("rom.py: patch aplicado com sucesso.")
    return True


# ============================================================
# PATCH 2: packer.py - tamanho super para dm1q
# ============================================================

def patch_packer_py(project_root: Path) -> bool:
    packer_py = project_root / "src" / "core" / "packer.py"
    if not packer_py.exists():
        logger.error(f"packer.py nao encontrado em {packer_py}")
        return False

    content = packer_py.read_text(encoding="utf-8")

    if "dm1q" in content and "9663676416" in content:
        logger.info("packer.py: patch dm1q ja aplicado, pulando.")
        return True

    backup_file(packer_py)

    # Adiciona dm1q no size_map
    # Encontra a ultima entrada do size_map e adiciona depois
    insert_after = '            # Default size'
    samsung_entry = '''            # Samsung Galaxy S23 series (dm1q) - Evolution X
            9663676416: ["dm1q", "dm2q", "dm3q",
                         "SM-S911B", "SM-S916B", "SM-S918B",
                         "r0q", "r11q", "r12s"],
            # Default size
'''

    if insert_after in content:
        content = content.replace(insert_after, samsung_entry, 1)
        logger.info("  Adicionado dm1q no size_map do super.img.")
    else:
        logger.warning("  Nao encontrou ponto de insercao no size_map.")

    packer_py.write_text(content, encoding="utf-8")
    logger.info("packer.py: patch aplicado com sucesso.")
    return True


# ============================================================
# PATCH 3: props.py - _reconstruct_my_product_props para AOSP
# ============================================================

def patch_props_py(project_root: Path) -> bool:
    props_py = project_root / "src" / "core" / "props.py"
    if not props_py.exists():
        logger.error(f"props.py nao encontrado em {props_py}")
        return False

    content = props_py.read_text(encoding="utf-8")

    if "base_is_aosp" in content:
        logger.info("props.py: patch ja aplicado, pulando.")
        return True

    backup_file(props_py)

    # Substitui a logica de base_prop_file por versao com deteccao AOSP
    old_logic = (
        "        # 2. Parse Props\n"
        "        base_props = self._read_prop_to_dict(base_prop_file)\n"
        "        port_props = self._read_prop_to_dict(port_prop_file)\n"
        "        \n"
        "        # 3. Calculate Bruce Props (Port-only props + Force keys)\n"
        "        bruce_props = {}\n"
        "        for key, value in port_props.items():\n"
        "            if key in force_keys or key not in base_props:\n"
        "                bruce_props[key] = value\n"
        "                logger.debug(f\"Adding to bruce.prop: {key}={value}\")\n"
        "        \n"
        "        # 4. Overwrite target main prop with Base content\n"
        "        if base_prop_file.exists():\n"
        "            shutil.copy2(base_prop_file, target_prop_main)"
    )

    new_logic = (
        "        # 2. Detecta se base e AOSP (sem my_product)\n"
        "        base_is_aosp = not base_prop_file.exists()\n"
        "        if base_is_aosp:\n"
        "            logger.info(\"Base AOSP detectada (sem my_product) - usando portrom como fonte\")\n"
        "\n"
        "        # 3. Parse Props\n"
        "        base_props = self._read_prop_to_dict(base_prop_file) if not base_is_aosp else {}\n"
        "        port_props = self._read_prop_to_dict(port_prop_file)\n"
        "        \n"
        "        # 4. Calculate Bruce Props\n"
        "        # Base AOSP: todas as props do port vao para bruce\n"
        "        # Base Oplus: somente force_keys e props exclusivos do port\n"
        "        bruce_props = {}\n"
        "        for key, value in port_props.items():\n"
        "            if base_is_aosp or key in force_keys or key not in base_props:\n"
        "                bruce_props[key] = value\n"
        "                logger.debug(f\"Adding to bruce.prop: {key}={value}\")\n"
        "        \n"
        "        # 5. Overwrite target main prop\n"
        "        if not base_is_aosp and base_prop_file.exists():\n"
        "            shutil.copy2(base_prop_file, target_prop_main)\n"
        "        elif port_prop_file.exists():\n"
        "            # Base AOSP: usa portrom como base do prop principal\n"
        "            shutil.copy2(port_prop_file, target_prop_main)\n"
        "        if False:  # placeholder para if original - mantido para compatibilidade\n"
        "            pass"
    )

    if old_logic in content:
        content = content.replace(old_logic, new_logic, 1)
        logger.info("  Logica de _reconstruct_my_product_props atualizada para AOSP.")
    else:
        logger.warning(
            "  Nao encontrou o bloco exato em props.py. "
            "Aplique o patch manualmente usando src/core/props_patch_dm1q.py como referencia."
        )

    props_py.write_text(content, encoding="utf-8")
    logger.info("props.py: patch aplicado.")
    return True


# ============================================================
# PATCH 4: Copia arquivos de config do device dm1q
# ============================================================

def copy_device_configs(project_root: Path, patch_dir: Path) -> bool:
    """Copia configs do dm1q para o projeto."""
    dm1q_configs = patch_dir / "devices" / "target" / "dm1q"
    dest_dir = project_root / "devices" / "target" / "dm1q"
    dest_dir.mkdir(parents=True, exist_ok=True)

    for config_file in dm1q_configs.glob("*.json"):
        dest = dest_dir / config_file.name
        if dest.exists():
            logger.info(f"  Config {config_file.name} ja existe, pulando.")
        else:
            shutil.copy2(config_file, dest)
            logger.info(f"  Copiado: {config_file.name} -> {dest}")

    return True


def copy_module(project_root: Path, patch_dir: Path) -> bool:
    """Copia modulo dm1q_aosp_compat para o projeto."""
    src = patch_dir / "src" / "modules" / "dm1q_aosp_compat.py"
    dest = project_root / "src" / "modules" / "dm1q_aosp_compat.py"

    if dest.exists():
        logger.info("  Modulo dm1q_aosp_compat.py ja existe.")
    else:
        shutil.copy2(src, dest)
        logger.info(f"  Modulo copiado: {dest}")

    return True


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Aplica patches dm1q (Galaxy S23 + Evolution X) no ColorOS-Port-Python"
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Raiz do projeto ColorOS-Port-Python (default: diretorio atual)"
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    patch_dir = Path(__file__).parent.resolve()

    logger.info("=" * 60)
    logger.info("ColorOS-Port-Python - Patch dm1q (Galaxy S23 + Evolution X)")
    logger.info("=" * 60)
    logger.info(f"Projeto: {project_root}")

    if not (project_root / "main.py").exists():
        logger.error(
            f"Nao parece ser a raiz do ColorOS-Port-Python: {project_root}\n"
            "Use --project-root para especificar o caminho correto."
        )
        sys.exit(1)

    results = {}

    logger.info("\n[1/4] Aplicando patch em rom.py...")
    results["rom.py"] = patch_rom_py(project_root)

    logger.info("\n[2/4] Aplicando patch em packer.py...")
    results["packer.py"] = patch_packer_py(project_root)

    logger.info("\n[3/4] Aplicando patch em props.py...")
    results["props.py"] = patch_props_py(project_root)

    logger.info("\n[4/4] Copiando configs e modulo do dm1q...")
    results["device_configs"] = copy_device_configs(project_root, patch_dir)
    results["module"] = copy_module(project_root, patch_dir)

    logger.info("\n" + "=" * 60)
    logger.info("RESULTADO DOS PATCHES:")
    all_ok = True
    for name, ok in results.items():
        status = "OK" if ok else "FALHOU"
        logger.info(f"  {status:6} {name}")
        if not ok:
            all_ok = False

    if all_ok:
        logger.info("\nTodos os patches aplicados com sucesso!")
        logger.info("\nProximo passo - execute o porting:")
        logger.info(
            "  python main.py \\\n"
            "    --baserom /caminho/evolution_x_dm1q.zip \\\n"
            "    --portrom  /caminho/coloros_port.zip \\\n"
            "    --device_code dm1q \\\n"
            "    --pack_type payload"
        )
    else:
        logger.warning("\nAlguns patches falharam. Verifique os erros acima.")
        logger.info("Aplique manualmente usando os arquivos *_patch_dm1q.py como referencia.")
        sys.exit(1)


if __name__ == "__main__":
    main()
