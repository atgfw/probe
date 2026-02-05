#!/bin/bash
# Master build script for the Probe ISO

set -e

# Change to the iso-builder directory
cd "$(dirname "$0")/../iso-builder"

# Check for live-build
if ! command -v lb >/dev/null 2>&1; then
    echo "Error: live-build is not installed. Please run: sudo apt install live-build"
    exit 1
fi

echo "Cleaning up previous builds..."
sudo lb clean --all

echo "Configuring the build..."
lb config

echo "Starting the build process (this may take 15-30 minutes)..."
sudo lb build

echo "Build complete! The ISO file should be in the current directory."
