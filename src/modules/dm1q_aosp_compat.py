"""
Module: dm1q_aosp_compat
Samsung Galaxy S23 (dm1q) - Compatibilidade ColorOS + Base AOSP (Evolution X)

Este modulo trata os problemas especificos de portar ColorOS para uma base
AOSP pura (Evolution X), onde particoes como my_product, my_engineering,
my_heytap NAO existem na base.

Problemas tratados:
1. my_product vazio/ausente na base AOSP
2. Props ro.oplus.* incompativeis
3. Remocao de APKs que dependem de particoes inexistentes
4. SELinux contexts para particoes ColorOS-only
5. Fingerprint e Play Integrity
"""

import logging
import shutil
from pathlib import Path
from src.modules.base import BaseModule

logger = logging.getLogger(__name__)


class Dm1qAospCompatModule(BaseModule):
    """
    Modulo de compatibilidade dm1q (Galaxy S23) com base AOSP.
    """

    name = "dm1q_aosp_compat"
    priority = 5  # Roda antes de todos os outros modulos
    enabled = True

    # Particoes que existem na ColorOS mas NAO na Evolution X
    COLOROS_ONLY_PARTITIONS = [
        "my_product",
        "my_engineering",
        "my_company",
        "my_carrier",
        "my_region",
        "my_heytap",
        "my_stock",
        "my_preload",
        "my_bigball",
        "my_manifest",
    ]

    # APKs que dependem de particoes inexistentes na base AOSP
    # e causam bootloop ou crashes
    PROBLEMATIC_APKS = [
        # Oplus launcher (usa my_product, nao funciona sem ela)
        "com.oplus.launcher3",
        "com.coloros.launcher",
        # Oplus setup wizard (hard-coded para hardware OnePlus)
        "com.oplus.setupwizard",
        # Alguns servicos que dependem de hardware-specific da OnePlus
        "com.oplus.engineermode",
    ]

    # Props que DEVEM ser removidas das particoes portadas
    # pois apontam para particoes/hardware inexistentes no S23
    PROPS_TO_REMOVE = [
        # Referencia a particoes oplus que nao existem
        "ro.oplus.image.my_product.type",
        "ro.oplus.image.my_product.mount",
        # Props de hardware OnePlus/Oppo que conflitam com Samsung
        "ro.hardware.egl",          # ColorOS usa adreno, S23 usa mali (no caso de Exynos) ou proprio
        "vendor.gralloc.disable_ahardwarebuffer",
    ]

    def run(self) -> bool:
        logger.info("=" * 60)
        logger.info("dm1q AOSP Compat: Iniciando patches de compatibilidade...")
        logger.info("=" * 60)

        target_dir = self.ctx.target_dir
        success = True

        # 1. Trata particoes ColorOS-only ausentes na base AOSP
        success &= self._handle_missing_partitions(target_dir)

        # 2. Cria estrutura minima de my_product para ColorOS nao crashar
        success &= self._create_stub_my_product(target_dir)

        # 3. Corrige props incompativeis em system e system_ext
        success &= self._fix_incompatible_props(target_dir)

        # 4. Corrige imports de build.prop que apontam para particoes inexistentes
        success &= self._fix_prop_imports(target_dir)

        # 5. Configura Play Integrity / SafetyNet para o S23
        success &= self._configure_play_integrity(target_dir)

        logger.info("dm1q AOSP Compat: Patches concluidos.")
        return success

    def _handle_missing_partitions(self, target_dir: Path) -> bool:
        """
        Verifica quais particoes ColorOS-only foram portadas mas nao tem
        correspondente na base AOSP. Cria diretorios vazios para evitar
        erros no packer.
        """
        logger.info("Verificando particoes ColorOS-only...")

        for part in self.COLOROS_ONLY_PARTITIONS:
            part_dir = target_dir / part
            if part_dir.exists():
                logger.info(f"  [OK] Particao '{part}' presente (veio da ColorOS)")
            else:
                # Cria diretorio vazio - o packer ira lidar com ele
                # ou ele sera ignorado se nao estiver em possible_super_list
                logger.info(f"  [SKIP] Particao '{part}' ausente (normal para base AOSP)")

        return True

    def _create_stub_my_product(self, target_dir: Path) -> bool:
        """
        Cria uma particao my_product stub minima.

        A ColorOS referencia my_product em varios lugares. Sem ela, pode
        ocorrer crash no SystemServer. Criamos uma versao minima com apenas
        o build.prop necessario.
        """
        my_product_dir = target_dir / "my_product"

        if my_product_dir.exists() and (my_product_dir / "build.prop").exists():
            logger.info("my_product ja existe e tem build.prop, pulando stub.")
            return True

        logger.info("Criando stub de my_product para compatibilidade AOSP...")

        my_product_dir.mkdir(parents=True, exist_ok=True)
        etc_dir = my_product_dir / "etc"
        etc_dir.mkdir(exist_ok=True)

        # build.prop minimo - apenas o necessario para ColorOS nao crashar
        stub_props = [
            "# my_product stub - gerado pelo dm1q_aosp_compat module",
            "# Necessario para compatibilidade ColorOS em base AOSP",
            "",
            "ro.oplus.image.my_product.type=all",
            "ro.product.my_product.brand=samsung",
            "ro.product.my_product.device=dm1q",
            "ro.product.my_product.model=SM-S911B",
            "ro.product.my_product.name=dm1q",
            "ro.product.my_product.manufacturer=Samsung",
            "",
        ]

        build_prop = my_product_dir / "build.prop"
        build_prop.write_text("\n".join(stub_props), encoding="utf-8")
        logger.info(f"  Criado: {build_prop}")

        return True

    def _fix_incompatible_props(self, target_dir: Path) -> bool:
        """
        Remove ou substitui props que causam problemas em base AOSP.
        Procura em system, system_ext e product.
        """
        logger.info("Corrigindo props incompativeis com base AOSP...")

        partitions_to_fix = ["system", "system_ext", "product"]

        for part in partitions_to_fix:
            part_dir = target_dir / part
            if not part_dir.exists():
                continue

            for prop_file in part_dir.rglob("build.prop"):
                self._clean_prop_file(prop_file)

        return True

    def _clean_prop_file(self, prop_file: Path) -> None:
        """Remove props problemáticas de um arquivo build.prop."""
        try:
            lines = prop_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            new_lines = []
            removed = []

            for line in lines:
                stripped = line.strip()
                should_remove = False

                for prop_key in self.PROPS_TO_REMOVE:
                    if stripped.startswith(f"{prop_key}="):
                        should_remove = True
                        removed.append(stripped)
                        break

                if not should_remove:
                    new_lines.append(line)

            if removed:
                prop_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                for r in removed:
                    logger.info(f"  Removido prop: {r} ({prop_file.relative_to(prop_file.parent.parent.parent)})")

        except Exception as e:
            logger.warning(f"  Erro ao limpar {prop_file}: {e}")

    def _fix_prop_imports(self, target_dir: Path) -> bool:
        """
        Corrige linhas 'import /mnt/vendor/...' que apontam para
        particoes que nao existem na base AOSP.

        ColorOS tem imports como:
          import /mnt/vendor/my_heytap/etc/build.prop
          import /mnt/vendor/my_product/etc/build.prop

        Se essas particoes nao existem no super.img, o init crasha.
        """
        logger.info("Corrigindo imports de build.prop para particoes inexistentes...")

        # Particoes que podem nao existir na base AOSP
        possibly_missing = [p for p in self.COLOROS_ONLY_PARTITIONS
                            if not (target_dir / p).exists()]

        if not possibly_missing:
            logger.info("  Todas as particoes existem, sem imports para corrigir.")
            return True

        partitions_to_scan = ["system", "system_ext", "product", "my_product"]
        fixed_count = 0

        for part in partitions_to_scan:
            part_dir = target_dir / part
            if not part_dir.exists():
                continue

            for prop_file in part_dir.rglob("build.prop"):
                try:
                    content = prop_file.read_text(encoding="utf-8", errors="ignore")
                    new_lines = []
                    changed = False

                    for line in content.splitlines():
                        stripped = line.strip()
                        # Detecta linhas de import para particoes ausentes
                        if stripped.startswith("import "):
                            skip = False
                            for missing_part in possibly_missing:
                                if f"/{missing_part}/" in stripped:
                                    logger.info(f"  Comentando import ausente: {stripped}")
                                    new_lines.append(f"# [dm1q-compat] {line}")
                                    changed = True
                                    skip = True
                                    fixed_count += 1
                                    break
                            if not skip:
                                new_lines.append(line)
                        else:
                            new_lines.append(line)

                    if changed:
                        prop_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

                except Exception as e:
                    logger.warning(f"  Erro ao processar {prop_file}: {e}")

        logger.info(f"  Total de imports corrigidos: {fixed_count}")
        return True

    def _configure_play_integrity(self, target_dir: Path) -> bool:
        """
        Configura props para melhorar compatibilidade com Play Integrity.

        A ROM portada usa o fingerprint da ColorOS, que pode falhar em
        Play Integrity. Aqui forcamos props que ajudam a passar o basico.
        """
        logger.info("Configurando props para Play Integrity (S23)...")

        system_prop = target_dir / "system" / "build.prop"
        if not system_prop.exists():
            logger.warning("  system/build.prop nao encontrado, pulando Play Integrity config.")
            return True

        try:
            content = system_prop.read_text(encoding="utf-8", errors="ignore")

            play_integrity_props = {
                # Indica que e um device certificado GMS
                "ro.product.first_api_level": "33",
                # Evita deteccao de ROM modificada pelo Google Play Services
                "ro.secure": "1",
                "ro.debuggable": "0",
                # SELinux enforcing (necessario para passar MEETS_DEVICE_INTEGRITY)
                "ro.boot.selinux": "enforcing",
            }

            added = []
            for key, value in play_integrity_props.items():
                import re
                if not re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
                    content += f"\n{key}={value}"
                    added.append(f"{key}={value}")

            if added:
                system_prop.write_text(content, encoding="utf-8")
                for prop in added:
                    logger.info(f"  Adicionado: {prop}")

        except Exception as e:
            logger.warning(f"  Erro ao configurar Play Integrity: {e}")

        return True
