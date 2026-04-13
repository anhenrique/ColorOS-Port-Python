#!/bin/bash
# Script para automatizar a extração e compressão da partição my_product

IMG_FILE="build/target/my_product.img"
TEMP_DIR="./temp_my_product"
TARGET_DIR="devices/target/dm1q"
BIN_PATH="./bin/linux/x86_64" # Caminho das ferramentas do ColorOS-Port-Python [3]

echo "📂 Extraindo $IMG_FILE..."
# erofsUnpackRust é a ferramenta ideal para processar partições EROFS [1]
$BIN_PATH/erofsUnpackRust "$IMG_FILE" "$TEMP_DIR"

if [ -d "$TEMP_DIR" ]; then
    echo "📦 Criando my_product.zip..."
    cd "$TEMP_DIR" || exit
    zip -r ../my_product.zip .
    cd ..
    
    # Move para a pasta do dispositivo onde o replacements.json o encontrará
    mv my_product.zip "$TARGET_DIR/"
    rm -rf "$TEMP_DIR"
    echo "✅ Sucesso: $TARGET_DIR/my_product.zip está pronto!"
else
    echo "❌ Erro: Falha ao extrair a imagem."
    exit 1
fi