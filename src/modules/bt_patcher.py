import subprocess
from pathlib import Path
import logging

def apply_bt_patch(context):
    logging.info("Iniciando BluetoothLibraryPatcher para S23 (dm1q)...")
    
    # Define os caminhos
    target_dir = Path("build/target")
    patch_script = Path("devices/target/dm1q/patch/bluetooth/hexpatch.sh")
    
    # O BluetoothLibraryPatcher geralmente atua em libs em /system ou /vendor [5]
    # No S23, o script v2.6.4 corrigiu problemas específicos [7]
    lib_path = target_dir / "vendor/lib64/libbluetooth.so" # Exemplo de caminho
    
    if not patch_script.exists():
        logging.error(f"Script {patch_script} não encontrado!")
        return False

    try:
        # Executa o hexpatch.sh passando o diretório da lib como argumento
        # Ignora funções de AI e Knox focando apenas no patch de pareamento [5, 8]
        result = subprocess.run(
            ["bash", str(patch_script), str(lib_path)],
            check=True, text=True
        )
        logging.info(f"Saída do Patcher: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Erro ao aplicar patch de Bluetooth: {e.stderr}")
        return False