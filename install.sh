#!/usr/bin/env bash
# Skyworth / TrueID EROFS Toolkit - Dependency Installer
# For Ubuntu / Debian / WSL
#
# Installs everything required by the Python unpack/repack tools:
#   - python3
#   - zstd
#   - e2fsprogs  (mke2fs, e2fsck)
#   - file       (handy image-type verification)
#
# No pip packages are required.

set -Eeuo pipefail

C_RESET='\033[0m'
C_GREEN='\033[1;32m'
C_YELLOW='\033[1;33m'
C_RED='\033[1;31m'
C_CYAN='\033[1;36m'

info()  { printf "${C_CYAN}[INFO]${C_RESET} %s\n" "$*"; }
ok()    { printf "${C_GREEN}[ OK ]${C_RESET} %s\n" "$*"; }
warn()  { printf "${C_YELLOW}[WARN]${C_RESET} %s\n" "$*"; }
error() { printf "${C_RED}[ERROR]${C_RESET} %s\n" "$*" >&2; }

echo "=================================================="
echo " Skyworth / TrueID EROFS Toolkit - install.sh"
echo "=================================================="

# Must be Linux (WSL is fine).
if [[ "$(uname -s)" != "Linux" ]]; then
    error "This installer is for Linux / Ubuntu / Debian / WSL only."
    exit 1
fi

if grep -qi microsoft /proc/version 2>/dev/null; then
    info "WSL detected."
fi

# Debian/Ubuntu package manager.
if ! command -v apt-get >/dev/null 2>&1; then
    error "apt-get was not found."
    error "Supported installer targets: Ubuntu, Debian, and WSL Ubuntu/Debian."
    exit 1
fi

# Use sudo only when not already root.
if [[ "${EUID}" -eq 0 ]]; then
    SUDO=""
else
    if ! command -v sudo >/dev/null 2>&1; then
        error "sudo is required when install.sh is not run as root."
        exit 1
    fi
    SUDO="sudo"
fi

PACKAGES=(
    python3
    zstd
    e2fsprogs
    file
)

echo
info "Updating package index..."
$SUDO apt-get update

echo
info "Installing required packages:"
printf '  - %s\n' "${PACKAGES[@]}"
$SUDO apt-get install -y "${PACKAGES[@]}"

echo
info "Verifying tools..."

FAIL=0

check_tool() {
    local cmd="$1"
    local desc="$2"

    if command -v "$cmd" >/dev/null 2>&1; then
        ok "$desc -> $(command -v "$cmd")"
    else
        error "$desc ($cmd) not found after installation."
        FAIL=1
    fi
}

check_tool python3 "Python 3"
check_tool zstd    "Zstandard"
check_tool mke2fs "EXT4 builder"
check_tool e2fsck  "EXT4 checker"
check_tool file    "File type checker"

echo

if [[ "$FAIL" -ne 0 ]]; then
    error "Installation finished, but one or more required tools are missing."
    exit 1
fi

echo "=================================================="
ok "All required tools are installed."
echo "=================================================="

python3 --version
zstd --version 2>/dev/null | head -n 1 || true
mke2fs -V 2>&1 | head -n 1 || true
e2fsck -V 2>&1 | head -n 1 || true

echo
echo "Ready."
echo
echo "Examples:"
echo "  python3 skyworth_erofs_unpack.py system.img"
echo "  sudo python3 skyworth_ext4_repack.py system.img ~/system_unpack"
echo
echo "No Python pip packages are required."
