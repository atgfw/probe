#!/usr/bin/env python3
"""
Probe Bootstrap Script - First-Boot Registration

This script runs on first boot of a probe to register it with the system:
1. Read tenant configuration
2. Get MAC address
3. Request proxy port from Gatekeeper
4. Generate SSH key pair
5. Create autossh systemd service
6. Call AWX provisioning callback

Author: Probe Discovery System
License: MIT
"""

import os
import sys
import json
import logging
import subprocess
import socket
from pathlib import Path
from datetime import datetime

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.backends import default_backend

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration search paths (ordered by preference)
CONFIG_PATHS = [
    "/boot/probe_config.txt",
    "/run/live/medium/probe_config.txt", # Boot media in Debian Live
    "/boot/firmware/probe_config.txt",   # Common on some Debian/RPi variants
    "/mnt/probe_config.txt",
]
NETWORK_INTERFACE = "eth0"
SSH_DIR = Path.home() / ".ssh"
SSH_KEY = SSH_DIR / "id_ed25519"
SSH_PUB_KEY = SSH_DIR / "id_ed25519.pub"
SYSTEMD_DIR = Path("/etc/systemd/system")

# Environment variables or defaults
# Note: These are baked into the ISO but can be overridden by env vars
GATEKEEPER_URL = os.getenv("GATEKEEPER_URL", "http://167.99.59.231:8000")
AWX_CALLBACK_URL = os.getenv("AWX_CALLBACK_URL", "https://awx.atgfw.com/api/v2/job_templates/45/callback/")
AWX_HOST_CONFIG_KEY = os.getenv("AWX_HOST_CONFIG_KEY", "probe-bootstrap-atg-2026")
PROXY_HOST = os.getenv("PROXY_HOST", "167.99.59.231")
PROXY_USER = os.getenv("PROXY_USER", "tunnelmgr")


def slugify(text: str) -> str:
    """
    Convert text to a URL-safe slug (lowercase, underscores).
    
    Args:
        text: Input string
        
    Returns:
        Slugified string
    """
    if not text:
        return ""
    import re
    # Lowercase, replace all non-alphanumeric characters with underscores
    text = text.lower().strip()
    text = re.sub(r'[^\w]+', '_', text)
    # Collapse consecutive underscores and strip them from the ends
    text = re.sub(r'_+', '_', text)
    return text.strip('_')


