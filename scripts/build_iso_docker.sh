#!/bin/bash
# Docker wrapper for the Probe ISO build process
# This allows building the Debian ISO on any OS (Arch, Fedora, Mac, etc.)

set -e

# Change to the project root
cd "$(dirname "$0")/.."

# Check for docker
if ! command -v docker >/dev/null 2>&1; then
    echo "Error: docker is not installed."
    echo "On Arch: sudo pacman -S docker && sudo systemctl enable --now docker"
    exit 1
fi

echo "Pulling Debian build environment..."
docker pull debian:bookworm

echo "Starting the ISO build process in a privileged container..."
docker run --privileged --rm -it \
  -v "$(pwd)":/build \
  -w /build/iso-builder \
  debian:bookworm \
  bash -c "apt update && apt install -y live-build && lb clean --all && lb config && lb build"

echo "Build process finished."
if [ -f iso-builder/live-image-amd64.hybrid.iso ]; then
    mv iso-builder/live-image-amd64.hybrid.iso ./probe-setup.iso
    echo "Success! ISO moved to: ./probe-setup.iso"
else
    echo "Error: ISO file was not found in the builder directory."
    exit 1
fi
