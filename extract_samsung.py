import sys
import subprocess
import shutil
from pathlib import Path
 
# Importa a classe do módulo lpunpack.py que está na mesma pasta
try:
    from lpunpack import LpUnpack
except ImportError:
    print("❌ ERRO: O arquivo lpunpack.py não foi encontrado no diretório atual.")
    sys.exit(1)
 
def run_cmd(cmd: list, desc: str):
    print(f"⏳ {desc}...")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"❌ ERRO ao executar: {' '.join(cmd)}")
        sys.exit(1)
 
def main():
    if len(sys.argv) < 2:
        print("Uso: python3 extract_samsung.py <caminho_para_AP_xxx.tar.md5>")
        sys.exit(1)
 
    ap_file = sys.argv[1]
    temp_dir = Path("temp_samsung")
    assets_dir = Path("devices/chipset/SM8550/assets")
 
    print("📦 Iniciando Pipeline de Extração da Base Samsung (S23/dm1q)...")
    # Criar diretórios
    temp_dir.mkdir(exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
 
    # 1. Extração do TAR (Somente as partições vitais)
    files_to_extract = ["boot.img.lz4", "super.img.lz4", "vendor_boot.img.lz4", "init_boot.img.lz4"]
    run_cmd(["tar", "-xf", ap_file, "-C", str(temp_dir)] + files_to_extract, "Lendo o arquivo TAR e extraindo imagens")
 
    # 2. Descompactação do LZ4
    print("⚡ Descompactando imagens LZ4 (Isso pode levar alguns minutos)...")
    lz4_tasks = {
        "boot.img.lz4": "boot.img",
        "vendor_boot.img.lz4": "vendor_boot.img",
        "init_boot.img.lz4": "init_boot.img",
        "super.img.lz4": "super.img"
    }
    for lz4_file, img_file in lz4_tasks.items():
        src = temp_dir / lz4_file
        dst = temp_dir / img_file if img_file == "super.img" else assets_dir / img_file
        if src.exists():
            run_cmd(["lz4", "-d", "-f", str(src), str(dst)], f"Descompactando {lz4_file}")
            src.unlink() # Limpa o lz4 após extrair para economizar disco
 
    # 3. Extração Nativa com Python (LpUnpack)
    super_img_path = temp_dir / "super.img"
    if super_img_path.exists():
        print("🔪 Executando extração nativa das partições lógicas (LpUnpack)...")
        try:
            # Invoca a classe do lpunpack passando os argumentos esperados
            unpacker = LpUnpack(
                SUPER_IMAGE=str(super_img_path),
                OUTPUT_DIR=temp_dir,
                SHOW_INFO=False
            )
            unpacker.unpack()
        except Exception as e:
            print(f"❌ Falha crítica no módulo LpUnpack: {e}")
            sys.exit(1)
    # 4. Mover as partições de destino e tratar os sufixos (_a)
    print("🚚 Movendo partições críticas para a pasta assets...")
    vital_parts = ["odm", "vendor_dlkm", "vendor"]
    for part in vital_parts:
        # Tenta pegar sem sufixo ou com sufixo _a
        part_file = temp_dir / f"{part}.img"
        part_a_file = temp_dir / f"{part}_a.img"
        target = assets_dir / f"{part}.img"
        if part_file.exists():
            shutil.move(str(part_file), str(target))
        elif part_a_file.exists():
            shutil.move(str(part_a_file), str(target))
        else:
            print(f"⚠️ AVISO: Partição {part} não encontrada após a extração.")
 
    # 5. Limpeza do Stage
    print("🧹 Realizando limpeza da área temporária...")
    shutil.rmtree(temp_dir, ignore_errors=True)
    print("✅ Pipeline de deploy da base concluída com sucesso absoluto!")
 
if __name__ == "__main__":
    main()