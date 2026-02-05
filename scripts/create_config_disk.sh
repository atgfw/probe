#!/bin/bash
# Create a small virtual config disk (FAT32) for VM testing
# This allows you to "plug in" a configuration to a VM without rebuilding the ISO

set -e

CONFIG_FILE="probe_config.txt"
IMG_FILE="probe_config.img"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: $CONFIG_FILE not found in current directory."
    exit 1
fi

# 1. Create a 10MB blank file
echo "Creating blank 10MB image..."
dd if=/dev/zero of="$IMG_FILE" bs=1M count=10 status=none

# 2. Format as FAT32
echo "Formatting as FAT32..."
mkfs.vfat "$IMG_FILE" > /dev/null

# 3. Use mtools to copy the file into the image without needing root/mount
if command -v mcopy >/dev/null 2>&1; then
    echo "Using mtools to copy $CONFIG_FILE into image..."
    mcopy -i "$IMG_FILE" "$CONFIG_FILE" ::/probe_config.txt
else
    echo "mtools not found. Attempting to use loop mount (requires sudo)..."
    TMP_MNT=$(mktemp -d)
    sudo mount -o loop "$IMG_FILE" "$TMP_MNT"
    sudo cp "$CONFIG_FILE" "$TMP_MNT/probe_config.txt"
    sudo umount "$TMP_MNT"
    rmdir "$TMP_MNT"
fi

echo "Success! Created '$IMG_FILE'."
echo "To use in a VM (VirtualBox/Proxmox/VMware):"
echo "  1. Add a second Hard Disk or Floppy Drive to your VM."
echo "  2. Select '$IMG_FILE' as the disk file."
echo "  3. Boot the probe-setup.iso."
