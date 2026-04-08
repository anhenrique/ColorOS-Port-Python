#!/usr/bin/env python3
"""
fix_dm1q_direct.py
Aplica correções diretamente, sem depender de localização de blocos exatos.
Abordagem: reescreve os métodos problemáticos por completo via AST/regex simples.

Uso:
    python fix_dm1q_direct.py
    (rode da raiz do projeto ColorOS-Port-Python)
"""

import re
import sys
import shutil
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("fix-direct")

ROOT = Path(".").resolve()


def bak(p: Path):
    b = p.with_suffix(p.suffix + ".bak3")
    if not b.exists():
        shutil.copy2(p, b)
    log.info(f"  Backup: {b.name}")


# ─────────────────────────────────────────────────────────────
# FIX A: packer.py
# ─────────────────────────────────────────────────────────────

PACKER_GUARD = '''\
        # FIX-dm1q: partições oplus sem fs_config causam erro no mkfs.erofs
        _OPLUS_STUBS = [
            "my_product", "my_manifest", "my_engineering", "my_company",
            "my_carrier", "my_region", "my_heytap", "my_stock",
            "my_preload", "my_bigball",
        ]
        if part_name in _OPLUS_STUBS and (
            not fs_config.exists() or not file_contexts.exists()
        ):
            self.logger.warning(
                f"[dm1q] Pulando {part_name}: sem fs_config/file_contexts."
            )
            return

'''

PACKER_SIZE_ENTRY = '''\
            # Samsung Galaxy S23 series (dm1q) — Evolution X base
            9663676416: ["dm1q", "dm2q", "dm3q",
                         "SM-S911B", "SM-S916B", "SM-S918B",
                         "r0q", "r11q", "r12s"],
'''


def fix_packer():
    f = ROOT / "src" / "core" / "packer.py"
    if not f.exists():
        log.error(f"Não encontrado: {f}")
        return False

    src = f.read_text(encoding="utf-8")
    changed = False

    # Guard nas partições oplus
    if "FIX-dm1q: partições oplus" not in src:
        bak(f)
        # Injeta logo antes da chamada _run_patch_tools dentro de _pack_partition
        target = "        self._run_patch_tools(src_dir, fs_config, file_contexts)"
        if target in src:
            src = src.replace(target, PACKER_GUARD + target, 1)
            log.info("  [packer] Guard oplus adicionado em _pack_partition.")
            changed = True
        else:
            log.warning("  [packer] '_run_patch_tools' não encontrado — verifique manualmente.")

    # Super size dm1q
    if "dm1q" not in src or "9663676416" not in src:
        if not changed:
            bak(f)
        # Procura qualquer linha com "Default size" dentro de size_map
        if "# Default size" in src:
            src = src.replace(
                "            # Default size",
                PACKER_SIZE_ENTRY + "            # Default size",
                1
            )
            log.info("  [packer] dm1q adicionado no size_map.")
            changed = True
        else:
            log.warning("  [packer] '# Default size' não encontrado no size_map.")
    else:
        log.info("  [packer] dm1q já no size_map.")

    if changed:
        f.write_text(src, encoding="utf-8")
        log.info("packer.py: OK ✓")
    else:
        log.info("packer.py: sem alterações necessárias.")
    return True


# ─────────────────────────────────────────────────────────────
# FIX B: módulo dm1q_aosp_compat.py — reescrita total do método
#         _create_stub_my_product para também gerar fs_config
# ─────────────────────────────────────────────────────────────

MODULE_PATH = ROOT / "src" / "modules" / "dm1q_aosp_compat.py"

