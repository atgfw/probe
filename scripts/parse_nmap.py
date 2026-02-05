#!/usr/bin/env python3
"""
Parse Nmap XML Output for NetBox IPAM Sync

This script parses nmap XML output and outputs JSON formatted data
for importing discovered IP addresses into NetBox.

Usage:
    python3 parse_nmap.py <scan.xml> <tenant_slug>

Output:
    JSON array of discovered hosts with IP addresses, MACs, and hostnames
"""

import sys
import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_nmap_xml(xml_file: str) -> List[Dict]:
    """
    Parse nmap XML output and extract discovered hosts.

    Args:
        xml_file: Path to nmap XML file

    Returns:
        List of discovered hosts with IP, MAC, and hostname
    """
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()

        hosts = []

        for host in root.findall('.//host'):
            host_info = {
                'ip': None,
                'mac': None,
                'hostname': None,
                'status': None,
                'vendor': None
            }

            # Get host status
            status_elem = host.find('status')
            if status_elem is not None:
                host_info['status'] = status_elem.get('state')

            if host_info['status'] != 'up':
                continue

            # Get IP address
            address = host.find('.//address[@addrtype="ipv4"]')
            if address is not None:
                host_info['ip'] = address.get('addr')

            # Get MAC address
            mac = host.find('.//address[@addrtype="mac"]')
            if mac is not None:
                host_info['mac'] = mac.get('addr')
                host_info['vendor'] = mac.get('vendor')

            # Get hostname
            hostname = host.find('.//hostname')
            if hostname is not None:
                host_info['hostname'] = hostname.get('name')

            # Only add if we have at least an IP or MAC
            if host_info['ip'] or host_info['mac']:
                hosts.append(host_info)

        logger.info(f"Parsed {len(hosts)} hosts from {xml_file}")
        return hosts

    except ET.ParseError as e:
        logger.error(f"Error parsing XML: {e}")
        raise
    except FileNotFoundError:
        logger.error(f"File not found: {xml_file}")
        raise


def format_for_netbox(hosts: List[Dict], tenant_slug: str) -> List[Dict]:
    """
    Format discovered hosts for NetBox IPAM import.

    Args:
        hosts: List of discovered hosts
        tenant_slug: Tenant identifier for NetBox

    Returns:
        Formatted list for NetBox API
    """
    formatted = []

    for host in hosts:
        # Skip hosts with no IP address (can't create IPAM entry)
        if not host['ip']:
            continue

        entry = {
            'address': f"{host['ip']}/24",  # Assume /24 for now
            'tenant': tenant_slug,
            'status': 'active',
            'description': f"Discovered via probe scan"
        }

        if host['hostname']:
            entry['dns_name'] = host['hostname']

        if host['mac']:
            entry['description'] += f" (MAC: {host['mac']})"

        if host['vendor']:
            entry['description'] += f" [{host['vendor']}]"

        formatted.append(entry)

    logger.info(f"Formatted {len(formatted)} hosts for NetBox")
    return formatted


def main():
    """
    Main execution flow.
    """
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <scan.xml> <tenant_slug>", file=sys.stderr)
        sys.exit(1)

    xml_file = sys.argv[1]
    tenant_slug = sys.argv[2]

    try:
        # Parse nmap XML
        hosts = parse_nmap_xml(xml_file)

        # Format for NetBox
        formatted = format_for_netbox(hosts, tenant_slug)

        # Output JSON
        output = {
            'tenant': tenant_slug,
            'scan_timestamp': datetime.utcnow().isoformat(),
            'discovered_count': len(hosts),
            'hosts': formatted
        }

        print(json.dumps(output, indent=2))

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
