import zipfile
from pathlib import Path

def pack_s23_blobs(img_dir="devices/chipset/SM8550/assets"):
    assets_path = Path(img_dir)
    zip_path = assets_path / "s23_blobs.zip"
    
    # Imagens que o seu replacements.json precisa processar
    critical_images = ["odm.img", "vendor_dlkm.img", "boot.img", "dtbo.img"]
    
    print(f"📦 Criando {zip_path.name}...")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for img in critical_images:
            img_path = assets_path / img
            if img_path.exists():
                # Adiciona ao zip mantendo apenas o nome do arquivo na raiz do zip
                zipf.write(img_path, arcname=img)
                print(f"✅ Adicionado: {img}")
            else:
                print(f"⚠️ Aviso: {img} não encontrado em {assets_path}")

    print("🚀 Compactação concluída para o Stage 3!")

if __name__ == "__main__":
    pack_s23_blobs()