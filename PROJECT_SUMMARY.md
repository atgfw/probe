# Project Summary

## Zero-Touch Network Discovery System

### What Was Created

This project provides a complete zero-touch provisioning and network discovery system for managing 200+ remote probes connecting via reverse SSH tunnels.

---

## File Structure

```
~/probe/
│
├── Core Components
│   ├── gatekeeper.py                 # FastAPI service for NetBox port assignments
│   ├── bootstrap_probe.py            # Probe first-boot registration script
│   ├── requirements.txt              # Python dependencies
│   └── .env.example                 # Environment variables template
│
├── Ansible Playbooks
│   ├── setup_infrastructure.yml     # Initial infrastructure setup
│   ├── register_probe.yml            # AWX registration playbook
│   ├── discovery_lan.yml            # LAN discovery playbook
│   └── maintenance.yml              # Heartbeat and kill switch
│
├── Scripts
│   ├── parse_nmap.py                # Nmap XML parser for discovery
│   └── verify_system.py             # System verification script
│
├── Configuration Files
│   ├── gatekeeper.service           # Systemd service for gatekeeper
│   ├── netbox_inventory.yml        # NetBox dynamic inventory config
│   └── probe_config.example.txt     # Probe configuration example
│
└── Documentation
    ├── README.md                    # Comprehensive documentation
    ├── QUICKSTART.md                # Quick start guide
    └── PROJECT_SUMMARY.md           # This file
```

---

## Component Breakdown

### 1. Gatekeeper (`gatekeeper.py`)
- **Purpose**: Manage NetBox port assignments via REST API
- **Framework**: FastAPI with Pydantic validation
- **Features**:
  - `GET /provision/request-port?mac=<MAC>` endpoint
  - Returns existing port if device found, otherwise assigns next available (starting at 10001)
  - Health check at `/health`
  - Comprehensive error handling and logging
- **Dependencies**: fastapi, uvicorn, pynetbox, python-dotenv

### 2. Bootstrap Script (`bootstrap_probe.py`)
- **Purpose**: First-boot registration for new probes
- **Features**:
  - Reads `TENANT_SLUG` from `/boot/probe_config.txt`
  - Gets MAC address of eth0
  - Calls Gatekeeper API for port assignment
  - Generates Ed25519 SSH key pair
  - Creates autossh systemd service
  - Calls AWX provisioning callback
  - Writes completion marker to prevent re-execution
- **Dependencies**: requests, cryptography

### 3. Registration Playbook (`register_probe.yml`)
- **Purpose**: Complete probe registration triggered by AWX callback
- **Tasks**:
  - Add SSH key to proxy `authorized_keys` with security restrictions
  - Create/update NetBox device with tenant and `automation_proxy_port`
  - Create NetBox interface with MAC address
  - Trigger AWX inventory synchronization
- **Security**: Keys added with `command="/bin/false",no-pty,no-X11-forwarding,no-agent-forwarding`

### 4. Discovery Playbook (`discovery_lan.yml`)
- **Purpose**: Discover devices on probe LANs and sync to NetBox
- **Tasks**:
  - Install nmap if missing
  - Run nmap ping scan on configured subnets
  - Parse XML results
  - Sync discovered IPs to NetBox IPAM per tenant
- **Features**: Tenant-based isolation, configurable subnets

### 5. Maintenance Playbook (`maintenance.yml`)
- **Purpose**: Heartbeat monitoring and probe decommissioning
- **Tags**:
  - `heartbeat`: Check connectivity, update NetBox status
  - `killswitch`: Remove keys, kill tunnels, decommission in NetBox
  - `cleanup`: Archive stale NetBox entries
- **Targeting**: By MAC address, port number, or tenant slug

### 6. Infrastructure Setup (`setup_infrastructure.yml`)
- **Purpose**: Automated initial deployment
- **Tasks**:
  - Configure proxy server (users, SSH, packages)
  - Deploy gatekeeper service
  - Create NetBox custom field
  - Setup probe on target hardware

### 7. Support Scripts

#### `parse_nmap.py`
- Parse nmap XML output
- Format discovered hosts for NetBox IPAM
- Output JSON for AWX/Ansible consumption

#### `verify_system.py`
- Comprehensive system health check
- Validates environment, dependencies, and connectivity
- Tests all major components

---

## Key Features

