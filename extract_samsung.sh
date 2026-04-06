#!/bin/bash

AP_FILE=$1

if [ -z "$AP_FILE" ]; then
  echo "Uso: ./extract_samsung.sh <caminho_para_o_arquivo_AP_xxx.tar.md5>"
  exit 1
fi

echo "📦 Iniciando extração blindada com ferramentas nativas do Ubuntu..."
mkdir -p temp_samsung
mkdir -p devices/chipset/SM8550/assets

echo "🗜️ Lendo o arquivo TAR e extraindo imagens vitais..."
tar -xf "$AP_FILE" -C temp_samsung boot.img.lz4 super.img.lz4 vendor_boot.img.lz4 init_boot.img.lz4

echo "⚡ Descompactando imagens LZ4..."
lz4 -d -f temp_samsung/boot.img.lz4 devices/chipset/SM8550/assets/boot.img
lz4 -d -f temp_samsung/vendor_boot.img.lz4 devices/chipset/SM8550/assets/vendor_boot.img
lz4 -d -f temp_samsung/init_boot.img.lz4 devices/chipset/SM8550/assets/init_boot.img
lz4 -d -f temp_samsung/super.img.lz4 temp_samsung/super.img

echo "🔄 Convertendo super.img para RAW (Usando simg2img nativo)..."
# Agora se falhar, veremos o erro real no terminal
simg2img temp_samsung/super.img temp_samsung/super.raw.img

if [ -f "temp_samsung/super.raw.img" ] && [ -s "temp_samsung/super.raw.img" ]; then
    echo "✅ Imagem convertida para formato RAW com sucesso."
    SUPER_TARGET="temp_samsung/super.raw.img"
else
    echo "❌ ERRO: Falha catastrófica no simg2img. Abortando deploy."
    exit 1
fi

echo "🔪 Executando lpunpack no super.raw.img..."
./bin/lpunpack "$SUPER_TARGET" temp_samsung/

if ls temp_samsung/odm*.img 1> /dev/null 2>&1; then
    echo "🚚 Movendo partições dinâmicas para assets..."
    mv temp_samsung/odm*.img devices/chipset/SM8550/assets/odm.img
    mv temp_samsung/vendor_dlkm*.img devices/chipset/SM8550/assets/vendor_dlkm.img
    
    echo "🧹 Limpando o ambiente temporário..."
    rm -rf temp_samsung
    echo "✅ Deploy da base concluído! A fundação do sistema está pronta."
else
    echo "❌ ERRO CRÍTICO: O lpunpack falhou em extrair as partições."
    exit 1
fi