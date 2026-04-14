#!/bin/bash
echo "🚀 Iniciando o processo de portabilidade para o DM1Q (Android 16)..."

#TMPDIR=/root/ColorOS-Port-Python/mytmp/ python3 main.py --baserom roms/base_unzip/images  --portrom roms/op11-16.zip  --device_code dm1q

TMPDIR=/root/ColorOS-Port-Python/mytmp/ python3 main_s23.py --baserom roms/gnsf/downloads/AP_S911BXXS9EZC1_S911BXXS9EZC1_MQB107205664_REV00_user_low_ship_MULTI_CERT_meta_OS16.tar.md5 --portrom roms/op11-16.zip --device dm1q #--output out/dm1q_op16.zip --pack_type super 