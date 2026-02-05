#!/usr/bin/env python3
"""
Gatekeeper - FastAPI Service for NetBox Port Assignments

Manages proxy port assignments for remote probes connecting via
reverse SSH tunnels to the DigitalOcean proxy.

Author: Probe Discovery System
License: MIT
"""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import pynetbox
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="Gatekeeper API",
    description="NetBox port assignment manager for probe registration",
    version="1.0.0"
)

# Configuration
NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")
DEFAULT_START_PORT = 10001
CUSTOM_FIELD_NAME = "automation_proxy_port"


# Initialize NetBox connection
try:
    nb = pynetbox.api(NETBOX_URL, NETBOX_TOKEN)
    logger.info(f"Connected to NetBox at {NETBOX_URL}")
except Exception as e:
    logger.error(f"Failed to connect to NetBox: {e}")
    nb = None


# Response models
class PortResponse(BaseModel):
    mac: str = Field(..., description="Probe MAC address")
    port: int = Field(..., description="Assigned proxy port")
    existing: bool = Field(..., description="Whether port was pre-existing")
    device_name: Optional[str] = Field(None, description="NetBox device name")
    timestamp: str = Field(..., description="Response timestamp")


class ErrorResponse(BaseModel):
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")


def normalize_mac(mac: str) -> str:
    """
    Normalize MAC address format to lowercase with colons.

    Args:
        mac: MAC address in various formats

    Returns:
        Normalized MAC address (lowercase, colon-separated)
    """
    mac = mac.lower()
    # Remove any separators
    mac_clean = mac.replace(':', '').replace('-', '').replace('.', '')

    # Validate length
    if len(mac_clean) != 12:
        raise ValueError(f"Invalid MAC address length: {len(mac_clean)}")

    # Add colons
    return ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])


def get_max_assigned_port() -> int:
    """
    Find the maximum assigned automation_proxy_port in NetBox.

    Returns:
        Maximum port number currently assigned
    """
    if not nb:
        raise RuntimeError("NetBox connection not available")

    try:
        devices = nb.dcim.devices.all()
        max_port = DEFAULT_START_PORT - 1

        for device in devices:
            port = device.custom_fields.get(CUSTOM_FIELD_NAME)
            if port and isinstance(port, int):
                max_port = max(max_port, port)

        logger.info(f"Current max assigned port: {max_port}")
        return max_port
    except Exception as e:
        logger.error(f"Error getting max port: {e}")
        raise


