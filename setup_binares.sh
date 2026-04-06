#!/bin/bash

echo "⚙️ Iniciando o provisionamento via mirror alternativo..."
mkdir -p bin/

# URL base do repositório público LonelyX (focado em OTA tools)
BASE_URL="https://github.com/LonelyX/otatools/raw/main/bin"

echo "📥 Baixando lpmake..."
wget -q --show-progress -O bin/lpmake "$BASE_URL/lpmake"

echo "📥 Baixando lpunpack..."
wget -q --show-progress -O bin/lpunpack "$BASE_URL/lpunpack"

echo "📥 Baixando make_erofs..."
wget -q --show-progress -O bin/mkfs.erofs "$BASE_URL/make_erofs"

echo "📥 Baixando simg2img..."
wget -q --show-progress -O bin/simg2img "$BASE_URL/simg2img"

echo "📥 Baixando img2simg..."
wget -q --show-progress -O bin/img2simg "$BASE_URL/img2simg"

echo "🔒 Aplicando permissões de execução (+x)..."
chmod +x -R bin/

echo "✅ Ambiente de ferramentas configurado com sucesso!"
echo "Teste rápido do EROFS:"
./bin/mkfs.erofs -V