Skyworth / TrueID EROFS Toolkit
================================

ชุดเครื่องมือสำหรับ ROM ที่ EROFS tools ปกติแตกไม่ได้จาก codec mapping ของ Skyworth/TrueID บางรุ่น
และสำหรับแพ็กโฟลเดอร์ที่แตกแล้วกลับเป็น RAW EXT4 image

ไฟล์ในชุด
-----------
1. tool.sh
   เมนูภาษาไทยสำหรับเรียกใช้งานทั้งหมด

2. install.sh
   ติดตั้ง dependency บน Ubuntu / Debian / WSL
   - python3
   - zstd
   - e2fsprogs (mke2fs/e2fsck)
   - file

3. skyworth_erofs_unpack.py
   แตก EROFS -> folder พร้อม progress

4. skyworth_ext4_repack.py
   folder -> RAW EXT4 image
   คืน UID/GID/mode จาก EROFS ต้นฉบับเท่าที่รองรับ

เริ่มใช้งาน
-----------
chmod +x install.sh tool.sh
./install.sh
./tool.sh

หรือใช้ Python โดยตรง
----------------------
python3 skyworth_erofs_unpack.py system.img -o ~/system_unpack
sudo python3 skyworth_ext4_repack.py system.img ~/system_unpack

คำแนะนำ WSL
------------
ควรแตก EROFS ไปใน /home เช่น ~/system_unpack
ไม่ควรแตกลง /mnt/c หรือ /mnt/d ถ้าต้องการเก็บ Linux symlink จริง

ข้อจำกัดสำคัญ
--------------
- EXT4 output เป็น RAW image ไม่ใช่ Android sparse image
- repacker คืน UID/GID/mode จาก original EROFS
- security.selinux / xattrs และ AVB footer ยังไม่ได้ rebuild ครบ
- ถ้า fstab ของเครื่องบังคับ filesystem เป็น EROFS ต้องแก้ส่วนที่เกี่ยวข้องก่อนใช้ EXT4 ในการบูต

โปรเจกต์นี้ควรทดสอบกับ image สำรองก่อนแฟลชทุกครั้ง
