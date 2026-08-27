# Skyworth / TrueID EROFS Toolkit

Toolkit for extracting vendor-patched Skyworth / TrueID EROFS images and rebuilding the extracted directory as a RAW EXT4 image.

This project was created for ROM images where normal `fsck.erofs --extract` may fail on vendor-specific compressed EROFS data.

---

## Features

- Extract Skyworth / TrueID EROFS `.img` files
- Supports the vendor-specific ZSTD mapping used by tested Skyworth / TrueID images
- Progress bar while extracting
- Preserves Linux symlinks when extracting inside WSL/Linux filesystem
- Rebuild extracted folders as RAW EXT4 images
- Restores original UID / GID / file mode from the original EROFS image where possible
- Automatic EXT4 image size calculation
- EXT4 filesystem verification with `e2fsck`
- Thai interactive menu with `tool.sh`
- Works on Ubuntu / Debian / WSL

---

## Included Files

```text
Skyworth-EROFS-Toolkit/
├── tool.sh
├── install.sh
├── skyworth_erofs_unpack.py
├── skyworth_ext4_repack.py
├── README.md
└── README_TH.txt
```

### File description

| File | Description |
|---|---|
| `tool.sh` | Thai interactive menu |
| `install.sh` | Installs all required Linux tools |
| `skyworth_erofs_unpack.py` | EROFS image extractor |
| `skyworth_ext4_repack.py` | Rebuilds an unpacked directory as RAW EXT4 |
| `README.md` | Main usage guide |
| `README_TH.txt` | Short Thai notes |

---

# 1. Requirements

Recommended environment:

- Ubuntu
- Debian
- WSL Ubuntu / Debian
- Python 3

Required Linux tools:

- `python3`
- `zstd`
- `e2fsprogs`
  - `mke2fs`
  - `e2fsck`
- `file`

No Python `pip` packages are required.

---

# 2. Installation

Enter the toolkit directory:

```bash
cd Skyworth-EROFS-Toolkit
```

Make scripts executable:

```bash
chmod +x install.sh tool.sh
```

Install all dependencies:

```bash
./install.sh
```

The installer automatically runs:

```bash
sudo apt update
sudo apt install -y python3 zstd e2fsprogs file
```

It also verifies that these commands are available:

```text
python3
zstd
mke2fs
e2fsck
file
```

---

# 3. Thai Menu

Start the interactive menu:

```bash
./tool.sh
```

The menu provides options similar to:

```text
1) ติดตั้งเครื่องมือที่จำเป็น
2) แตกไฟล์ EROFS .img
3) แพ็กโฟลเดอร์กลับเป็น EXT4 .img
4) เช็กประเภทไฟล์ .img
5) แสดงตัวอย่างคำสั่ง
0) ออก
```

This is the easiest method for normal use.

---

# 4. Extract EROFS Image

## Basic command

```bash
python3 skyworth_erofs_unpack.py system.img
```

If you run the command from a Windows drive under WSL such as:

```text
/mnt/c/
/mnt/d/
```

the extractor may automatically prefer the Linux home directory for output so Linux symlinks work correctly.

Example output directory:

```text
/home/username/system_unpack
```

or:

```bash
~/system_unpack
```

---

## Specify output directory manually

```bash
python3 skyworth_erofs_unpack.py system.img -o ~/system_unpack
```

Examples:

### System

```bash
python3 skyworth_erofs_unpack.py system.img -o ~/system_unpack
```

### Vendor

```bash
python3 skyworth_erofs_unpack.py vendor.img -o ~/vendor_unpack
```

### Product

```bash
python3 skyworth_erofs_unpack.py product.img -o ~/product_unpack
```

### System Ext

```bash
python3 skyworth_erofs_unpack.py system_ext.img -o ~/system_ext_unpack
```

### Vendor DLKM

```bash
python3 skyworth_erofs_unpack.py vendor_dlkm.img -o ~/vendor_dlkm_unpack
```

---

# 5. Extraction Progress

The extractor scans the filesystem first:

```text
[SCAN] reading filesystem tree...
[SCAN] entries found: 2,652 — done
```

Then shows information such as:

```text
[SCAN] files=2,181 dirs=218 symlinks=253 logical-data=1.3 GiB
```

During extraction:

```text
[████████--------------------]  31.42%
[██████████████--------------]  52.16%
[██████████████████████------]  81.77%
[████████████████████████████] 100.00%
```

Successful extraction ends with:

```text
[OK] extracted to: /home/username/system_unpack
[OK] files=2181 dirs=218 symlinks=253 markers=0
```

---

# 6. WSL and Symlinks

Android partitions contain many Linux symlinks.

Example:

```text
bin -> /system/bin
```

Windows NTFS mounted through WSL may reject Linux symlink creation.

