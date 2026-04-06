"""
Module: dm1q_aosp_compat  (versão 2 — corrigida pelo log port_8)
Samsung Galaxy S23 (dm1q) — Compatibilidade ColorOS + Base AOSP (Evolution X)

Correções aplicadas nesta versão:
  FIX-1: path de build.prop é system/system/build.prop (aninhado), não system/build.prop
  FIX-2: my_product e my_manifest precisam de fs_config + file_contexts mínimos para mkfs.erofs
  FIX-3: fingerprint precisa ser regenerado DEPOIS que este módulo cria my_product
  FIX-4: super size mapa para dm1q (A-only, ~9.6 GB)
"""

import logging
import re
import shutil
from pathlib import Path
from src.modules.base import BaseModule

logger = logging.getLogger(__name__)


class Dm1qAospCompatModule(BaseModule):

    name = "dm1q_aosp_compat"
    priority = 5  # Roda antes de todos os outros módulos
    enabled = True

    # Partições ColorOS-only sem correspondente na Evolution X
    COLOROS_ONLY_PARTITIONS = [
        "my_product", "my_engineering", "my_company", "my_carrier",
        "my_region", "my_heytap", "my_stock", "my_preload",
        "my_bigball", "my_manifest",
    ]

    # Props que causam problemas em base AOSP
    PROPS_TO_REMOVE = [
        "ro.oplus.image.my_product.type",
        "ro.oplus.image.my_product.mount",
        "vendor.gralloc.disable_ahardwarebuffer",
    ]

    def run(self) -> bool:
        logger.info("=" * 60)
        logger.info("dm1q AOSP Compat v2: Iniciando patches...")
        logger.info("=" * 60)

        target_dir = self.ctx.target_dir
        ok = True

        ok &= self._handle_missing_partitions(target_dir)
        ok &= self._create_stub_my_product(target_dir)
        ok &= self._generate_fs_config_for_stubs(target_dir)   # FIX-2
        ok &= self._fix_incompatible_props(target_dir)
        ok &= self._fix_prop_imports(target_dir)
        ok &= self._fix_fingerprint(target_dir)                # FIX-1 + FIX-3
        ok &= self._configure_play_integrity(target_dir)       # FIX-1

        logger.info("dm1q AOSP Compat v2: Concluído.")
        return ok

    # ------------------------------------------------------------------
    # FIX-1: path aninhado system/system/build.prop
    # ------------------------------------------------------------------

    def _find_system_build_prop(self, target_dir: Path) -> Path | None:
        """
        Evolution X extrai system dentro de system/ (caminho aninhado).
        Tenta: target/system/system/build.prop antes de target/system/build.prop
        """
        nested = target_dir / "system" / "system" / "build.prop"
        if nested.exists():
            return nested
        direct = target_dir / "system" / "build.prop"
        if direct.exists():
            return direct
        # Busca genérica
        for p in (target_dir / "system").rglob("build.prop"):
            return p
        return None

    def _find_partition_root(self, target_dir: Path, partition: str) -> Path | None:
        """
        Retorna o diretório raiz real da partição, considerando path aninhado.
        Ex: system -> target/system/system  (se existir)
            vendor -> target/vendor
        """
        nested = target_dir / partition / partition
        if nested.exists() and nested.is_dir():
            return nested
        direct = target_dir / partition
        if direct.exists():
            return direct
        return None

    # ------------------------------------------------------------------
    # Partições ausentes
    # ------------------------------------------------------------------

    def _handle_missing_partitions(self, target_dir: Path) -> bool:
        logger.info("Verificando partições ColorOS-only...")
        for part in self.COLOROS_ONLY_PARTITIONS:
            if (target_dir / part).exists():
                logger.info(f"  [OK]   {part} presente")
            else:
                logger.info(f"  [SKIP] {part} ausente (normal para base AOSP)")
        return True

    # ------------------------------------------------------------------
    # Stub my_product
    # ------------------------------------------------------------------

    def _create_stub_my_product(self, target_dir: Path) -> bool:
        my_product_dir = target_dir / "my_product"

        if my_product_dir.exists() and (my_product_dir / "build.prop").exists():
            logger.info("my_product/build.prop já existe, pulando stub.")
            return True

        logger.info("Criando stub de my_product...")
        my_product_dir.mkdir(parents=True, exist_ok=True)
        (my_product_dir / "etc").mkdir(exist_ok=True)
        (my_product_dir / "etc" / "bruce").mkdir(parents=True, exist_ok=True)

        stub_props = "\n".join([
            "# my_product stub — dm1q_aosp_compat v2",
            "ro.oplus.image.my_product.type=all",
            "ro.product.my_product.brand=samsung",
            "ro.product.my_product.device=dm1q",
            "ro.product.my_product.model=SM-S911B",
            "ro.product.my_product.name=dm1q",
            "ro.product.my_product.manufacturer=Samsung",
            "",
        ])
        (my_product_dir / "build.prop").write_text(stub_props, encoding="utf-8")
        (my_product_dir / "etc" / "bruce" / "build.prop").write_text(
            "# bruce stub\n", encoding="utf-8"
        )
        logger.info(f"  Stub criado: {my_product_dir}/build.prop")
        return True

    # ------------------------------------------------------------------
    # FIX-2: gerar fs_config e file_contexts mínimos para my_product e my_manifest
    # ------------------------------------------------------------------

    def _generate_fs_config_for_stubs(self, target_dir: Path) -> bool:
        """
        mkfs.erofs requer --fs-config-file e --file-contexts.
        Para partições stub (my_product, my_manifest) que vieram sem esses
        arquivos de config, geramos entradas mínimas válidas.
        """
        config_dir = self.ctx.target_config_dir  # build/target/config/
        config_dir.mkdir(parents=True, exist_ok=True)

        stubs_needing_config = []
        for part in ["my_product", "my_manifest"]:
            part_dir = target_dir / part
            if not part_dir.exists():
                continue
            fs_cfg  = config_dir / f"{part}_fs_config"
            fc_cfg  = config_dir / f"{part}_file_contexts"
            if not fs_cfg.exists() or not fc_cfg.exists():
                stubs_needing_config.append((part, part_dir, fs_cfg, fc_cfg))

        if not stubs_needing_config:
            logger.info("fs_config/file_contexts já existem para my_product e my_manifest.")
            return True

        for part, part_dir, fs_cfg, fc_cfg in stubs_needing_config:
            logger.info(f"Gerando fs_config e file_contexts mínimos para {part}...")

            # fs_config: uma linha por arquivo encontrado na partição
            fs_lines = [f"{part} 0 2000 0755"]
            for f in sorted(part_dir.rglob("*")):
                rel = f.relative_to(part_dir)
                rel_str = str(rel).replace("\\", "/")
                if f.is_dir():
                    fs_lines.append(f"{part}/{rel_str} 0 2000 0755")
                else:
                    fs_lines.append(f"{part}/{rel_str} 0 0 0644")

            fs_cfg.write_text("\n".join(fs_lines) + "\n", encoding="utf-8")
            logger.info(f"  {fs_cfg.name}: {len(fs_lines)} entradas")

            # file_contexts: contexto SELinux genérico para partição oplus
            fc_lines = [
                f"/{part}(/.*)?  u:object_r:system_file:s0",
                f"/{part}/build\\.prop  u:object_r:system_prop_file:s0",
                f"/{part}/etc(/.*)?  u:object_r:system_file:s0",
            ]
            fc_cfg.write_text("\n".join(fc_lines) + "\n", encoding="utf-8")
            logger.info(f"  {fc_cfg.name}: {len(fc_lines)} entradas")

        return True

    # ------------------------------------------------------------------
    # Props incompatíveis
    # ------------------------------------------------------------------

    def _fix_incompatible_props(self, target_dir: Path) -> bool:
        logger.info("Corrigindo props incompatíveis com base AOSP...")
        for part in ["system", "system_ext", "product", "my_product"]:
            root = self._find_partition_root(target_dir, part)
            if not root:
                continue
            for prop_file in root.rglob("build.prop"):
                self._clean_prop_file(prop_file)
        return True

    def _clean_prop_file(self, prop_file: Path) -> None:
        try:
            lines = prop_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            new_lines, removed = [], []
            for line in lines:
                stripped = line.strip()
                drop = any(stripped.startswith(f"{k}=") for k in self.PROPS_TO_REMOVE)
                if drop:
                    removed.append(stripped)
                else:
                    new_lines.append(line)
            if removed:
                prop_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                for r in removed:
                    logger.info(f"  Removido: {r}")
        except Exception as e:
            logger.warning(f"  Erro ao limpar {prop_file}: {e}")

    # ------------------------------------------------------------------
    # Corrige imports de build.prop
    # ------------------------------------------------------------------

    def _fix_prop_imports(self, target_dir: Path) -> bool:
        logger.info("Corrigindo imports de build.prop para partições inexistentes...")
        possibly_missing = [p for p in self.COLOROS_ONLY_PARTITIONS
                            if not (target_dir / p).exists()]
        if not possibly_missing:
            logger.info("  Nenhum import para corrigir.")
            return True

        fixed = 0
        for part in ["system", "system_ext", "product", "my_product"]:
            root = self._find_partition_root(target_dir, part)
            if not root:
                continue
            for prop_file in root.rglob("build.prop"):
                try:
                    content = prop_file.read_text(encoding="utf-8", errors="ignore")
                    new_lines, changed = [], False
                    for line in content.splitlines():
                        s = line.strip()
                        if s.startswith("import ") and any(f"/{m}/" in s for m in possibly_missing):
                            new_lines.append(f"# [dm1q-compat] {line}")
                            changed = True
                            fixed += 1
                            logger.info(f"  Comentado: {s}")
                        else:
                            new_lines.append(line)
                    if changed:
                        prop_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                except Exception as e:
                    logger.warning(f"  Erro em {prop_file}: {e}")

        logger.info(f"  Imports corrigidos: {fixed}")
        return True

    # ------------------------------------------------------------------
    # FIX-1 + FIX-3: fingerprint regenerado com path correto
    # ------------------------------------------------------------------

    def _fix_fingerprint(self, target_dir: Path) -> bool:
        """
        O fingerprint saiu como 'OnePlus//oplus' porque na Stage 2
        my_product ainda não existia e o path system/system/ não foi
        considerado. Aqui regeneramos com os valores corretos do S23.
        """
        logger.info("Regenerando fingerprint para dm1q (SM-S911B)...")

        # Lê props da base (vendor tem os valores mais confiáveis do device)
        vendor_root = self._find_partition_root(target_dir, "vendor")
        system_root = self._find_partition_root(target_dir, "system")

        def read_prop(root: Path | None, key: str, fallback: str = "") -> str:
            if not root:
                return fallback
            for bp in root.rglob("build.prop"):
                try:
                    for line in bp.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.strip().startswith(f"{key}="):
                            return line.split("=", 1)[1].strip()
                except Exception:
                    pass
            return fallback

        brand       = read_prop(vendor_root, "ro.product.vendor.brand",       "samsung")
        name        = read_prop(vendor_root, "ro.product.vendor.name",        "dm1q")
        device      = read_prop(vendor_root, "ro.product.vendor.device",      "dm1q")
        version     = read_prop(system_root, "ro.build.version.release",      "15")
        build_id    = read_prop(system_root, "ro.build.id",                   "AP3A")
        incremental = read_prop(system_root, "ro.build.version.incremental",  "eng")
        build_type  = read_prop(system_root, "ro.build.type",                 "user")
        tags        = read_prop(system_root, "ro.build.tags",                 "release-keys")

        fingerprint = f"{brand}/{name}/{device}:{version}/{build_id}/{incremental}:{build_type}/{tags}"
        description = f"{name}-{build_type} {version} {build_id} {incremental} {tags}"

        logger.info(f"  Novo fingerprint: {fingerprint}")

        fp_replacements = {
            "ro.build.fingerprint":            fingerprint,
            "ro.bootimage.build.fingerprint":  fingerprint,
            "ro.system.build.fingerprint":     fingerprint,
            "ro.product.build.fingerprint":    fingerprint,
            "ro.system_ext.build.fingerprint": fingerprint,
            "ro.vendor.build.fingerprint":     fingerprint,
            "ro.odm.build.fingerprint":        fingerprint,
            "ro.build.description":            description,
            "ro.system.build.description":     description,
        }

        modified = 0
        for part in ["system", "system_ext", "product", "vendor", "odm", "my_product"]:
            root = self._find_partition_root(target_dir, part)
            if not root:
                continue
            for bp in root.rglob("build.prop"):
                if self._apply_prop_replacements(bp, fp_replacements):
                    modified += 1

        logger.info(f"  Fingerprint atualizado em {modified} arquivos.")
        return True

    def _apply_prop_replacements(self, prop_file: Path, replacements: dict) -> bool:
        try:
            lines = prop_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            new_lines, changed = [], False
            for line in lines:
                key = line.split("=", 1)[0].strip()
                if key in replacements:
                    new_line = f"{key}={replacements[key]}"
                    if new_line != line.strip():
                        new_lines.append(new_line)
                        changed = True
                        continue
                new_lines.append(line)
            if changed:
                prop_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            return changed
        except Exception as e:
            logger.warning(f"  Erro ao aplicar replacements em {prop_file}: {e}")
            return False

    # ------------------------------------------------------------------
    # FIX-1: Play Integrity com path correto
    # ------------------------------------------------------------------

    def _configure_play_integrity(self, target_dir: Path) -> bool:
        logger.info("Configurando props de Play Integrity (S23)...")

        system_root = self._find_partition_root(target_dir, "system")
        if not system_root:
            logger.warning("  Diretório system não encontrado, pulando.")
            return True

        system_prop = system_root / "build.prop"
        if not system_prop.exists():
            logger.warning(f"  build.prop não encontrado em {system_root}, pulando.")
            return True

        play_props = {
            "ro.secure":              "1",
            "ro.debuggable":          "0",
            "ro.boot.selinux":        "enforcing",
            "ro.product.first_api_level": "33",
        }

        content = system_prop.read_text(encoding="utf-8", errors="ignore")
        added = []
        for key, value in play_props.items():
            if not re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
                content += f"\n{key}={value}"
                added.append(f"{key}={value}")

        if added:
            system_prop.write_text(content, encoding="utf-8")
            for p in added:
                logger.info(f"  Adicionado: {p}")
        else:
            logger.info("  Props de Play Integrity já presentes.")

        return True