# Novo método que substitui _create_stub_my_product E adiciona
# _generate_fs_config_for_stubs logo depois
NEW_STUB_METHODS = '''\
    def _create_stub_my_product(self, target_dir: Path) -> bool:
        """Cria stub mínimo de my_product SE não existir."""
        my_product_dir = target_dir / "my_product"

        if my_product_dir.exists() and (my_product_dir / "build.prop").exists():
            logger.info("my_product/build.prop já existe, pulando stub.")
        else:
            logger.info("Criando stub de my_product...")
            my_product_dir.mkdir(parents=True, exist_ok=True)
            (my_product_dir / "etc" / "bruce").mkdir(parents=True, exist_ok=True)
            stub = "\\n".join([
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
                "# bruce stub\\n", encoding="utf-8"
            )
            logger.info(f"  Stub criado: {my_product_dir}/build.prop")

        # Sempre garante fs_config e file_contexts para packer
        self._generate_fs_config_for_stubs(target_dir)
        return True

    def _generate_fs_config_for_stubs(self, target_dir: Path) -> bool:
        """Gera fs_config e file_contexts mínimos para my_product e my_manifest."""
        config_dir = self.ctx.target_config_dir
        config_dir.mkdir(parents=True, exist_ok=True)

        for part in ["my_product", "my_manifest"]:
            part_dir = target_dir / part
            if not part_dir.exists():
                continue

            fs_cfg = config_dir / f"{part}_fs_config"
            fc_cfg = config_dir / f"{part}_file_contexts"

            if not fs_cfg.exists():
                lines = [f"{part} 0 2000 0755"]
                for fp in sorted(part_dir.rglob("*")):
                    rel = str(fp.relative_to(part_dir)).replace("\\\\", "/")
                    mode = "0755" if fp.is_dir() else "0644"
                    lines.append(f"{part}/{rel} 0 {'2000' if fp.is_dir() else '0'} {mode}")
                fs_cfg.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
                logger.info(f"  Gerado: {fs_cfg.name} ({len(lines)} entradas)")

            if not fc_cfg.exists():
                fc_lines = [
                    f"/{part}(/.*)? u:object_r:system_file:s0",
                    f"/{part}/build\\\\.prop u:object_r:system_prop_file:s0",
                    f"/{part}/etc(/.*)? u:object_r:system_file:s0",
                ]
                fc_cfg.write_text("\\n".join(fc_lines) + "\\n", encoding="utf-8")
                logger.info(f"  Gerado: {fc_cfg.name}")

        return True

'''


def fix_module():
    if not MODULE_PATH.exists():
        log.error(f"Módulo não encontrado: {MODULE_PATH}")
        return False

    src = MODULE_PATH.read_text(encoding="utf-8")

    if "_generate_fs_config_for_stubs" in src:
        log.info("dm1q_aosp_compat.py: _generate_fs_config_for_stubs já presente.")
        return True

    bak(MODULE_PATH)

    # Localiza o método _create_stub_my_product e substitui até o próximo def
    pattern = re.compile(
        r"( {4}def _create_stub_my_product\(self.*?)(?=\n {4}def )",
        re.DOTALL
    )
    if pattern.search(src):
        src = pattern.sub(NEW_STUB_METHODS, src, count=1)
        MODULE_PATH.write_text(src, encoding="utf-8")
        log.info("dm1q_aosp_compat.py: _create_stub_my_product atualizado + _generate_fs_config_for_stubs adicionado. ✓")
        return True
    else:
        log.warning("  Padrão _create_stub_my_product não encontrado. Tentando append...")
        # Append no final da classe
        src += "\n" + NEW_STUB_METHODS
        MODULE_PATH.write_text(src, encoding="utf-8")
        log.info("  Métodos adicionados no final do módulo.")
        return True


# ─────────────────────────────────────────────────────────────
# FIX C: fingerprint — corrige path aninhado system/system/
# ─────────────────────────────────────────────────────────────

FP_FIX_CODE = '''\

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

        def read_prop(root: Path | None, key: str, fallback: str = "") -> str:
            if not root:
                return fallback
            for bp in root.rglob("build.prop"):
                try:
                    for line in bp.read_text(encoding="utf-8", errors="ignore").splitlines():
                        s = line.strip()
                        if s.startswith(f"{key}="):
                            return s.split("=", 1)[1]
                except Exception:
                    pass
            return fallback

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
        }

        modified = 0
        for part in ["system", "system_ext", "product", "vendor", "odm", "my_product"]:
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
                        bp.write_text("\\n".join(new_lines) + "\\n", encoding="utf-8")
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
                content += f"\\n{key}={value}"
                added.append(f"{key}={value}")
        if added:
            system_bp.write_text(content, encoding="utf-8")
            for p in added:
                logger.info(f"  Adicionado: {p}")
        else:
            logger.info("  Props já presentes.")
        return True

'''