Because of this, it is strongly recommended to extract to the WSL Linux filesystem:

```bash
python3 skyworth_erofs_unpack.py system.img -o ~/system_unpack
```

Do not normally extract directly to:

```text
/mnt/c/...
/mnt/d/...
```

if you need a complete Linux filesystem tree.

---

# 7. View Extracted Files

Example:

```bash
cd ~/system_unpack
ls -lah
```

Check total size:

```bash
du -sh ~/system_unpack
```

Find APK files:

```bash
find ~/system_unpack -type f -name "*.apk"
```

Find build properties:

```bash
find ~/system_unpack -type f -name "build.prop"
```

---

# 8. Edit Files

After extraction you may modify files inside the unpacked directory.

Example:

```bash
nano ~/system_unpack/system/build.prop
```

or copy a replacement file:

```bash
cp MyApp.apk ~/system_unpack/system/app/MyApp/MyApp.apk
```

Make sure the replacement path is correct before repacking.

---

# 9. Repack to RAW EXT4

The repacker uses:

1. Original EROFS image
2. Unpacked directory
3. Original metadata
4. `mke2fs`
5. `e2fsck`

Command format:

```bash
sudo python3 skyworth_ext4_repack.py <original.img> <unpacked_folder>
```

---

## System

```bash
sudo python3 skyworth_ext4_repack.py system.img ~/system_unpack
```

Output:

```text
system_ext4.img
```

---

## Vendor

```bash
sudo python3 skyworth_ext4_repack.py vendor.img ~/vendor_unpack
```

Output:

```text
vendor_ext4.img
```

---

## Product

```bash
sudo python3 skyworth_ext4_repack.py product.img ~/product_unpack
```

Output:

```text
product_ext4.img
```

---

## System Ext

```bash
sudo python3 skyworth_ext4_repack.py system_ext.img ~/system_ext_unpack
```

Output:

```text
system_ext_ext4.img
```

---

## Vendor DLKM

```bash
sudo python3 skyworth_ext4_repack.py vendor_dlkm.img ~/vendor_dlkm_unpack
```

Output:

```text
vendor_dlkm_ext4.img
```

---

# 10. Why the Original Image Is Required During Repack

Do not delete the original EROFS image before repacking.

For example:

```text
system.img
```

is still required even after:

```text
~/system_unpack
```

has already been created.

The repacker reads the original EROFS metadata and attempts to restore:

```text
UID
GID
file mode / permissions
```

to the EXT4 filesystem.

If the original image is missing or replaced with another filesystem, the repacker may report:

```text
ValueError: not EROFS
```

---

# 11. Repack Progress

Typical output:

```text
[1/6] Scanning unpacked directory...
[SCAN] files=2,181 dirs=219 symlinks=252 data=1.3 GiB

[2/6] Copying unpacked tree to staging...
[████████████████████████████] 100.00%

[3/6] Restoring UID/GID/mode from original EROFS...
[████████████████████████████] 100.00%

[4/6] Building raw EXT4 image...
[██████----------------------]  22.40%  Building EXT4
[██████████████--------------]  52.00%  Building EXT4
[███████████████████████████-]  99.00%  Building EXT4
[████████████████████████████] 100.00%  Building EXT4

[5/6] Checking EXT4 filesystem...
[CHECK] e2fsck ... OK

[6/6] Done
[SUCCESS]
```

The `Building EXT4` percentage is an estimate because `mke2fs` does not provide a native percentage.

The script keeps the displayed progress at a maximum of `99%` until `mke2fs` actually exits successfully.

---

# 12. Automatic EXT4 Size

By default the repacker automatically calculates an EXT4 image size based on the extracted data.

Example:

```text
[SCAN] data=1.3 GiB
[SIZE] raw EXT4 target = 1904 MiB
```

You normally do not need to specify the size manually.

---

## Force EXT4 size

Example: 2048 MiB

```bash
sudo python3 skyworth_ext4_repack.py system.img ~/system_unpack --size-mb 2048
```

Be careful not to choose a size smaller than the actual unpacked data.

---

# 13. Custom Output Name

Example:

```bash
sudo python3 skyworth_ext4_repack.py system.img ~/system_unpack -o system_new.img
```

---

# 14. EXT4 Filesystem Label

By default the label is based on the original image name.

Examples:

```text
system.img      -> system
vendor.img      -> vendor
product.img     -> product
```

Set a custom label:

```bash
sudo python3 skyworth_ext4_repack.py system.img ~/system_unpack --label system
```

---

# 15. EXT4 Journal

The default generated image does not use an EXT4 journal.

To enable a journal:

```bash
sudo python3 skyworth_ext4_repack.py system.img ~/system_unpack --with-journal
```

---