def read_config() -> tuple:
    """
    Read TENANT_NAME/SLUG and SITE_NAME/SLUG from available config paths.

    Returns:
        Tuple of (tenant_name, tenant_slug, site_name, site_slug)

    Raises:
        RuntimeError: If no config file found or tenant info not found
    """
    tenant_name = None
    tenant_slug = None
    site_name = None
    site_slug = None

    for config_path in CONFIG_PATHS:
        path = Path(config_path)
        if not path.exists():
            continue

        logger.info(f"Checking config at: {config_path}")
        try:
            with open(path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                        
                    if '=' in line:
                        key, val = line.split('=', 1)
                        key = key.strip()
                        val = val.strip().strip('"\'')
                        
                        if key == 'TENANT_NAME': tenant_name = val
                        elif key == 'TENANT_SLUG': tenant_slug = val
                        elif key == 'SITE_NAME': site_name = val
                        elif key == 'SITE_SLUG': site_slug = val
            
            # Prioritize Names and derive slugs if missing
            if tenant_name:
                derived_tenant_slug = tenant_slug if tenant_slug else slugify(tenant_name)
                # Site defaults to tenant if missing
                final_site_name = site_name if site_name else tenant_name
                final_site_slug = site_slug if site_slug else (slugify(site_name) if site_name else derived_tenant_slug)
                
                logger.info(f"Loaded config: Tenant='{tenant_name}' ({derived_tenant_slug}), Site='{final_site_name}' ({final_site_slug})")
                return tenant_name, derived_tenant_slug, final_site_name, final_site_slug
            
            # Fallback to pure slug if that's all we have (backwards compat)
            if tenant_slug:
                final_site_slug = site_slug if site_slug else tenant_slug
                return tenant_slug.title(), tenant_slug, (site_slug.title() if site_slug else tenant_slug.title()), final_site_slug

        except Exception as e:
            logger.warning(f"Error reading {config_path}: {e}")

    raise RuntimeError(f"Tenant configuration not found in any of: {', '.join(CONFIG_PATHS)}")


def get_mac_address(interface: str = NETWORK_INTERFACE) -> str:
    """
    Get the MAC address of the specified network interface.

    Args:
        interface: Network interface name (default: eth0)

    Returns:
        MAC address string

    Raises:
        RuntimeError: If interface not found or MAC address cannot be retrieved
    """
    try:
        # Try /sys/class/net first (most reliable on Linux)
        sys_path = Path(f"/sys/class/net/{interface}/address")

        if sys_path.exists():
            mac = sys_path.read_text().strip()
            logger.info(f"MAC address from sysfs: {mac}")
            return mac

        # Fallback to ip command
        result = subprocess.run(
            ['ip', 'link', 'show', interface],
            capture_output=True,
            text=True,
            check=True
        )

        for line in result.stdout.split('\n'):
            if 'link/ether' in line:
                mac = line.split()[1]
                logger.info(f"MAC address from ip command: {mac}")
                return mac

        raise RuntimeError(f"Could not find MAC address for interface {interface}")

    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ip command: {e}")
        raise RuntimeError(f"Interface {interface} not found")


def request_proxy_port(mac: str) -> int:
    """
    Request a proxy port from the Gatekeeper API.

    Args:
        mac: Probe MAC address

    Returns:
        Assigned proxy port number

    Raises:
        RuntimeError: If API request fails
    """
    url = f"{GATEKEEPER_URL}/provision/request-port"
    params = {"mac": mac}

    try:
        logger.info(f"Requesting proxy port from {url}")
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        port = data.get('port')

        if not port or not isinstance(port, int):
            raise RuntimeError(f"Invalid port in response: {data}")

        logger.info(f"Assigned proxy port: {port}")
        return port

    except requests.RequestException as e:
        logger.error(f"Error requesting proxy port: {e}")
        raise RuntimeError(f"Failed to request proxy port: {e}")


def generate_ssh_key_pair() -> str:
    """
    Generate Ed25519 SSH key pair if it doesn't exist.

    Returns:
        Public key string

    Raises:
        RuntimeError: If key generation fails
    """
    if SSH_KEY.exists() and SSH_PUB_KEY.exists():
        logger.info(f"SSH key already exists: {SSH_KEY}")
        return SSH_PUB_KEY.read_text().strip()

    try:
        # Create .ssh directory if needed
        SSH_DIR.mkdir(mode=0o700, exist_ok=True)

        logger.info("Generating new Ed25519 SSH key pair")

        # Generate private key
        private_key = ed25519.Ed25519PrivateKey.generate()
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        # Write private key
        SSH_KEY.write_bytes(private_pem)
        SSH_KEY.chmod(0o600)

        # Generate public key
        public_key = private_key.public_key()
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH
        )

        # Write public key
        SSH_PUB_KEY.write_text(public_bytes.decode('utf-8') + '\n')
        SSH_PUB_KEY.chmod(0o644)

        logger.info(f"SSH key pair generated: {SSH_KEY}")
        return public_bytes.decode('utf-8')

    except Exception as e:
        logger.error(f"Error generating SSH keys: {e}")
        raise RuntimeError(f"Failed to generate SSH keys: {e}")


