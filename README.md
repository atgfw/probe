# Zero-Touch Network Discovery System

A complete zero-touch provisioning and network discovery system for managing 200+ remote probes (Debian/Raspbian) connecting via reverse SSH tunnels to a DigitalOcean proxy.

## Architecture Overview

```
┌─────────────┐     1. Boot & Read Config     ┌─────────────────┐
│  New Probe  │ ───────────────────────────► │ /boot/config.txt │
└──────┬──────┘                              └────────┬─────────┘
       │                                               │
       │ 2. Get MAC                                    │
       ▼                                               │
┌─────────────┐                                       │
│ bootstrap_  │◄──────────────────────────────────────┘
│ probe.py    │
└──────┬──────┘
       │
       ├─► 3. Gatekeeper API (GET /provision/request-port)
       │    └─► Returns: proxy_port, existing/new
       │
       ├─► 4. Generate SSH Key (id_ed25519)
       │
       ├─► 5. Create autossh systemd service
       │
       └─► 6. AWX Callback (POST JSON)
            └─► Triggers: Ansible Registration Playbook

Registration Playbook:
┌──────────────┐     ┌─────────────┐     ┌─────────────┐
│   Proxy SSH  │     │   NetBox    │     │    AWX      │
│  authorized_ │ ◄── │  Device     │ ◄── │   Inventory │
│    keys      │     │   Create/   │     │    Sync     │
└──────────────┘     │   Update    │     └─────────────┘
                    └─────────────┘

Ongoing Operations:
┌─────────────┐     Nmap Scan      ┌─────────────┐
│  Discovery  │ ◄───────────────── │   NetBox    │
│  Playbook   │  IPAM Sync         │   IPAM      │
└─────────────┘                    └─────────────┘

┌─────────────┐                    ┌─────────────┐
│ Maintenance │ ◄── Heartbeat ──► │   NetBox    │
│  Playbook   │   Kill Switch     │   Status    │
└─────────────┘                    └─────────────┘
```

## Components

### 1. Gatekeeper (`gatekeeper.py`)

FastAPI service that manages proxy port assignments in NetBox.

**Features:**
- Connects to NetBox API via `pynetbox`
- Endpoint: `GET /provision/request-port?mac=<MAC>`
- Returns existing port if device found, otherwise assigns next available (starting at 10001)
- Health check endpoint at `/health`

**Requirements:**
- Python 3.8+
- FastAPI, Uvicorn, PyNetBox

**Usage:**
```bash
# Set environment variables
export NETBOX_URL=https://netbox.example.com
export NETBOX_TOKEN=your-token

# Run
python3 gatekeeper.py
# Or with uvicorn
uvicorn gatekeeper:app --host 0.0.0.0 --port 8000
```

### 2. Bootstrap Script (`bootstrap_probe.py`)

Runs on first boot of a probe to register with the system.

**Features:**
- Reads `TENANT_SLUG` from `/boot/probe_config.txt`
- Gets MAC address of eth0
- Requests proxy port from Gatekeeper API
- Generates Ed25519 SSH key pair (if missing)
- Creates autossh systemd service
- Calls AWX provisioning callback

**Requirements:**
- Python 3.8+, cryptography, requests
- autossh installed on probe

**Usage:**
```bash
# Install dependencies
pip3 install -r requirements.txt

# Run (typically via systemd one-shot service or cloud-init)
python3 bootstrap_probe.py
```

**Probe Configuration:**
Create `/boot/probe_config.txt` on the probe:
```
TENANT_SLUG=your-tenant-slug
```

### 3. Registration Playbook (`playbooks/register_probe.yml`)

Triggered by AWX callback to complete registration.

**Tasks:**
1. Append probe's public key to proxy's `authorized_keys` with restrictions
2. Create/update NetBox device with tenant and `automation_proxy_port` custom field
3. Create NetBox interface with MAC address
4. Trigger AWX inventory synchronization

