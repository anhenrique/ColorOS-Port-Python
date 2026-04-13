#!/usr/bin/env python3
"""
patch_otatools_v2.py
Patch cirúrgico no common.py para aceitar EROFS.

Baseado na leitura real das linhas 2290-2300:
  2291: assert os.path.exists(path) and os.path.exists(mappath)
  2298: image = sparse_img.SparseImage(path, mappath, ...)

Para EROFS, o SparseImage falha. Solução: detectar EROFS e
usar FileImage/EmptyImage como fallback.

Uso:
    python3 patch_otatools_v2.py
"""

import sys
import shutil
from pathlib import Path

ROOT = Path("/root/ColorOS-Port-Python")
COMMON_PY = ROOT / "otatools" / "releasetools" / "common.py"


def log(msg):
    print(msg, flush=True)


def bak(p: Path):
    b = p.with_suffix(".py.bak_erofs2")
    if not b.exists():
        shutil.copy2(p, b)
        log(f"  Backup: {b.name}")


def patch_common():
    if not COMMON_PY.exists():
        log(f"ERRO: {COMMON_PY} não encontrado.")
        return False

    src = COMMON_PY.read_text(encoding="utf-8")

    if "# EROFS_PATCH_V2" in src:
        log("common.py: já patchado.")
        return True

    bak(COMMON_PY)

    # ─────────────────────────────────────────────────────────
    # PATCH 1: assert os.path.exists(path) and os.path.exists(mappath)
    # Substitui por versão que não falha quando mappath não existe
    # ─────────────────────────────────────────────────────────
    old1 = "  assert os.path.exists(path) and os.path.exists(mappath)"
    new1 = (
        "  # EROFS_PATCH_V2: não faz assert em mappath para EROFS\n"
        "  assert os.path.exists(path)\n"
        "  if not os.path.exists(mappath):\n"
        "    mappath = None  # EROFS: sem map sparse"
    )

    if old1 in src:
        src = src.replace(old1, new1, 1)
        log("  PATCH 1: assert de mappath relaxado.")
    else:
        log(f"  AVISO: PATCH 1 não encontrou o alvo exato.")
        log(f"  Tentando variação sem espaços duplos...")
        old1b = "assert os.path.exists(path) and os.path.exists(mappath)"
        if old1b in src:
            src = src.replace(old1b, old1b.replace(
                "assert os.path.exists(path) and os.path.exists(mappath)",
                "assert os.path.exists(path)  # EROFS_PATCH_V2: mappath opcional"
            ), 1)
            log("  PATCH 1b aplicado.")

    # ─────────────────────────────────────────────────────────
    # PATCH 2: image = sparse_img.SparseImage(path, mappath, ...)
    # Adiciona try/except para EROFS
    # ─────────────────────────────────────────────────────────
    old2 = (
        "  image = sparse_img.SparseImage(\n"
        "      path, mappath, clobbered_blocks, allow_shared_blocks=allow_shared_blocks)"
    )
    new2 = (
        "  # EROFS_PATCH_V2: fallback para EROFS\n"
        "  if mappath is None or not os.path.exists(mappath):\n"
        "    # EROFS ou imagem sem map — retorna imagem bruta\n"
        "    class _RawImage:\n"
        "      \"\"\"Minimal image object for non-sparse images (EROFS).\"\"\"\n"
        "      def __init__(self, path):\n"
        "        self.path = path\n"
        "        self.size = os.path.getsize(path)\n"
        "        self.blocksize = 4096\n"
        "        self.total_blocks = (self.size + self.blocksize - 1) // self.blocksize\n"
        "        self.care_map = RangeSet(['0-{}'.format(self.total_blocks - 1)])\n"
        "        self.clobbered_blocks = RangeSet()\n"
        "        self.extended = RangeSet()\n"
        "      def TotalSha256(self, include_clobbered_blocks=False):\n"
        "        import hashlib\n"
        "        h = hashlib.sha256()\n"
        "        with open(self.path, 'rb') as f:\n"
        "          while True:\n"
        "            chunk = f.read(1 << 20)\n"
        "            if not chunk: break\n"
        "            h.update(chunk)\n"
        "        return h.hexdigest()\n"
        "      def WriteRangeDataToFd(self, ranges, fd):\n"
        "        with open(self.path, 'rb') as f:\n"
        "          for s, e in ranges:\n"
        "            f.seek(s * self.blocksize)\n"
        "            fd.write(f.read((e - s) * self.blocksize))\n"
        "    image = _RawImage(path)\n"
        "  else:\n"
        "    image = sparse_img.SparseImage(\n"
        "        path, mappath, clobbered_blocks, allow_shared_blocks=allow_shared_blocks)"
    )

    if old2 in src:
        src = src.replace(old2, new2, 1)
        log("  PATCH 2: SparseImage com fallback EROFS aplicado.")
    else:
        # Tenta variação de formatação
        old2b = "image = sparse_img.SparseImage(\n      path, mappath, clobbered_blocks, allow_shared_blocks=allow_shared_blocks)"
        old2c = "image = sparse_img.SparseImage(path, mappath, clobbered_blocks, allow_shared_blocks=allow_shared_blocks)"
        if old2b in src:
            src = src.replace(old2b, new2.replace("  image", "  image").replace("  else:\n    image", "  else:\n    image"), 1)
            log("  PATCH 2b aplicado.")
        elif old2c in src:
            new2c = (
                "# EROFS_PATCH_V2\n"
                "  if mappath and os.path.exists(mappath):\n"
                "    image = sparse_img.SparseImage(path, mappath, clobbered_blocks, allow_shared_blocks=allow_shared_blocks)\n"
                "  else:\n"
                "    image = EmptyImage()  # EROFS fallback"
            )
            src = src.replace(old2c, new2c, 1)
            log("  PATCH 2c aplicado (linha única).")
        else:
            log("  AVISO: PATCH 2 não encontrou alvo. Mostrando linhas 2285-2310 para debug:")
            lines = src.splitlines()
            for i, line in enumerate(lines[2284:2310], start=2285):
                log(f"    {i:4d}: {repr(line)}")

    COMMON_PY.write_text(src, encoding="utf-8")

    # Valida sintaxe
    import subprocess
    r = subprocess.run(
        ["python3", "-m", "py_compile", str(COMMON_PY)],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        log(f"  ERRO de sintaxe: {r.stderr}")
        log("  Restaurando backup...")
        bak_path = COMMON_PY.with_suffix(".py.bak_erofs2")
        if bak_path.exists():
            shutil.copy2(bak_path, COMMON_PY)
        return False

    log("  Sintaxe OK.")
    return True


def show_lines():
    """Mostra as linhas relevantes antes e depois do patch."""
    if not COMMON_PY.exists():
        return
    lines = COMMON_PY.read_text().splitlines()
    log("\nLinhas 2285-2320 após patch:")
    for i, line in enumerate(lines[2284:2320], start=2285):
        log(f"  {i:4d}: {line}")


def main():
    log("=" * 55)
    log("patch_otatools_v2.py — Patch EROFS cirúrgico")
    log("=" * 55)

    ok = patch_common()

    if ok:
        show_lines()
        log("""
Patch aplicado! Agora rode:

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
        log("\nPatch falhou. Verifique acima.")
        sys.exit(1)


if __name__ == "__main__":
    main()
