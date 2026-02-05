#!/usr/bin/env python3
"""
Setup NetBox prerequisites for the probe system.

Creates:
- Custom field: automation_proxy_port
- Sites: pending, remote-site
- Manufacturer: Generic
- Device Type: network-probe
- Device Role: network-probe
"""

import os
import sys
from dotenv import load_dotenv
import pynetbox

load_dotenv()

# Get NetBox connection info
NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")

# Ensure URL has https://
if NETBOX_URL and not NETBOX_URL.startswith("http"):
    NETBOX_URL = f"https://{NETBOX_URL}"

print(f"Connecting to NetBox at {NETBOX_URL}...")

try:
    nb = pynetbox.api(NETBOX_URL, NETBOX_TOKEN)
    # Test connection
    nb.status()
    print("✓ Connected to NetBox")
except Exception as e:
    print(f"✗ Failed to connect to NetBox: {e}")
    sys.exit(1)


def create_if_not_exists(endpoint, name, slug, **extra):
    """Create an object if it doesn't exist."""
    existing = list(endpoint.filter(slug=slug))
    if existing:
        print(f"  ✓ {name} already exists")
        return existing[0]
    
    try:
        obj = endpoint.create(name=name, slug=slug, **extra)
        print(f"  + Created {name}")
        return obj
    except Exception as e:
        print(f"  ✗ Failed to create {name}: {e}")
        return None


print("\n1. Creating sites...")
pending_site = create_if_not_exists(
    nb.dcim.sites,
    name="Pending",
    slug="pending",
    status="planned",
    description="Probes awaiting full registration"
)

remote_site = create_if_not_exists(
    nb.dcim.sites,
    name="Remote Site",
    slug="remote-site",
    status="active",
    description="Default site for registered probes"
)


print("\n2. Creating manufacturer...")
manufacturer = create_if_not_exists(
    nb.dcim.manufacturers,
    name="Generic",
    slug="generic"
)


print("\n3. Creating device type...")
if manufacturer:
    existing_types = list(nb.dcim.device_types.filter(slug="network-probe"))
    if existing_types:
        print("  ✓ network-probe device type already exists")
        device_type = existing_types[0]
    else:
        try:
            device_type = nb.dcim.device_types.create(
                manufacturer=manufacturer.id,
                model="Network Probe",
                slug="network-probe"
            )
            print("  + Created network-probe device type")
        except Exception as e:
            print(f"  ✗ Failed to create device type: {e}")


print("\n4. Creating device role...")
existing_roles = list(nb.dcim.device_roles.filter(slug="network-probe"))
if existing_roles:
    print("  ✓ network-probe role already exists")
else:
    try:
        nb.dcim.device_roles.create(
            name="Network Probe",
            slug="network-probe",
            color="4caf50"  # Green
        )
        print("  + Created network-probe role")
    except Exception as e:
        print(f"  ✗ Failed to create role: {e}")


print("\n5. Creating custom field (automation_proxy_port)...")
try:
    # Check if custom field exists
    existing_cf = list(nb.extras.custom_fields.filter(name="automation_proxy_port"))
    if existing_cf:
        print("  ✓ automation_proxy_port custom field already exists")
    else:
        # Get the content type for dcim.device
        cf = nb.extras.custom_fields.create(
            name="automation_proxy_port",
            label="Automation Proxy Port",
            type="integer",
            object_types=["dcim.device"],
            required=False,
            description="SSH tunnel port for probe access via proxy"
        )
        print("  + Created automation_proxy_port custom field")
except Exception as e:
    print(f"  ✗ Failed to create custom field: {e}")


print("\n" + "="*50)
print("Setup complete!")
print("="*50)