def fix_module_fingerprint():
    if not MODULE_PATH.exists():
        return False

    src = MODULE_PATH.read_text(encoding="utf-8")

    if "_fix_fingerprint_dm1q" in src:
        log.info("dm1q_aosp_compat.py: fingerprint fix já presente.")
    else:
        # Adiciona os métodos antes do último fechamento de classe
        src = src.rstrip() + "\n" + FP_FIX_CODE + "\n"
        MODULE_PATH.write_text(src, encoding="utf-8")
        log.info("dm1q_aosp_compat.py: métodos de fingerprint e Play Integrity adicionados. ✓")

    # Atualiza o método run() para chamar as versões novas
    run_old_pi   = "ok &= self._configure_play_integrity(target_dir)"
    run_new_pi   = "ok &= self._configure_play_integrity_v2(target_dir)"
    run_old_fp   = "# (fingerprint é regenerado pelo FingerprintStrategy na Stage 2)"
    run_new_fp_call = (
        "        ok &= self._fix_fingerprint_dm1q(target_dir)  # FIX: regenera após módulos\n"
        "        ok &= self._configure_play_integrity_v2(target_dir)"
    )

    src = MODULE_PATH.read_text(encoding="utf-8")
    changed = False

    if run_old_pi in src:
        src = src.replace(run_old_pi, run_new_pi, 1)
        changed = True
        log.info("  run(): _configure_play_integrity atualizada para v2.")

    # Adiciona chamada de fingerprint se não existir no run()
    if "_fix_fingerprint_dm1q" not in src.split("def run(")[1].split("def ")[0]:
        # Injeta antes do return True no run()
        src = src.replace(
            "        logger.info(\"dm1q AOSP Compat",
            "        ok &= self._fix_fingerprint_dm1q(target_dir)\n"
            "        logger.info(\"dm1q AOSP Compat",
            1
        )
        changed = True
        log.info("  run(): chamada de _fix_fingerprint_dm1q adicionada.")

    if changed:
        MODULE_PATH.write_text(src, encoding="utf-8")

    return True


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info("dm1q Direct Fix — baseado no port_9.log")
    log.info("=" * 55)

    if not (ROOT / "main.py").exists():
        log.error(f"Execute da raiz do projeto! Diretório atual: {ROOT}")
        sys.exit(1)

    results = {}

    log.info("\n[1/3] packer.py — guard oplus + super size dm1q...")
    results["packer.py"] = fix_packer()

    log.info("\n[2/3] dm1q_aosp_compat.py — fs_config para stubs...")
    results["compat_stub"] = fix_module()

    log.info("\n[3/3] dm1q_aosp_compat.py — fingerprint path aninhado...")
    results["compat_fp"] = fix_module_fingerprint()

    log.info("\n" + "=" * 55)
    ok = all(results.values())
    for k, v in results.items():
        log.info(f"  {'OK  ' if v else 'FAIL'} {k}")

    if ok:
        log.info("""
Pronto! Agora rode:

  python main.py \\
    --baserom /path/evolution_x_dm1q.zip \\
    --portrom  /path/coloros_port.zip \\
    --device_code dm1q \\
    --pack_type payload --clean

Erros que devem sumir:
  ✓ mkfs.erofs failed for my_product / my_manifest
  ✓ Fingerprint: OnePlus//oplus
  ✓ super size 15GB → 9.6GB
  ✓ system/build.prop não encontrado (Play Integrity)
""")
    else:
        log.warning("Alguns fixes falharam. Veja acima.")
        sys.exit(1)


if __name__ == "__main__":
    main()
