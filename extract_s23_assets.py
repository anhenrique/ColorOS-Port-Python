import os
import shutil
import subprocess
from pathlib import Path

def extract_s23_base(baserom_zip, output_dir="devices/chipset/SM8550/assets"):
    """
    Extrai as partições críticas da OneUI para servirem de base no port da ColorOS 16.
    """
    print(f"🚀 Iniciando extração da base Samsung S23: {baserom_zip}")
    
    # 1. Setup de pastas
    temp_dir = Path("temp_extraction")
    assets_path = Path(output_dir)
    assets_path.mkdir(parents=True, exist_ok=True)
    
    # 2. Extrair o zip da Samsung (procurando pelo payload.bin)
    # Assumindo que você tem o payload-dumper no seu path ou na pasta bin
    try:
        print("📦 Extraindo partições críticas (odm, vendor, vendor_dlkm)...")
        # Comando hipotético usando o dumper do repo
        subprocess.run(["python3", "bin/payload_dumper.py", baserom_zip, "--out", str(temp_dir)], check=True)
        
        # 3. Mover o que é vital para o S23
        critical_images = ["odm.img", "vendor_dlkm.img", "boot.img", "dtbo.img"]
        for img in critical_images:
            src = temp_dir / img
            if src.exists():
                shutil.move(str(src), str(assets_path / img))
                print(f"✅ {img} extraído para assets.")
            else:
                print(f"⚠️ Aviso: {img} não encontrado na base.")

    except Exception as e:
        print(f"❌ Erro na extração: {e}")
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

if __name__ == "__main__":
    # Ajuste o caminho para o seu arquivo da OneUI
    extract_s23_base("caminho/para/sua/rom_samsung_s23.zip")