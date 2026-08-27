#!/usr/bin/env bash
# Skyworth / TrueID EROFS Toolkit - เมนูภาษาไทย
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNPACK="$DIR/skyworth_erofs_unpack.py"
REPACK="$DIR/skyworth_ext4_repack.py"
INSTALL="$DIR/install.sh"

GREEN='\033[1;32m'
CYAN='\033[1;36m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
RESET='\033[0m'

pause_menu() {
  echo
  read -r -p "กด Enter เพื่อกลับเมนู..." _
}

clean_path() {
  local p="$1"
  p="${p%\"}"; p="${p#\"}"
  p="${p%\'}"; p="${p#\'}"
  printf '%s' "$p"
}

banner() {
  clear 2>/dev/null || true
  echo -e "${CYAN}====================================================${RESET}"
  echo -e "${CYAN}     Skyworth / TrueID EROFS Toolkit - ภาษาไทย${RESET}"
  echo -e "${CYAN}====================================================${RESET}"
  echo "  1) ติดตั้งเครื่องมือที่จำเป็น"
  echo "  2) แตกไฟล์ EROFS .img"
  echo "  3) แพ็กโฟลเดอร์กลับเป็น EXT4 .img"
  echo "  4) เช็กประเภทไฟล์ .img"
  echo "  5) แสดงตัวอย่างคำสั่ง"
  echo "  0) ออก"
  echo -e "${CYAN}====================================================${RESET}"
}

install_tools() {
  echo
  echo -e "${YELLOW}[ติดตั้ง] กำลังเรียก install.sh${RESET}"
  chmod +x "$INSTALL" 2>/dev/null || true
  "$INSTALL"
}

unpack_img() {
  echo
  read -r -p "ใส่ path ไฟล์ EROFS .img: " img
  img="$(clean_path "$img")"
  if [[ ! -f "$img" ]]; then
    echo -e "${RED}[ผิดพลาด] ไม่พบไฟล์: $img${RESET}"
    return
  fi

  local stem out
  stem="$(basename "$img")"
  stem="${stem%.*}"
  out="$HOME/${stem}_unpack"

  echo
  echo "ไฟล์ต้นฉบับ : $img"
  echo "โฟลเดอร์ออก : $out"
  read -r -p "กด Enter เพื่อใช้ตำแหน่งนี้ หรือพิมพ์ path ใหม่: " custom
  if [[ -n "$custom" ]]; then
    out="$(clean_path "$custom")"
  fi

  echo
  echo -e "${CYAN}[UNPACK] เริ่มแตกไฟล์...${RESET}"
  python3 "$UNPACK" "$img" -o "$out"
}

repack_img() {
  echo
  read -r -p "ใส่ path ไฟล์ EROFS ต้นฉบับ .img: " img
  img="$(clean_path "$img")"
  if [[ ! -f "$img" ]]; then
    echo -e "${RED}[ผิดพลาด] ไม่พบไฟล์: $img${RESET}"
    return
  fi

  local stem folder
  stem="$(basename "$img")"
  stem="${stem%.*}"
  folder="$HOME/${stem}_unpack"

  echo "โฟลเดอร์ unpack ค่าเริ่มต้น: $folder"
  read -r -p "กด Enter เพื่อใช้ค่านี้ หรือพิมพ์ path โฟลเดอร์ใหม่: " custom
  if [[ -n "$custom" ]]; then
    folder="$(clean_path "$custom")"
  fi

  if [[ ! -d "$folder" ]]; then
    echo -e "${RED}[ผิดพลาด] ไม่พบโฟลเดอร์: $folder${RESET}"
    return
  fi

  echo
  echo "ต้นฉบับ : $img"
  echo "โฟลเดอร์: $folder"
  echo -e "${YELLOW}ตัว repack ต้องใช้ sudo เพื่อคืน UID/GID/mode จาก ROM เดิม${RESET}"
  echo
  sudo python3 "$REPACK" "$img" "$folder"
}

check_img() {
  echo
  read -r -p "ใส่ path ไฟล์ .img: " img
  img="$(clean_path "$img")"
  if [[ ! -f "$img" ]]; then
    echo -e "${RED}[ผิดพลาด] ไม่พบไฟล์: $img${RESET}"
    return
  fi
  echo
  file "$img"
  echo
  echo "EROFS magic @ 1024:"
  if command -v xxd >/dev/null 2>&1; then
    xxd -s 1024 -l 16 "$img" || true
  else
    od -An -tx1 -j1024 -N16 "$img" || true
  fi
}

examples() {
  cat <<EOF2

ตัวอย่างคำสั่งตรง:

  แตก EROFS:
    python3 skyworth_erofs_unpack.py system.img -o ~/system_unpack

  แพ็ก EXT4:
    sudo python3 skyworth_ext4_repack.py system.img ~/system_unpack

  Vendor:
    python3 skyworth_erofs_unpack.py vendor.img -o ~/vendor_unpack
    sudo python3 skyworth_ext4_repack.py vendor.img ~/vendor_unpack

  Product:
    python3 skyworth_erofs_unpack.py product.img -o ~/product_unpack
    sudo python3 skyworth_ext4_repack.py product.img ~/product_unpack

หมายเหตุ:
  - แนะนำให้แตกไฟล์ไปที่ ~/..._unpack เพื่อให้ Linux symlink ทำงานปกติ
  - EXT4 ที่สร้างเป็น RAW image
  - การเปลี่ยน EROFS -> EXT4 อาจต้องแก้ fstab/AVB/SELinux เพิ่มก่อนแฟลชจริง
EOF2
}

while true; do
  banner
  read -r -p "เลือกเมนู [0-5]: " choice
  case "$choice" in
    1) install_tools; pause_menu ;;
    2) unpack_img; pause_menu ;;
    3) repack_img; pause_menu ;;
    4) check_img; pause_menu ;;
    5) examples; pause_menu ;;
    0) echo -e "${GREEN}ออกจากโปรแกรม${RESET}"; exit 0 ;;
    *) echo -e "${RED}กรุณาเลือก 0-5${RESET}"; sleep 1 ;;
  esac
done