def find_device_by_mac(mac: str) -> Optional[Dict[str, Any]]:
    """
    Find a NetBox device by MAC address.

    Supports NetBox 4.0+ where MAC addresses are separate objects,
    as well as older versions where MAC is a field on interfaces.

    Args:
        mac: Normalized MAC address

    Returns:
        Device object or None if not found
    """
    if not nb:
        raise RuntimeError("NetBox connection not available")

    try:
        # NetBox 4.0+: MAC addresses are separate objects in dcim.mac-addresses
        # Query the MAC address object directly
        try:
            mac_addresses = nb.dcim.mac_addresses.filter(mac_address=mac)
            for mac_obj in mac_addresses:
                # MAC address objects link to interfaces via assigned_object
                if hasattr(mac_obj, 'assigned_object') and mac_obj.assigned_object:
                    interface = mac_obj.assigned_object
                    if hasattr(interface, 'device') and interface.device:
                        logger.info(f"Found device via MAC address object: {interface.device.name}")
                        return nb.dcim.devices.get(interface.device.id)
        except AttributeError:
            # nb.dcim.mac_addresses doesn't exist - older NetBox version
            logger.debug("MAC address objects not available, trying legacy lookup")

        # Legacy/fallback: Search interfaces by mac_address field (pre-4.0)
        try:
            interfaces = nb.dcim.interfaces.filter(mac_address=mac)
            for interface in interfaces:
                if interface.device:
                    logger.info(f"Found device via interface MAC field: {interface.device.name}")
                    return nb.dcim.devices.get(interface.device.id)
        except Exception as e:
            logger.debug(f"Interface MAC lookup failed: {e}")

        # Fallback: Check custom field mac_address on devices
        devices = nb.dcim.devices.filter(cf_mac_address=mac)
        for device in devices:
            logger.info(f"Found device via custom field: {device.name}")
            return device

        # Last resort: Check if device name contains MAC (naming convention)
        mac_clean = mac.replace(':', '')
        devices = nb.dcim.devices.all()
        for device in devices:
            if mac_clean in device.name.lower().replace(':', '').replace('-', ''):
                logger.info(f"Found device via name matching: {device.name}")
                return device

        return None
    except Exception as e:
        logger.error(f"Error searching for device by MAC {mac}: {e}")
        raise


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint.
    """
    return {
        "status": "healthy",
        "netbox_connected": nb is not None,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get(
    "/provision/request-port",
    response_model=PortResponse,
    responses={
        500: {"model": ErrorResponse, "description": "NetBox connection error"}
    },
    tags=["Provisioning"]
)
async def request_port(
    mac: str = Query(..., description="Probe MAC address (eth0)")
):
    """
    Request a proxy port assignment for a probe.

    If the MAC address exists in NetBox, return the existing port.
    Otherwise, assign the next available port (max + 1, starting at 10001).

    Args:
        mac: Probe MAC address

    Returns:
        Port assignment details

    Raises:
        HTTPException: On validation or NetBox errors
    """
    # Normalize MAC address
    try:
        mac_normalized = normalize_mac(mac)
    except ValueError as e:
        logger.error(f"Invalid MAC address: {mac}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid MAC address: {e}"
        )

    logger.info(f"Port request for MAC: {mac_normalized}")

    # Check NetBox connection
    if not nb:
        logger.error("NetBox connection not available")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NetBox connection not available"
        )

    # Try to find existing device by MAC
    device = find_device_by_mac(mac_normalized)
    existing_device = None

    if device:
        # Check for existing port assignment
        existing_port = device.custom_fields.get(CUSTOM_FIELD_NAME)
        if existing_port and isinstance(existing_port, int):
            logger.info(f"Found existing port {existing_port} for MAC {mac_normalized}")
            return PortResponse(
                mac=mac_normalized,
                port=existing_port,
                existing=True,
                device_name=device.name,
                timestamp=datetime.utcnow().isoformat()
            )
        existing_device = device

    # Assign new port and create pending device in NetBox
    try:
        max_port = get_max_assigned_port()
        new_port = max_port + 1

        logger.info(f"Assigning new port {new_port} to MAC {mac_normalized}")

        # Create a pending device in NetBox to reserve the port atomically
        # The register_probe playbook will update this device with full details
        device_name = f"probe-{mac_normalized.replace(':', '')}"
        
        if existing_device:
            # Device exists but has no port - update it
            existing_device.custom_fields[CUSTOM_FIELD_NAME] = new_port
            existing_device.save()
            logger.info(f"Updated existing device {existing_device.name} with port {new_port}")
            created_device_name = existing_device.name
        else:
            # Create new pending device with minimal info
            # Note: MAC address object is created by register_probe playbook
            new_device = nb.dcim.devices.create(
                name=device_name,
                device_type="network-probe",  # Must exist in NetBox
                role="network-probe",      # Must exist in NetBox
                site="pending",            # Placeholder site for pending probes
                status="planned",          # Indicates pending registration
                custom_fields={
                    CUSTOM_FIELD_NAME: new_port,
                },
            )
            logger.info(f"Created pending device {device_name} with port {new_port}")
            created_device_name = device_name

        return PortResponse(
            mac=mac_normalized,
            port=new_port,
            existing=False,
            device_name=created_device_name,
            timestamp=datetime.utcnow().isoformat()
        )

    except Exception as e:
        logger.error(f"Error assigning port: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to assign port: {e}"
        )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Global exception handler.
    """
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error", "detail": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("GATEKEEPER_PORT", "8000"))
    host = os.getenv("GATEKEEPER_HOST", "0.0.0.0")

    logger.info(f"Starting Gatekeeper API on {host}:{port}")

    uvicorn.run(
        "gatekeeper:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
