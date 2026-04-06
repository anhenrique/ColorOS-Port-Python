"""
PATCH para src/core/rom.py
Adiciona deteccao de Evolution X / ROMs AOSP como base.

INSTRUCOES:
  1. Em RomPackage, adicione as propriedades abaixo depois da propriedade is_coloros
  2. Em detect_device_code, adicione o caso dm1q conforme indicado
"""


# ============================================================
# ADICIONAR em RomPackage (depois de is_coloros):
# ============================================================

@property
def is_aosp_based(self) -> bool:
    """
    Detecta se e uma ROM baseada em AOSP puro (sem camada Oplus).
    Exemplos: Evolution X, LineageOS, PixelOS, crDroid, etc.

    ROMs AOSP nao tem:
      - ro.oplus.image.system_ext.area
      - ro.build.version.oplusrom
      - ro.oplus.image.system_ext.brand
    """
    has_oplus_area   = bool(self.get_prop("ro.oplus.image.system_ext.area"))
    has_oplus_rom    = bool(self.get_prop("ro.build.version.oplusrom"))
    has_oplus_brand  = bool(self.get_prop("ro.oplus.image.system_ext.brand"))
    return not (has_oplus_area or has_oplus_rom or has_oplus_brand)

@property
def is_evolution_x(self) -> bool:
    """Detecta Evolution X especificamente."""
    display_id = self.get_prop("ro.build.display.id") or ""
    evo_prop   = self.get_prop("ro.evolution.device") or ""
    evo_prop2  = self.get_prop("org.evolution.device") or ""
    return (
        "EvolutionX" in display_id
        or bool(evo_prop)
        or bool(evo_prop2)
    )

@property
def is_samsung_device(self) -> bool:
    """Detecta se e um dispositivo Samsung."""
    brand = (self.vendor_brand or "").lower()
    model = (self.product_model or "").upper()
    return brand == "samsung" or model.startswith("SM-")


# ============================================================
# SUBSTITUIR detect_device_code por esta versao:
# ============================================================

@classmethod
def detect_device_code(cls, rom_path, args_device_code=None):
    """
    Detecta device code do ROM.

    Priority:
    1. User provided (args_device_code)
    2. pre-device from ZIP metadata
    3. ro.product.vendor.device do build.prop (via ZIP)
    4. Filename patterns (inclui Samsung S23)
    5. None como fallback
    """
    import logging, re, zipfile
    from pathlib import Path
    logger = logging.getLogger(cls.__name__)

    if args_device_code:
        return args_device_code

    # Tenta metadata do ZIP
    try:
        with zipfile.ZipFile(rom_path, "r") as zf:
            metadata_path = "META-INF/com/android/metadata"
            if metadata_path in zf.namelist():
                with zf.open(metadata_path) as f:
                    content = f.read().decode("utf-8")
                    match = re.search(r"pre-device=(\S+)", content)
                    if match:
                        code = match.group(1)
                        logger.info(f"Device code from metadata: {code}")
                        return code
    except Exception as e:
        logger.debug(f"Falha ao ler metadata do ZIP: {e}")

    # Tenta pelo filename - inclui padroes Samsung Galaxy S23
    filename = Path(rom_path).name.upper()

    samsung_patterns = {
        # Galaxy S23 series
        "SM-S911": "dm1q",   "SM_S911": "dm1q",   "S911": "dm1q",
        "SM-S916": "dm2q",   "SM_S916": "dm2q",   "S916": "dm2q",
        "SM-S918": "dm3q",   "SM_S918": "dm3q",   "S918": "dm3q",
        # Galaxy S22 series
        "SM-S901": "r0q",    "SM_S901": "r0q",
        "SM-S906": "r11q",   "SM_S906": "r11q",
        "SM-S908": "r12s",   "SM_S908": "r12s",
        # Galaxy S24 series
        "SM-S921": "e1q",    "SM_S921": "e1q",
        "SM-S926": "e2q",    "SM_S926": "e2q",
        "SM-S928": "e3q",    "SM_S928": "e3q",
    }

    for pattern, code in samsung_patterns.items():
        if pattern in filename:
            logger.info(f"Device code do filename Samsung: {code}")
            return code

    # Fallback: pattern ColorOS original
    match = re.search(r"ColorOS_([^_]+)_", filename)
    if match:
        code = match.group(1)
        logger.info(f"Device code do filename ColorOS: {code}")
        return code

    return None