def create_autossh_service(port: int) -> None:
    """
    Create systemd service file for autossh reverse tunnel.

    Args:
        port: Assigned proxy port

    Raises:
        RuntimeError: If service file creation or enablement fails
    """
    service_name = f"autossh-probe-{port}.service"
    service_path = SYSTEMD_DIR / service_name

    service_content = f"""[Unit]
Description=Autossh reverse tunnel to proxy
After=network.target

[Service]
Environment="AUTOSSH_GATETIME=0"
User=root
ExecStart=/usr/bin/autossh -M 0 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=no -N -R {port}:localhost:22 {PROXY_USER}@{PROXY_HOST}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""

    try:
        logger.info(f"Creating systemd service: {service_path}")

        # Write service file
        service_path.write_text(service_content)
        service_path.chmod(0o644)

        # Reload systemd, enable, and start service
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', service_name], check=True)
        subprocess.run(['systemctl', 'start', service_name], check=True)

        logger.info(f"Systemd service {service_name} created, enabled, and started")

    except subprocess.CalledProcessError as e:
        logger.error(f"Error managing systemd service: {e}")
        raise RuntimeError(f"Failed to create systemd service: {e}")


def call_awx_callback(mac: str, proxy_port: int, t_name: str, t_slug: str, s_name: str, s_slug: str, public_key: str) -> None:
    """
    Call AWX provisioning callback URL.

    Args:
        mac: Probe MAC address
        proxy_port: Assigned proxy port
        t_name: Tenant Display Name
        t_slug: Tenant URL-safe slug
        s_name: Site Display Name
        s_slug: Site URL-safe slug
        public_key: SSH public key

    Raises:
        RuntimeError: If callback URL not configured or request fails
    """
    if not AWX_CALLBACK_URL:
        logger.warning("AWX_CALLBACK_URL not configured, skipping callback")
        return

    payload = {
        "mac": mac,
        "proxy_port": proxy_port,
        "tenant_name": t_name,
        "tenant_slug": t_slug,
        "site_name": s_name,
        "site_slug": s_slug,
        "public_key": public_key,
        "hostname": socket.gethostname(),
        "timestamp": datetime.utcnow().isoformat(),
        "host_config_key": AWX_HOST_CONFIG_KEY
    }

    try:
        logger.info(f"Calling AWX callback: {AWX_CALLBACK_URL}")
        response = requests.post(
            AWX_CALLBACK_URL,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()

        logger.info("AWX callback successful")

    except requests.RequestException as e:
        logger.error(f"Error calling AWX callback: {e}")
        raise RuntimeError(f"Failed to call AWX callback: {e}")


def write_bootstrap_complete(port: int) -> None:
    """
    Write bootstrap completion marker.

    Args:
        port: Assigned proxy port
    """
    marker_path = Path("/var/lib/probe_bootstrap_complete")
    marker_content = f"""bootstrap_timestamp={datetime.utcnow().isoformat()}
proxy_port={port}
"""

    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(marker_content)
        logger.info(f"Bootstrap marker written: {marker_path}")
    except Exception as e:
        logger.warning(f"Could not write bootstrap marker: {e}")


def main():
    """
    Main bootstrap execution flow.
    """
    logger.info("=" * 60)
    logger.info("Starting probe bootstrap process")
    logger.info("=" * 60)

    try:
        # Step 1: Read configuration
        logger.info("Step 1: Reading configuration")
        t_name, t_slug, s_name, s_slug = read_config()

        # Step 2: Get MAC address
        logger.info("Step 2: Getting MAC address")
        mac = get_mac_address()

        # Step 3: Request proxy port
        logger.info("Step 3: Requesting proxy port from Gatekeeper")
        proxy_port = request_proxy_port(mac)

        # Step 4: Generate SSH key pair
        logger.info("Step 4: Generating SSH key pair")
        public_key = generate_ssh_key_pair()

        # Step 5: Create autossh service
        logger.info("Step 5: Creating autossh systemd service")
        create_autossh_service(proxy_port)

        # Step 6: Call AWX callback
        logger.info("Step 6: Calling AWX provisioning callback")
        call_awx_callback(mac, proxy_port, t_name, t_slug, s_name, s_slug, public_key)

        # Step 7: Mark bootstrap complete
        logger.info("Step 7: Writing bootstrap completion marker")
        write_bootstrap_complete(proxy_port)

        logger.info("=" * 60)
        logger.info("Bootstrap completed successfully!")
        logger.info(f"  Tenant: {t_name} ({t_slug})")
        logger.info(f"  Site:   {s_name} ({s_slug})")
        logger.info(f"  MAC: {mac}")
        logger.info(f"  Proxy Port: {proxy_port}")
        logger.info(f"  Service: autossh-probe-{proxy_port}.service")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"Bootstrap failed: {e}")
        logger.error("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
