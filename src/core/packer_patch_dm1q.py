"""
PATCH para src/core/packer.py
Adiciona o Samsung Galaxy S23 (dm1q) no mapa de tamanhos do super.img.

INSTRUCOES:
  No metodo _get_super_size de Repacker, adicione as entradas abaixo
  no dicionario size_map existente.
"""

# Adicionar no size_map dentro de _get_super_size:
#
# Galaxy S23 series (Snapdragon 8 Gen 2) - super de 9.1GB
# Baseado no layout de partitions do Evolution X para dm1q
SAMSUNG_S23_SUPER_ENTRIES = {
    # ~9.1 GB - Galaxy S23 (dm1q) / S23+ (dm2q) / S23 Ultra (dm3q)
    # Evolution X usa esse tamanho no super.img
    9663676416: ["dm1q", "dm2q", "dm3q", "SM-S911B", "SM-S916B", "SM-S918B"],

    # ~9.1 GB - Galaxy S22 series (r0q, r11q, r12s)
    9663676416: ["r0q", "r11q", "r12s"],

    # ~9.9 GB - Galaxy S24 series (e1q, e2q, e3q)
    # Snapdragon 8 Gen 3
    9932111872: ["e1q", "e2q", "e3q"],
}

# ============================================================
# INSTRUCOES DE APLICACAO MANUAL:
# ============================================================
#
# Em src/core/packer.py, dentro do metodo _get_super_size,
# ENCONTRE o dicionario size_map e ADICIONE antes do fechamento }:
#
#   # Samsung Galaxy S23 series (dm1q/dm2q/dm3q) - Evolution X base
#   9663676416: ["dm1q", "dm2q", "dm3q",
#                "SM-S911B", "SM-S916B", "SM-S918B",
#                "r0q", "r11q", "r12s"],
#
# TAMBEM no __init__ de Repacker, a linha:
#   self.product_out = self.out_dir / "target" / "product" / (self.ctx.baserom.vendor_device or "dm1q")
# ja usa "dm1q" como fallback, entao esta correta.