**Usage:**
```bash
# Via AWX Job Template (recommended)
# Set as callback URL in bootstrap_probe.py

# Manual execution
ansible-playbook playbooks/register_probe.yml \
  -e "mac=aa:bb:cc:dd:ee:ff" \
  -e "proxy_port=10001" \
  -e "tenant_slug=example" \
  -e "public_key='ssh-ed25519 AAAA...'"
```

### 4. Discovery Playbook (`playbooks/discovery_lan.yml`)

Runs on registered probes to discover LAN devices.

**Tasks:**
1. Target probes via NetBox dynamic inventory
2. Run nmap ping scan on configured subnets
3. Parse XML results
4. Sync discovered IPs to NetBox IPAM per tenant

**Usage:**
```bash
# Run on all probes
ansible-playbook playbooks/discovery_lan.yml -i netbox_inventory.ini

# Target specific probes
ansible-playbook playbooks/discovery_lan.yml -i netbox_inventory.ini -l probes_customer1

# Override subnets per probe
ansible-playbook playbooks/discovery_lan.yml -i netbox_inventory.ini \
  -e "probe_subnets=192.168.1.0/24,10.0.0.0/24"
```

**Parse Nmap Output (Standalone):**
```bash
python3 scripts/parse_nmap.py /tmp/lan_scan.xml tenant-slug > discovered.json
```

### 5. Maintenance Playbook (`playbooks/maintenance.yml`)

Handles heartbeat monitoring and decommissioning.

**Tasks:**
- **Heartbeat**: Ping probes, update NetBox status (active/offline)
- **Kill Switch**: Remove SSH keys and kill tunnels by MAC, port, or tenant
- **Cleanup**: Archive stale NetBox entries

**Usage:**
```bash
# Heartbeat check (all probes)
ansible-playbook playbooks/maintenance.yml -i netbox_inventory.ini --tags heartbeat

# Kill specific probe by MAC
ansible-playbook playbooks/maintenance.yml -i netbox_inventory.ini --tags killswitch \
  -e "target_mac=aa:bb:cc:dd:ee:ff"

# Kill probe by port
ansible-playbook playbooks/maintenance.yml -i netbox_inventory.ini --tags killswitch \
  -e "target_port=10001"

# Kill all probes in a tenant
ansible-playbook playbooks/maintenance.yml -i netbox_inventory.ini --tags killswitch \
  -e "tenant_slug=customer1"

# Cleanup stale NetBox entries
ansible-playbook playbooks/maintenance.yml -i netbox_inventory.ini --tags cleanup
```

## Installation

### Prerequisites

- **NetBox** with custom field `automation_proxy_port` on devices
- **AWX** (or AWX-compatible automation controller)
- **Proxy Server** (DigitalOcean droplet) with `tunnelmgr` user
- **Probe Hardware** (Raspberry Pi, etc.) running Debian/Raspbian

### 1. Set Up NetBox

Create the required custom field:
```python
# Via NetBox API or web UI
# Custom field: automation_proxy_port
# Type: Integer
# Label: Automation Proxy Port
# Required: False
```

### 2. Deploy Gatekeeper

```bash
# On proxy or management server
cd /opt/gatekeeper
python3 -m venv venv
source venv/bin/activate
pip install -r ~/probe/requirements.txt

# Configure
cp ~/probe/.env.example .env
# Edit .env with your NetBox credentials

# Run (use systemd in production)
uvicorn gatekeeper:app --host 0.0.0.0 --port 8000
```

### 3. Configure Proxy User

```bash
# On proxy server
sudo useradd -m -s /bin/bash tunnelmgr
sudo -u tunnelmgr mkdir -p ~/.ssh
sudo -u tunnelmgr touch ~/.ssh/authorized_keys
sudo -u tunnelmgr chmod 700 ~/.ssh
sudo -u tunnelmgr chmod 600 ~/.ssh/authorized_keys
```

### 4. Set Up AWX

Create job templates:
1. **Probe Registration**: Run `playbooks/register_probe.yml` with callback enabled
2. **LAN Discovery**: Run `playbooks/discovery_lan.yml` on schedule
3. **Maintenance**: Run `playbooks/maintenance.yml` on schedule

