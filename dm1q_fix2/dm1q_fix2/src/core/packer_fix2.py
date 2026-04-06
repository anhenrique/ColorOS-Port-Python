"""
PATCH v2 para src/core/packer.py
Dois problemas corrigidos:

  FIX-A: dm1q ausente no size_map → usa 15GB padrão (errado, S23 é ~9.6GB)
  FIX-B: my_product e my_manifest falham no mkfs.erofs sem fs_config/file_contexts

INSTRUCOES DE APLICAÇÃO MANUAL (se o script automático não funcionar):

--- FIX-A: adicione no dicionário size_map em _get_super_size ---

    # Samsung Galaxy S23 series (dm1q/dm2q/dm3q) - Evolution X
    9663676416: ["dm1q", "dm2q", "dm3q",
                 "SM-S911B", "SM-S916B", "SM-S918B",
                 "r0q", "r11q", "r12s"],


--- FIX-B: em _pack_partition, adicione ANTES do bloco pack_type ---

    # FIX dm1q: partições oplus sem fs_config/file_contexts não podem ser
    # empacotadas com mkfs.erofs (retorna erro 1). Pula silenciosamente.
    if not fs_config.exists() or not file_contexts.exists():
        oplus_stubs = [
            "my_product", "my_manifest", "my_engineering", "my_company",
            "my_carrier", "my_region", "my_heytap", "my_stock",
            "my_preload", "my_bigball",
        ]
        if part_name in oplus_stubs:
            self.logger.warning(
                f"[dm1q] Ignorando {part_name}: sem fs_config/file_contexts. "
                f"Não será incluída no super.img."
            )
            return


Aplicar o script abaixo resolve ambos automaticamente.
"""
