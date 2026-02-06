#!/usr/bin/env python3
import os
import sys
import subprocess
import time
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_cmd(cmd, check=True):
    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        logger.error(f"Command failed: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result

def get_internal_disk():
    # Identify the largest non-removable disk
    lsblk = run_cmd(['lsblk', '-bndlo', 'NAME,SIZE,RM,TYPE']).stdout
    disks = []
    for line in lsblk.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] == '0' and parts[3] == 'disk':
            disks.append({'name': parts[0], 'size': int(parts[1])})
    
    if not disks:
        # Fallback to any disk that isn't the one we booted from
        # In live env, we boot from something usually named /dev/sdX or /dev/nvmeX
        # Let's just look for anything that isn't 'sda' if sda is the live media
        # More robust: list all disks and pick the largest one that isn't 'rm'
        raise RuntimeError("No internal (non-removable) disks found!")
    
    # Pick the largest one
    disks.sort(key=lambda x: x['size'], reverse=True)
    return f"/dev/{disks[0]['name']}"

def install_system(target_disk):
    logger.info(f"Targeting disk: {target_disk}")
    
    # 1. Wipe and partition
    run_cmd(['parted', '-s', target_disk, 'mklabel', 'gpt'])
    # BIOS Boot partition (for GRUB on GPT/BIOS)
    run_cmd(['parted', '-s', target_disk, 'mkpart', 'primary', '1MiB', '2MiB'])
    run_cmd(['parted', '-s', target_disk, 'set', '1', 'bios_grub', 'on'])
    # EFI System Partition
    run_cmd(['parted', '-s', target_disk, 'mkpart', 'primary', '2MiB', '512MiB'])
    run_cmd(['parted', '-s', target_disk, 'set', '2', 'esp', 'on'])
    # Root partition
    run_cmd(['parted', '-s', target_disk, 'mkpart', 'primary', '512MiB', '100%'])
    
    time.sleep(2) # Wait for kernel to update partitions
    
    p_prefix = "p" if "nvme" in target_disk else ""
    esp_part = f"{target_disk}{p_prefix}2"
    root_part = f"{target_disk}{p_prefix}3"

    logger.info("Formatting partitions...")
    run_cmd(['mkfs.vfat', '-F', '32', esp_part])
    run_cmd(['mkfs.ext4', '-F', root_part])

    # 2. Mount and copy
    target_mnt = Path('/mnt/target')
    target_mnt.mkdir(parents=True, exist_ok=True)
    
    run_cmd(['mount', root_part, str(target_mnt)])
    (target_mnt / 'boot' / 'efi').mkdir(parents=True, exist_ok=True)
    run_cmd(['mount', esp_part, str(target_mnt / 'boot' / 'efi')])

    logger.info("Cloning system (this may take a few minutes)...")
    # In live env, the system is in /run/live/rootfs/filesystem.squashfs mounted at /
    # We want to copy the running system but exclude virtual dirs
    run_cmd(['rsync', '-aAXHAX', '--info=progress2', '--exclude', '/proc/*', '--exclude', '/sys/*', 
             '--exclude', '/dev/*', '--exclude', '/run/*', '--exclude', '/tmp/*', 
             '--exclude', '/mnt/*', '--exclude', '/media/*', '--exclude', '/lost+found', '/', str(target_mnt)])

    # 3. Fix fstab
    logger.info("Updating fstab...")
    root_uuid = run_cmd(['blkid', '-s', 'UUID', '-o', 'value', root_part]).stdout.strip()
    esp_uuid = run_cmd(['blkid', '-s', 'UUID', '-o', 'value', esp_part]).stdout.strip()
    
    fstab_content = f"""
UUID={root_uuid} /               ext4    errors=remount-ro 0       1
UUID={esp_uuid}  /boot/efi       vfat    umask=0077      0       2
"""
    with open(target_mnt / 'etc' / 'fstab', 'w') as f:
        f.write(fstab_content)

    # 4. Install Bootloader
    logger.info("Installing GRUB...")
    # Bind mount virtual filesystems
    for d in ['dev', 'proc', 'sys', 'run']:
        run_cmd(['mount', '--bind', f'/{d}', str(target_mnt / d)])
    
    try:
        # Install for BIOS
        run_cmd(['chroot', str(target_mnt), 'grub-install', '--target=i386-pc', target_disk])
        # Install for UEFI
        run_cmd(['chroot', str(target_mnt), 'grub-install', '--target=x86_64-efi', '--efi-directory=/boot/efi', '--bootloader-id=debian', '--recheck'])
        # Update config
        run_cmd(['chroot', str(target_mnt), 'update-grub'])
    finally:
        # Unmount virtual filesystems
        for d in ['run', 'sys', 'proc', 'dev']:
            run_cmd(['umount', str(target_mnt / d)])

    # 5. Cleanup
    run_cmd(['umount', str(target_mnt / 'boot' / 'efi')])
    run_cmd(['umount', str(target_mnt)])
    logger.info("Installation complete! You can now reboot and remove the USB.")

def main():
    if os.getuid() != 0:
        print("Error: This script must be run as root.")
        sys.exit(1)

    print("====================================================")
    print("      Network Probe Internal Disk Installer         ")
    print("====================================================")
    
    try:
        disk = get_internal_disk()
    except Exception as e:
        logger.error(e)
        sys.exit(1)

    print(f"\nWARNING: This will wipe all data on {disk}!")
    confirm = input(f"Are you absolutely sure you want to proceed? (yes/N): ")
    if confirm.lower() != 'yes':
        print("Aborted.")
        sys.exit(0)

    try:
        install_system(disk)
        print("\nSUCCESS! System installed to internal disk.")
        print("You can shutdown now, remove the USB, and boot from the internal drive.")
    except Exception as e:
        logger.error(f"Installation failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
