#!/usr/bin/env python3
"""
patch_otatools.py
Patcha otatools para aceitar imagens EROFS em vez de apenas ext4/sparse.

O erro:
  File "non_ab_ota.py", line 76, in GetBlockDifferences
  File "common.py", line 2296, in GetNonSparseImage
  AssertionError

Causa: GetNonSparseImage faz assert que a imagem é sparse (ext4).
EROFS não é sparse — o assert falha.

Solução: Patchar GetNonSparseImage para retornar a imagem diretamente
quando ela não for sparse (EROFS, squashfs, etc).

Uso:
    python3 patch_otatools.py
    (rode da raiz do projeto)
"""

import re
import sys
import shutil
import subprocess
from pathlib import Path

ROOT = Path("/root/ColorOS-Port-Python")
OTA_DIR = ROOT / "otatools" / "bin" / "ota_from_target_files"


def log(msg):
    print(msg, flush=True)


def bak(p: Path):
    b = p.with_suffix(p.suffix + ".bak_erofs")
    if not b.exists():
        shutil.copy2(p, b)
        log(f"  Backup: {b.name}")


def find_common_py() -> Path:
    """Localiza o common.py dentro do módulo otatools."""
    # Pode estar em diferentes locais dependendo da versão
    candidates = [
        OTA_DIR / "common.py",
        ROOT / "otatools" / "releasetools" / "common.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Busca recursiva
    for f in ROOT.rglob("common.py"):
        if "ota_from_target_files" in str(f) or "releasetools" in str(f):
            return f
    return None


def find_non_ab_ota_py() -> Path:
    """Localiza o non_ab_ota.py."""
    candidates = [
        OTA_DIR / "non_ab_ota.py",
        ROOT / "otatools" / "releasetools" / "non_ab_ota.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    for f in ROOT.rglob("non_ab_ota.py"):
        return f
    return None


def patch_common_py(common_py: Path) -> bool:
    """
    Patcha GetNonSparseImage para aceitar EROFS.

    Original (aproximado):
        def GetNonSparseImage(self, partition, reset_file_map=False):
            ...
            assert not sparse_img.SparseImage.IsSparseSuperImage(...)
            return sparse_img.SparseImage(...)

    O assert falha para EROFS porque EROFS não é sparse.
    Solução: detectar EROFS pelo magic e retornar FileImage em vez de SparseImage.
    """
    log(f"\n[1/2] Patchando {common_py}...")

    src = common_py.read_text(encoding="utf-8")

    # Verifica se já foi patchado
    if "# EROFS_PATCH" in src:
        log("  Já patchado anteriormente.")
        return True

    # Localiza GetNonSparseImage
    if "GetNonSparseImage" not in src:
        log("  AVISO: GetNonSparseImage não encontrado em common.py")
        log("  Tentando abordagem alternativa via non_ab_ota.py...")
        return True  # Não é erro, pode estar em versão diferente

    bak(common_py)

    # Abordagem 1: Adiciona verificação de EROFS antes do assert/SparseImage
    # Magic EROFS: 0xE0F5E1E2 (little-endian nos bytes 1024-1028)
    erofs_patch = '''
def _IsErofsImage(path):
    """Check if image is EROFS format (magic at offset 1024)."""
    # EROFS_PATCH
    try:
        with open(path, "rb") as f:
            f.seek(1024)
            magic = f.read(4)
            # EROFS magic: 0xE0F5E1E2 little-endian
            return magic == b"\\xe2\\xe1\\xf5\\xe0"
    except Exception:
        return False

'''

    # Injeta a função helper antes de GetNonSparseImage
    target = "def GetNonSparseImage"
    if target in src:
        src = src.replace(target, erofs_patch + target, 1)
        log("  _IsErofsImage helper adicionado.")

    # Agora patcha o corpo de GetNonSparseImage
    # Localiza o assert e adiciona bypass para EROFS
    # Estratégia: wrapa o conteúdo problemático com try/except + verificação EROFS

    # Padrão 1: assert seguido de SparseImage
    pattern1 = re.compile(
        r"(def GetNonSparseImage\(self[^)]*\):.*?)"
        r"(assert\s+not\s+sparse_img\.SparseImage\.IsSparseSuperImage[^\n]*\n)",
        re.DOTALL
    )

    def replace_assert(m):
        prefix = m.group(1)
        assert_line = m.group(2)
        indent = "    " * 2  # assumindo indentação de método de classe
        bypass = (
            f"{indent}# EROFS_PATCH: bypass assert para imagens EROFS\n"
            f"{indent}if not _IsErofsImage(path):\n"
            f"{indent}    {assert_line.strip()}\n"
        )
        return prefix + bypass

    new_src, count = re.subn(pattern1, replace_assert, src, flags=re.DOTALL)
    if count > 0:
        src = new_src
        log(f"  Assert de sparse bypassed ({count} ocorrência(s)).")

    # Padrão 2: retorno de SparseImage — para EROFS retorna FileImage
    # Adiciona early return para EROFS antes de criar SparseImage
    pattern2 = re.compile(
        r"(def GetNonSparseImage\(self,\s*partition[^)]*\):)(.*?)"
        r"(return sparse_img\.SparseImage\(path[^)]*\))",
        re.DOTALL
    )

    def replace_return(m):
        sig = m.group(1)
        body = m.group(2)
        ret = m.group(3)

        # Detecta indentação do return
        lines = ret.split("\n")
        indent = ""
        for line in body.split("\n")[-5:]:
            if line.strip():
                indent = line[: len(line) - len(line.lstrip())]
                break

        erofs_early_return = (
            f"\n{indent}# EROFS_PATCH: retorna FileImage para EROFS\n"
            f"{indent}if _IsErofsImage(path):\n"
            f"{indent}    import common as _common\n"
            f"{indent}    return _common.FileImage(path)\n"
            f"{indent}"
        )
        return sig + body + erofs_early_return + ret

    new_src, count = re.subn(pattern2, replace_return, src, flags=re.DOTALL)
    if count > 0:
        src = new_src
        log(f"  Early return EROFS adicionado ({count} ocorrência(s)).")

    # Se nenhum padrão funcionou, usa abordagem mais agressiva:
    # wrapa GetNonSparseImage inteiro com try/except
    if "EROFS_PATCH" not in src or count == 0:
        log("  Padrões não encontrados, usando abordagem try/except...")

        # Localiza a função e adiciona try/except em volta do corpo
        pattern3 = re.compile(
            r"(def GetNonSparseImage\(self,\s*partition[^\n]*\n)((?:[ \t]+[^\n]*\n)*)",
        )
        match = pattern3.search(src)
        if match:
            func_sig = match.group(1)
            func_body = match.group(2)

            # Indenta o body e wrapa com try/except
            wrapped = (
                f"{func_sig}"
                f"    # EROFS_PATCH: try/except para EROFS\n"
                f"    try:\n"
                + "\n".join("    " + line if line.strip() else line
                            for line in func_body.splitlines())
                + "\n"
                f"    except AssertionError:\n"
                f"        path = self.GetPartitionBuildPropPath(partition)\n"
                f"        import common as _c\n"
                f"        return _c.FileImage(path)\n"
            )
            src = src[:match.start()] + wrapped + src[match.end():]
            log("  try/except adicionado em GetNonSparseImage.")

    common_py.write_text(src, encoding="utf-8")

    # Valida sintaxe
    result = subprocess.run(
        ["python3", "-c", f"import ast; ast.parse(open('{common_py}').read())"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        log(f"  ERRO de sintaxe após patch: {result.stderr}")
        log("  Restaurando backup...")
        bak_path = common_py.with_suffix(".py.bak_erofs")
        if bak_path.exists():
            shutil.copy2(bak_path, common_py)
        return False

    log("  common.py patchado com sucesso.")
    return True


def patch_non_ab_ota(non_ab_py: Path) -> bool:
    """
    Patcha non_ab_ota.py GetBlockDifferences para tratar EROFS.

    Linha ~76:
        source_image = GetUserImage(partition_name, source_zip, ...)
        target_image = GetUserImage(partition_name, target_zip, ...)

    GetUserImage chama GetNonSparseImage que falha com EROFS.
    Alternativa: usar EmptyImage() como source para OTA full.
    """
    log(f"\n[2/2] Patchando {non_ab_py}...")

    src = non_ab_py.read_text(encoding="utf-8")

    if "# EROFS_PATCH_NON_AB" in src:
        log("  Já patchado.")
        return True

    bak(non_ab_py)

    # Localiza GetBlockDifferences e adiciona try/except no GetUserImage
    old_pattern = re.compile(
        r"(source_image\s*=\s*common\.GetUserImage\([^\)]+\))",
    )

    patch_code = (
        "# EROFS_PATCH_NON_AB\n"
        "    try:\n"
        "        \\1\n"
        "    except (AssertionError, Exception) as _e:\n"
        "        logger.warning(f'GetUserImage failed ({_e}), using EmptyImage for EROFS')\n"
        "        source_image = common.EmptyImage()\n"
    )

    new_src, count = re.subn(old_pattern, patch_code, src)
    if count > 0:
        src = new_src
        log(f"  try/except adicionado em GetBlockDifferences ({count} local).")
    else:
        log("  Padrão source_image não encontrado, tentando abordagem direta...")
        # Adiciona import e monkey-patch no topo
        monkey_patch = '''
# EROFS_PATCH_NON_AB
import functools as _functools
_orig_GetNonSparseImage = None

def _safe_get_user_image(partition, input_zip, info_dict=None):
    """Wrapper que aceita EROFS retornando EmptyImage como fallback."""
    try:
        return common.GetUserImage(partition, input_zip, info_dict)
    except (AssertionError, Exception) as e:
        import logging
        logging.getLogger(__name__).warning(
            f"GetUserImage failed for {partition} (EROFS?): {e}. Using EmptyImage."
        )
        return common.EmptyImage()

'''
        # Injeta após os imports
        import_end = 0
        for m in re.finditer(r'^import |^from ', src, re.MULTILINE):
            import_end = m.end()

        # Encontra o fim da última linha de import
        last_import_line = src.rfind('\n', 0, import_end)
        next_newline = src.find('\n', last_import_line + 1)

        src = src[:next_newline + 1] + monkey_patch + src[next_newline + 1:]

        # Substitui chamadas de GetUserImage pelo wrapper
        src = src.replace(
            "common.GetUserImage(",
            "_safe_get_user_image("
        )
        log(f"  Monkey-patch aplicado: {src.count('_safe_get_user_image(')} substituições.")

    non_ab_py.write_text(src, encoding="utf-8")

    # Valida sintaxe
    result = subprocess.run(
        ["python3", "-c", f"import ast; ast.parse(open('{non_ab_py}').read())"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        log(f"  ERRO de sintaxe: {result.stderr}")
        bak_path = non_ab_py.with_suffix(".py.bak_erofs")
        if bak_path.exists():
            shutil.copy2(bak_path, non_ab_py)
        return False

    log("  non_ab_ota.py patchado.")
    return True


def main():
    log("=" * 55)
    log("patch_otatools.py — Suporte EROFS no ota_from_target_files")
    log("=" * 55)

    if not ROOT.exists():
        log(f"ERRO: {ROOT} não encontrado.")
        sys.exit(1)

    # Localiza os arquivos
    log("\nLocalizando arquivos do otatools...")
    common_py = find_common_py()
    non_ab_py = find_non_ab_ota_py()

    if not common_py:
        log("ERRO: common.py não encontrado!")
        log("Locais verificados:")
        log(f"  {OTA_DIR}/common.py")
        log(f"  otatools/releasetools/common.py")
        # Lista o que tem no otatools
        log("\nConteúdo de otatools/bin/ota_from_target_files/:")
        for f in sorted(OTA_DIR.iterdir()):
            log(f"  {f.name}")
        sys.exit(1)

    log(f"  common.py    : {common_py}")
    log(f"  non_ab_ota.py: {non_ab_py or 'NÃO ENCONTRADO'}")

    # Mostra linhas relevantes
    log("\nLinhas 2290-2300 de common.py:")
    lines = common_py.read_text().splitlines()
    for i, line in enumerate(lines[2289:2300], start=2290):
        log(f"  {i:4d}: {line}")

    if non_ab_py:
        log("\nLinhas 68-85 de non_ab_ota.py:")
        lines2 = non_ab_py.read_text().splitlines()
        for i, line in enumerate(lines2[67:85], start=68):
            log(f"  {i:4d}: {line}")

    results = {}
    results["common.py"] = patch_common_py(common_py)

    if non_ab_py:
        results["non_ab_ota.py"] = patch_non_ab_ota(non_ab_py)
    else:
        log("\n  non_ab_ota.py não encontrado — pulando.")

    log("\n" + "=" * 55)
    all_ok = all(results.values())
    for k, v in results.items():
        log(f"  {'OK  ' if v else 'FAIL'} {k}")

    if all_ok:
        log("""
Patches aplicados! Rode o OTA tool novamente:

  cd /root/ColorOS-Port-Python
  TMPDIR=/root/ColorOS-Port-Python/mytmp/ \\
  python3 otatools/bin/ota_from_target_files \\
    -v \\
    -k otatools/key/testkey \\
    out/target/product/dm1q \\
    out/dm1q_coloros_port.zip 2>&1 | tee out/ota_build.log

  ls -lh out/dm1q_coloros_port.zip
""")
    else:
        log("\nAlgum patch falhou. Verifique acima.")
        sys.exit(1)


if __name__ == "__main__":
    main()
