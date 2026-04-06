"""
PATCH para src/core/props.py
Metodo _reconstruct_my_product_props corrigido para base AOSP (Evolution X).

O metodo original assume que a base tem my_product. Com Evolution X,
my_product nao existe. Este patch detecta isso e pula a reconstrucao
quando a base e AOSP.

INSTRUCOES:
  Substitua o metodo _reconstruct_my_product_props em src/core/props.py
  pelo metodo abaixo.
"""

def _reconstruct_my_product_props(self):
    """
    Reconstroi my_product/build.prop usando baserom como base e
    movendo props especificos do portrom para etc/bruce/build.prop.

    PATCH dm1q: Detecta base AOSP (Evolution X) onde my_product nao existe.
    Nesse caso, usa apenas o portrom como fonte e cria my_product do zero.
    """
    target_my_product = self.target_dir / "my_product"
    if not target_my_product.exists():
        return

    import logging
    logger = logging.getLogger(__name__)
    logger.info("Reconstituindo props de my_product...")

    # Carrega config de my_product
    my_product_config = self._config.get("my_product", {})
    force_keys = my_product_config.get("force_keys", [
        "ro.build.version.oplusrom",
        "ro.build.version.oplusrom.display",
        "ro.build.version.oplusrom.confidential",
        "ro.build.version.realmeui",
    ])
    import_line = my_product_config.get(
        "import_line",
        "import /mnt/vendor/my_product/etc/bruce/build.prop"
    )

    # Caminhos
    base_prop_file  = self._find_build_prop(self.ctx.baserom.extracted_dir / "my_product")
    port_prop_file  = self._find_build_prop(self.ctx.portrom.extracted_dir / "my_product")
    target_prop_main  = target_my_product / "build.prop"
    target_prop_bruce = target_my_product / "etc" / "bruce" / "build.prop"

    # --- PATCH: detecta se base e AOSP (sem my_product) ---
    base_is_aosp = not base_prop_file.exists()

    if base_is_aosp:
        logger.info(
            "  Base ROM e AOSP (sem my_product). "
            "Usando apenas portrom como fonte de my_product."
        )

    base_props = self._read_prop_to_dict(base_prop_file) if not base_is_aosp else {}
    port_props = self._read_prop_to_dict(port_prop_file)

    # Props que vao para bruce.prop:
    # - Se base e AOSP: todas as props do port (sem filtrar)
    # - Se base existe: somente force_keys e props exclusivos do port
    bruce_props = {}
    for key, value in port_props.items():
        if base_is_aosp or key in force_keys or key not in base_props:
            bruce_props[key] = value
            logger.debug(f"  bruce.prop <- {key}={value}")

    # Escreve prop principal
    if not base_is_aosp and base_prop_file.exists():
        import shutil
        shutil.copy2(base_prop_file, target_prop_main)
    elif port_prop_file.exists():
        # Base AOSP: usa portrom como base do main prop
        import shutil
        shutil.copy2(port_prop_file, target_prop_main)
    else:
        # Nenhuma fonte disponivel: cria prop minimo
        target_prop_main.write_text(
            "# my_product stub (dm1q AOSP compat)\n"
            "ro.product.my_product.device=dm1q\n",
            encoding="utf-8"
        )

    # Garante linha de import no prop principal
    content = target_prop_main.read_text(encoding="utf-8", errors="ignore")
    if import_line not in content:
        with open(target_prop_main, "a", encoding="utf-8") as f:
            f.write(f"\n\n# Bruce Property Patch\n{import_line}\n")

    # Escreve bruce.prop
    target_prop_bruce.parent.mkdir(parents=True, exist_ok=True)
    with open(target_prop_bruce, "w", encoding="utf-8") as f:
        f.write("# Props adicionados do Port ROM (dm1q AOSP compat)\n")
        for key in sorted(bruce_props.keys()):
            f.write(f"{key}={bruce_props[key]}\n")

    logger.info(
        f"  Reconstrucao concluida. "
        f"{len(bruce_props)} props em bruce/build.prop "
        f"({'base AOSP' if base_is_aosp else 'base+port merge'})"
    )