Configure dynamic inventory source pointing to NetBox.

### 5. Prepare Probe Image

```bash
# On probe image
apt-get update
apt-get install -y python3 python3-pip autossh nmap

pip3 install -r requirements.txt

# Create config file
cat > /boot/probe_config.txt <<EOF
TENANT_SLUG=your-tenant-slug
EOF

# Create systemd service for bootstrap
cat > /etc/systemd/system/probe-bootstrap.service <<EOF
[Unit]
Description=Probe Bootstrap Registration
After=network-online.target
Wants=network-online.target
ConditionPathExists=!/var/lib/probe_bootstrap_complete

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/probe/bootstrap_probe.py
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl enable probe-bootstrap.service
```

## Security Considerations

### SSH Key Restrictions
All probe keys are added with these restrictions in `authorized_keys`:
```
command="/bin/false",no-pty,no-X11-forwarding,no-agent-forwarding <public_key>
```

This ensures probes can only establish reverse tunnels, not interactive shells.

### Network Security
- Probes connect out via SSH; no inbound firewall rules needed
- Autossh with `ServerAliveInterval` and `ExitOnForwardFailure` ensures reliable tunnels
- SSH host key verification disabled for bootstrap (improves first-boot success rate)

### NetBox Access
- Use read/write API tokens with minimal scope
- Tenant-based segmentation in NetBox
- Custom field `automation_proxy_port` tracks port assignments

### Kill Switch
Maintenance playbook can immediately revoke access by:
1. Removing SSH key from authorized_keys
2. Killing autossh processes
3. Marking device as decommissioned in NetBox

## Troubleshooting

### Bootstrap Fails

Check bootstrap logs:
```bash
journalctl -u probe-bootstrap.service -f
```

Common issues:
- `TENANT_SLUG` missing in `/boot/probe_config.txt`
- Gatekeeper API unreachable
- Network interface `eth0` not present

### Tunnel Not Connecting

Check autossh status:
```bash
systemctl status autossh-probe-10001.service
journalctl -u autossh-probe-10001.service -f
```

Check proxy connection:
```bash
ssh -p 10001 tunnelmgr@proxy.example.com
```

### Discovery Not Finding Devices

Check nmap installation and permissions:
```bash
# On probe
which nmap
sudo nmap -sn 192.168.1.0/24
```

Check local subnets configuration.

### Kill Switch Not Working

Verify authorized_keys entries:
```bash
# On proxy
sudo grep "Probe" /home/tunnelmgr/.ssh/authorized_keys
```

Check running autossh processes:
```bash
# On proxy
ps aux | grep autossh
```

## Directory Structure

```
~/probe/
├── gatekeeper.py              # FastAPI port assignment service
├── bootstrap_probe.py         # Probe first-boot registration
├── requirements.txt           # Python dependencies
├── .env.example              # Environment variables template
├── README.md                 # This file
├── playbooks/
│   ├── register_probe.yml    # AWX registration playbook
│   ├── discovery_lan.yml     # Network discovery playbook
│   └── maintenance.yml       # Heartbeat & kill switch
└── scripts/
    └── parse_nmap.py        # Nmap XML parser
```

## Monitoring and Maintenance

### Scheduled Tasks

**Heartbeat (Every 15 minutes):**
```bash
# AWX Job Template
ansible-playbook playbooks/maintenance.yml --tags heartbeat
```

**LAN Discovery (Daily):**
```bash
# AWX Job Template
ansible-playbook playbooks/discovery_lan.yml
```

**Cleanup (Weekly):**
```bash
# AWX Job Template
ansible-playbook playbooks/maintenance.yml --tags cleanup
```

### Metrics to Monitor

- Gatekeeper API response time
- Probe tunnel uptime (via heartbeat status)
- NetBox device count by status
- AWX job success/failure rates
- Nmap scan completion time

## License

MIT

## Contributing

This is an internal project. For questions or issues, contact the infrastructure team.