### Security
- **SSH Key Restrictions**: All probe keys added with `command="/bin/false",no-pty,no-X11-forwarding,no-agent-forwarding`
- **Tenant Isolation**: NetBox tenant-based segmentation
- **Kill Switch**: Immediate revocation by MAC, port, or tenant
- **No Inbound Ports**: Probes connect out via SSH only

### Scalability
- **200+ Probes**: Designed for large fleets
- **Zero-Touch**: Fully automated provisioning
- **Batch Processing**: Maintenance playbook uses `serial: 50`
- **API-First**: Gatekeeper provides RESTful service

### Reliability
- **Autossh**: Automatic reconnection with health checks
- **Heartbeat**: Regular status updates to NetBox
- **Error Handling**: Comprehensive exception handling and logging
- **Idempotent**: All playbooks safe to run multiple times

### Flexibility
- **Configurable Subnets**: Per-probe or global
- **Multiple Targets**: Kill switch by MAC, port, or tenant
- **Extensible**: Easy to add new discovery methods

---

## Dependencies

### Python Packages
```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
pydantic>=2.5.0
pynetbox>=7.3.0
requests>=2.31.0
cryptography>=41.0.0
python-dotenv>=1.0.0
lxml>=4.9.0
python-json-logger>=2.0.7
```

### Ansible Collections
```
netbox.netbox
ansible.posix
community.general (for XML parsing)
```

### System Packages
- autossh (for reverse tunnels)
- nmap (for LAN discovery)
- python3, pip (for scripts)

---

## Deployment Flow

```
1. New Probe Boots
   └─> Reads /boot/probe_config.txt

2. Bootstrap Script Runs
   ├─> Gets MAC address
   ├─> Calls Gatekeeper API
   │   └─> Gets port assignment
   ├─> Generates SSH keys
   ├─> Creates autossh service
   └─> Calls AWX callback

3. AWX Registration Playbook
   ├─> Adds key to proxy authorized_keys
   ├─> Creates NetBox device
   ├─> Creates NetBox interface
   └─> Triggers inventory sync

4. Ongoing Operations
   ├─> Discovery: Daily nmap scans → NetBox IPAM
   ├─> Heartbeat: Every 15 min → NetBox status
   └─> Kill Switch: On-demand revocation
```

---

## NetBox Requirements

### Custom Field
```
Name: automation_proxy_port
Label: Automation Proxy Port
Type: Integer
Content Types: DCIM > Device
Required: False
UI Visibility: Read-Only
```

### Device Naming Convention
```
probe-<mac-without-colons>
Example: probe-aabbccddeeff
```

---

## Configuration Files

### `.env` (Gatekeeper)
```env
NETBOX_URL=https://netbox.example.com
NETBOX_TOKEN=your-token
GATEKEEPER_PORT=8000
```

### `/boot/probe_config.txt` (Probe)
```
TENANT_SLUG=customer-name
```

---

## Testing & Verification

Run the verification script:
```bash
cd ~/probe
. .env  # Load environment variables
python3 scripts/verify_system.py
```

Checks:
- ✓ Environment variables
- ✓ Python dependencies
- ✓ Required files
- ✓ Gatekeeper API health
- ✓ Port request test
- ✓ NetBox connection
- ✓ Proxy SSH access

---

## Next Steps for Deployment

1. **Infrastructure Setup**
   ```bash
   ansible-playbook playbooks/setup_infrastructure.yml
   ```

2. **Verify System**
   ```bash
   python3 scripts/verify_system.py
   ```

3. **Prepare Probe Image**
   - Install dependencies
   - Copy `bootstrap_probe.py`
   - Configure `/boot/probe_config.txt`
   - Enable systemd service

4. **Deploy Probes**
   - Flash SD cards with prepared image
   - Provision `TENANT_SLUG` per customer
   - Deploy to locations

5. **Monitor**
   - Check AWX job results
   - Review NetBox device inventory
   - Verify tunnel connectivity

---

## Maintenance Schedule

- **Every 15 min**: Heartbeat check (via AWX schedule)
- **Daily**: LAN discovery scan (via AWX schedule)
- **Weekly**: Cleanup stale NetBox entries
- **Monthly**: Review access logs and audit trails

---

## Support

For issues or questions:
1. Check `README.md` for detailed documentation
2. Review `QUICKSTART.md` for quick fixes
3. Run `verify_system.py` to diagnose problems
4. Check logs: `journalctl -u gatekeeper`, `journalctl -u probe-bootstrap`

---

## License

MIT

---

**Last Updated**: 2025-02-05
**Version**: 1.0.0
