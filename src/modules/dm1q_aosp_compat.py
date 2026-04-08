"""
<<<<<<< HEAD
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
=======
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
>>>>>>> e98abe7a534c0ac8cfe7c001d70322dc8fc4ae0e
import shutil
from pathlib import Path
from src.modules.base import BaseModule

logger = logging.getLogger(__name__)


class Dm1qAospCompatModule(BaseModule):
<<<<<<< HEAD
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
=======

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
>>>>>>> e98abe7a534c0ac8cfe7c001d70322dc8fc4ae0e
        "vendor.gralloc.disable_ahardwarebuffer",
    ]

    def run(self) -> bool:
        logger.info("=" * 60)
<<<<<<< HEAD
        ok &= self._fix_fingerprint_dm1q(target_dir)
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
        """Cria stub mínimo de my_product SE não existir."""
=======
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
>>>>>>> e98abe7a534c0ac8cfe7c001d70322dc8fc4ae0e
        my_product_dir = target_dir / "my_product"

        if my_product_dir.exists() and (my_product_dir / "build.prop").exists():
            logger.info("my_product/build.prop já existe, pulando stub.")
<<<<<<< HEAD
        else:
            logger.info("Criando stub de my_product...")
            my_product_dir.mkdir(parents=True, exist_ok=True)
            (my_product_dir / "etc" / "bruce").mkdir(parents=True, exist_ok=True)
            stub = "
".join([
                "# my_product stub — dm1q_aosp_compat",
                "ro.oplus.image.my_product.type=all",
                "ro.product.my_product.brand=samsung",
                "ro.product.my_product.device=dm1q",
                "ro.product.my_product.model=SM-S911B",
                "ro.product.my_product.name=dm1q",
                "ro.product.my_product.manufacturer=Samsung", "",
            ])
            (my_product_dir / "build.prop").write_text(stub, encoding="utf-8")
            (my_product_dir / "etc" / "bruce" / "build.prop").write_text(
                "# bruce stub
", encoding="utf-8"
            )
            logger.info(f"  Stub criado: {my_product_dir}/build.prop")

        # Sempre garante fs_config e file_contexts para packer
        self._generate_fs_config_for_stubs(target_dir)
        return True

    def _generate_fs_config_for_stubs(self, target_dir: Path) -> bool:
        """Gera fs_config e file_contexts mínimos para my_product e my_manifest."""
        config_dir = self.ctx.target_config_dir
        config_dir.mkdir(parents=True, exist_ok=True)

=======
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
>>>>>>> e98abe7a534c0ac8cfe7c001d70322dc8fc4ae0e
        for part in ["my_product", "my_manifest"]:
            part_dir = target_dir / part
            if not part_dir.exists():
                continue
<<<<<<< HEAD

            fs_cfg = config_dir / f"{part}_fs_config"
            fc_cfg = config_dir / f"{part}_file_contexts"

            if not fs_cfg.exists():
                lines = [f"{part} 0 2000 0755"]
                for fp in sorted(part_dir.rglob("*")):
                    rel = str(fp.relative_to(part_dir)).replace("\", "/")
                    mode = "0755" if fp.is_dir() else "0644"
                    lines.append(f"{part}/{rel} 0 {'2000' if fp.is_dir() else '0'} {mode}")
                fs_cfg.write_text("
".join(lines) + "
", encoding="utf-8")
                logger.info(f"  Gerado: {fs_cfg.name} ({len(lines)} entradas)")

            if not fc_cfg.exists():
                fc_lines = [
                    f"/{part}(/.*)? u:object_r:system_file:s0",
                    f"/{part}/build\.prop u:object_r:system_prop_file:s0",
                    f"/{part}/etc(/.*)? u:object_r:system_file:s0",
                ]
                fc_cfg.write_text("
".join(fc_lines) + "
", encoding="utf-8")
                logger.info(f"  Gerado: {fc_cfg.name}")

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

    def _fix_fingerprint_dm1q(self, target_dir: Path) -> bool:
        """
        Regenera fingerprint com valores corretos do S23.
        FIX: considera path aninhado system/system/build.prop (Evolution X).
        """
        logger.info("Regenerando fingerprint dm1q...")

        def find_root(part: str) -> Path | None:
            nested = target_dir / part / part
            if nested.exists():
                return nested
            direct = target_dir / part
            if direct.exists():
                return direct
            return None
=======
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
>>>>>>> e98abe7a534c0ac8cfe7c001d70322dc8fc4ae0e

        def read_prop(root: Path | None, key: str, fallback: str = "") -> str:
            if not root:
                return fallback
            for bp in root.rglob("build.prop"):
                try:
                    for line in bp.read_text(encoding="utf-8", errors="ignore").splitlines():
<<<<<<< HEAD
                        s = line.strip()
                        if s.startswith(f"{key}="):
                            return s.split("=", 1)[1]
=======
                        if line.strip().startswith(f"{key}="):
                            return line.split("=", 1)[1].strip()
>>>>>>> e98abe7a534c0ac8cfe7c001d70322dc8fc4ae0e
                except Exception:
                    pass
            return fallback

<<<<<<< HEAD
        vendor = find_root("vendor")
        system = find_root("system")

        brand       = read_prop(vendor, "ro.product.vendor.brand",      "samsung")
        name        = read_prop(vendor, "ro.product.vendor.name",       "dm1q")
        device      = read_prop(vendor, "ro.product.vendor.device",     "dm1q")
        version     = read_prop(system, "ro.build.version.release",     "15")
        build_id    = read_prop(system, "ro.build.id",                  "AP3A")
        incremental = read_prop(system, "ro.build.version.incremental", "eng")
        build_type  = read_prop(system, "ro.build.type",                "user")
        tags        = read_prop(system, "ro.build.tags",                "release-keys")

        fp  = f"{brand}/{name}/{device}:{version}/{build_id}/{incremental}:{build_type}/{tags}"
        desc = f"{name}-{build_type} {version} {build_id} {incremental} {tags}"
        logger.info(f"  Fingerprint: {fp}")

        repl = {
            "ro.build.fingerprint":            fp,
            "ro.bootimage.build.fingerprint":  fp,
            "ro.system.build.fingerprint":     fp,
            "ro.product.build.fingerprint":    fp,
            "ro.system_ext.build.fingerprint": fp,
            "ro.vendor.build.fingerprint":     fp,
            "ro.odm.build.fingerprint":        fp,
            "ro.build.description":            desc,
            "ro.system.build.description":     desc,
=======
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
>>>>>>> e98abe7a534c0ac8cfe7c001d70322dc8fc4ae0e
        }

        modified = 0
        for part in ["system", "system_ext", "product", "vendor", "odm", "my_product"]:
<<<<<<< HEAD
            root = find_root(part)
            if not root:
                continue
            for bp in root.rglob("build.prop"):
                try:
                    lines = bp.read_text(encoding="utf-8", errors="ignore").splitlines()
                    new_lines, changed = [], False
                    for line in lines:
                        key = line.split("=", 1)[0].strip()
                        if key in repl and line.strip() != f"{key}={repl[key]}":
                            new_lines.append(f"{key}={repl[key]}")
                            changed = True
                        else:
                            new_lines.append(line)
                    if changed:
                        bp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                        modified += 1
                except Exception as e:
                    logger.warning(f"  Erro em {bp}: {e}")

        logger.info(f"  Fingerprint corrigido em {modified} arquivos.")
        return True

    def _configure_play_integrity_v2(self, target_dir: Path) -> bool:
        """Play Integrity com path aninhado correto."""
        logger.info("Configurando Play Integrity (S23)...")

        # Busca build.prop em system, considerando path aninhado
        system_bp = None
        for candidate in [
            target_dir / "system" / "system" / "build.prop",
            target_dir / "system" / "build.prop",
        ]:
            if candidate.exists():
                system_bp = candidate
                break

        if not system_bp:
            # Tenta rglob como fallback
            results = list((target_dir / "system").rglob("build.prop"))
            if results:
                system_bp = results[0]

        if not system_bp:
            logger.warning("  system/build.prop não encontrado.")
            return True

        content = system_bp.read_text(encoding="utf-8", errors="ignore")
        play_props = {
            "ro.secure": "1",
            "ro.debuggable": "0",
            "ro.boot.selinux": "enforcing",
        }
        added = []
        import re as _re
        for key, value in play_props.items():
            if not _re.search(rf"^{_re.escape(key)}=", content, _re.MULTILINE):
                content += f"\n{key}={value}"
                added.append(f"{key}={value}")
        if added:
            system_bp.write_text(content, encoding="utf-8")
            for p in added:
                logger.info(f"  Adicionado: {p}")
        else:
            logger.info("  Props já presentes.")
        return True


=======
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
>>>>>>> e98abe7a534c0ac8cfe7c001d70322dc8fc4ae0e
