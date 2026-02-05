#!/usr/bin/env python3
"""
System Verification Script

Verifies all components of the probe discovery system:
1. Gatekeeper API connectivity
2. NetBox connection and custom field
3. SSH access to proxy
4. AWX callback URL (if configured)

Usage:
    python3 verify_system.py
"""

import os
import sys
import logging
import requests
import subprocess
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_environment_vars():
    """Check required environment variables."""
    logger.info("=" * 60)
    logger.info("Checking environment variables...")
    logger.info("=" * 60)

    required = {
        'NETBOX_URL': False,
        'NETBOX_TOKEN': False,
        'GATEKEEPER_URL': True,
        'AWX_CALLBACK_URL': True,
        'PROXY_HOST': True
    }

    for var, optional in required.items():
        value = os.getenv(var)
        if value:
            status = "✓"
            required[var] = True
            # Mask token in output
            if 'TOKEN' in var or 'PASSWORD' in var:
                logger.info(f"{status} {var}: ***set***")
            else:
                logger.info(f"{status} {var}: {value}")
        elif optional:
            status = "○"
            logger.warning(f"{status} {var}: not set (optional)")
        else:
            status = "✗"
            logger.error(f"{status} {var}: not set (required)")
            return False

    return True


def check_gatekeeper():
    """Check Gatekeeper API health."""
    logger.info("=" * 60)
    logger.info("Checking Gatekeeper API...")
    logger.info("=" * 60)

    gatekeeper_url = os.getenv("GATEKEEPER_URL", "http://localhost:8000")

    try:
        response = requests.get(f"{gatekeeper_url}/health", timeout=5)
        response.raise_for_status()
        data = response.json()

        logger.info(f"✓ Gatekeeper is healthy")
        logger.info(f"  Status: {data['status']}")
        logger.info(f"  NetBox Connected: {data['netbox_connected']}")
        logger.info(f"  URL: {gatekeeper_url}")
        return True

    except requests.RequestException as e:
        logger.error(f"✗ Gatekeeper health check failed: {e}")
        return False


