#!/bin/bash
echo "🚀 Iniciando o processo de portabilidade para o DM1Q (Android 16)..."

TMPDIR=/root/ColorOS-Port-Python/mytmp/ python3 main.py --baserom roms/base_unzip/images  --portrom roms/op12r-16.zip  --device_code dm1q