# 16. Verify an Image

Use:

```bash
file system.img
```

Example original EROFS output:

```text
EROFS filesystem
```

Example generated output:

```text
Linux rev 1.0 ext4 filesystem data
```

You can also inspect the EROFS magic manually:

```bash
xxd -s 1024 -l 16 system.img
```

EROFS magic should begin with:

```text
e2 e1 f5 e0
```

---

# 17. Verify Generated EXT4

Run:

```bash
sudo e2fsck -f system_ext4.img
```

or:

```bash
file system_ext4.img
```

The repacker already performs an automatic `e2fsck` check before reporting success.

---

# 18. Common Errors

## `PermissionError: Operation not permitted`

Example:

```text
PermissionError: [Errno 1] Operation not permitted
```

Usually caused by extracting Linux symlinks to `/mnt/c` or `/mnt/d`.

Use:

```bash
python3 skyworth_erofs_unpack.py system.img -o ~/system_unpack
```

---

## `Permission denied` while extracting again

If an older extraction left read-only Android files, remove the old directory first:

```bash
sudo chmod -R u+rwX ~/system_unpack 2>/dev/null
sudo rm -rf ~/system_unpack
```

Then extract again.

---

## `ValueError: not EROFS`

Check:

```bash
file system.img
```

The first argument to the repacker must be the original EROFS image.

---

## `zstd not found`

Install:

```bash
sudo apt install -y zstd
```

or simply:

```bash
./install.sh
```

---

## `mke2fs not found`

Install:

```bash
sudo apt install -y e2fsprogs
```

---

## WSL `Catastrophic failure`

Try from Windows CMD or PowerShell:

```bat
wsl --shutdown
wsl --update
wsl -d Ubuntu
```

Do not run:

```bat
wsl --unregister Ubuntu
```

unless you intentionally want to delete the WSL distribution and its Linux files.

---

# 19. Useful WSL Paths

Windows:

```text
D:\TEMP\ROM\
```

Inside WSL:

```text
/mnt/d/TEMP/ROM/
```

WSL home:

```bash
~
```

Example:

```text
/home/username/
```

Recommended workflow:

```text
Original IMG:
    /mnt/d/TEMP/ROM/system.img

Extracted directory:
    ~/system_unpack

Generated EXT4:
    /mnt/d/TEMP/ROM/system_ext4.img
```

---

# 20. Recommended Workflow

```text
system.img
   │
   ▼
skyworth_erofs_unpack.py
   │
   ▼
~/system_unpack
   │
   ├── Edit / replace files
   │
   ▼
skyworth_ext4_repack.py
   │
   ▼
system_ext4.img
```

Commands:

```bash
python3 skyworth_erofs_unpack.py system.img -o ~/system_unpack
```

Edit files.

Then:

```bash
sudo python3 skyworth_ext4_repack.py system.img ~/system_unpack
```

Wait until:

```text
[SUCCESS]
```

---

# 21. Important Limitations

The generated image is:

```text
RAW EXT4
```

It is not automatically:

```text
Android sparse image
```

The current repacker restores original:

- UID
- GID
- Linux file mode

where possible.

The current tool does **not** rebuild all Android security metadata such as:

- `security.selinux` xattrs
- all Linux capabilities / security xattrs
- AVB footer / hash tree
- vbmeta signatures

Also, if the device fstab explicitly requires:

```text
erofs
```

changing only the partition image to EXT4 may not be enough for the device to boot.

Before flashing a modified image, verify:

- partition filesystem support
- dynamic partition size
- fstab
- AVB / vbmeta configuration
- SELinux metadata requirements

---

# 22. Tested Image Types

The extractor was developed and tested against Skyworth / TrueID Android TV EROFS images, including partitions such as:

```text
system
system_ext
vendor
vendor_dlkm
```

Other EROFS images may use different compression layouts or filesystem features.

---

# 23. Direct Command Cheat Sheet

Install:

```bash
chmod +x install.sh tool.sh
./install.sh
```

Menu:

```bash
./tool.sh
```

Extract:

```bash
python3 skyworth_erofs_unpack.py system.img -o ~/system_unpack
```

Repack:

```bash
sudo python3 skyworth_ext4_repack.py system.img ~/system_unpack
```

Check:

```bash
file system.img
file system_ext4.img
```

Check EXT4:

```bash
sudo e2fsck -f system_ext4.img
```

---

# 24. Safety

Always keep a backup of the original firmware images.

Do not delete the original EROFS image until the repack process is finished.

Flashing an incorrect Android partition image may cause boot failure and may require recovery using the device's original firmware or flashing tools.

---

## License / Credits

Use and modify this toolkit at your own risk.

Designed for Skyworth / TrueID Android TV firmware research and ROM development.