def test_port_request():
    """Test port request endpoint."""
    logger.info("=" * 60)
    logger.info("Testing port request...")
    logger.info("=" * 60)

    gatekeeper_url = os.getenv("GATEKEEPER_URL", "http://localhost:8000")
    test_mac = "00:11:22:33:44:55"

    try:
        response = requests.get(
            f"{gatekeeper_url}/provision/request-port",
            params={"mac": test_mac},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        logger.info(f"✓ Port request successful")
        logger.info(f"  MAC: {data['mac']}")
        logger.info(f"  Port: {data['port']}")
        logger.info(f"  Existing: {data['existing']}")
        return True

    except requests.RequestException as e:
        logger.error(f"✗ Port request failed: {e}")
        return False


def check_netbox():
    """Check NetBox connectivity and custom field."""
    logger.info("=" * 60)
    logger.info("Checking NetBox...")
    logger.info("=" * 60)

    netbox_url = os.getenv("NETBOX_URL")
    netbox_token = os.getenv("NETBOX_TOKEN")

    if not netbox_url or not netbox_token:
        logger.error("✗ NETBOX_URL or NETBOX_TOKEN not set")
        return False

    try:
        # Check API access
        headers = {"Authorization": f"Token {netbox_token}"}
        response = requests.get(f"{netbox_url}/api/", headers=headers, timeout=10)
        response.raise_for_status()

        logger.info(f"✓ NetBox API accessible")
        logger.info(f"  URL: {netbox_url}")

        # Check for custom field
        response = requests.get(
            f"{netbox_url}/api/extras/custom-fields/",
            headers=headers,
            params={"name": "automation_proxy_port"},
            timeout=10
        )

        if response.status_code == 200 and response.json()['results']:
            logger.info(f"✓ Custom field 'automation_proxy_port' exists")
        else:
            logger.warning(f"○ Custom field 'automation_proxy_port' not found")

        # Try to get devices
        response = requests.get(
            f"{netbox_url}/api/dcim/devices/",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()

        device_count = response.json()['count']
        logger.info(f"  Total devices: {device_count}")

        return True

    except requests.RequestException as e:
        logger.error(f"✗ NetBox check failed: {e}")
        return False


def check_proxy_ssh():
    """Check SSH access to proxy."""
    logger.info("=" * 60)
    logger.info("Checking Proxy SSH access...")
    logger.info("=" * 60)

    proxy_host = os.getenv("PROXY_HOST")
    proxy_user = os.getenv("PROXY_USER", "tunnelmgr")

    if not proxy_host:
        logger.warning("○ PROXY_HOST not set, skipping SSH check")
        return True

    try:
        # Test SSH connection
        result = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=5",
                "-o", "StrictHostKeyChecking=no",
                f"{proxy_user}@{proxy_host}",
                "echo 'SSH connection successful'"
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            logger.info(f"✓ SSH to {proxy_user}@{proxy_host} successful")

            # Check autossh installation
            result = subprocess.run(
                ["ssh", f"{proxy_user}@{proxy_host}", "which autossh"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                logger.info(f"✓ autossh installed on proxy")
            else:
                logger.warning(f"○ autossh not found on proxy")

            return True

        else:
            logger.error(f"✗ SSH to {proxy_user}@{proxy_host} failed: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error(f"✗ SSH to proxy timed out")
        return False
    except Exception as e:
        logger.error(f"✗ SSH check failed: {e}")
        return False


def check_dependencies():
    """Check Python dependencies."""
    logger.info("=" * 60)
    logger.info("Checking Python dependencies...")
    logger.info("=" * 60)

    required_modules = [
        "fastapi",
        "uvicorn",
        "pynetbox",
        "requests",
        "cryptography"
    ]

    all_found = True

    for module in required_modules:
        try:
            __import__(module)
            logger.info(f"✓ {module}")
        except ImportError:
            logger.error(f"✗ {module} not installed")
            all_found = False

    return all_found


def check_files():
    """Check required files exist."""
    logger.info("=" * 60)
    logger.info("Checking required files...")
    logger.info("=" * 60)

    script_dir = Path(__file__).parent.parent
    required_files = [
        "gatekeeper.py",
        "bootstrap_probe.py",
        "requirements.txt",
        "README.md"
    ]

    all_found = True

    for file in required_files:
        file_path = script_dir / file
        if file_path.exists():
            logger.info(f"✓ {file}")
        else:
            logger.error(f"✗ {file} not found")
            all_found = False

    # Check directories
    dirs = ["playbooks", "scripts"]
    for dir_name in dirs:
        dir_path = script_dir / dir_name
        if dir_path.exists() and dir_path.is_dir():
            logger.info(f"✓ {dir_name}/")
        else:
            logger.warning(f"○ {dir_name}/ not found")

    return all_found


def print_summary(results):
    """Print verification summary."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("VERIFICATION SUMMARY")
    logger.info("=" * 60)

    total = len(results)
    passed = sum(results.values())

    for check, status in results.items():
        symbol = "✓" if status else "✗"
        logger.info(f"{symbol} {check}")

    logger.info("")
    logger.info(f"Passed: {passed}/{total}")

    if passed == total:
        logger.info("All checks passed! System is ready.")
        return 0
    else:
        logger.warning(f"{total - passed} check(s) failed. Review errors above.")
        return 1


def main():
    """Main verification flow."""
    logger.info("Probe Discovery System Verification")
    logger.info("")

    results = {}

    # Run all checks
    results["Environment Variables"] = check_environment_vars()
    results["Python Dependencies"] = check_dependencies()
    results["Required Files"] = check_files()
    results["Gatekeeper API"] = check_gatekeeper()
    results["Port Request Test"] = test_port_request()
    results["NetBox Connection"] = check_netbox()
    results["Proxy SSH Access"] = check_proxy_ssh()

    # Print summary
    exit_code = print_summary(results)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
