# Quick Start Guide

This guide gets you up and running with the minimum viable setup in about 30 minutes.

## Prerequisites Checklist

- [ ] NetBox server running (version 4.0+)
- [ ] DigitalOcean proxy droplet (Ubuntu 22.04 recommended)
- [ ] AWX or Ansible Controller instance
- [ ] At least one x86 PC/NUC or Debian-based probe
- [ ] GitHub access for cloning/playbook deployment

## Step 1: NetBox Setup (5 minutes)

```bash
# Log into NetBox web UI

# 1. Create custom field for proxy ports:
# Go to Customization > Custom Fields > Add
# Name: automation_proxy_port
# Label: Automation Proxy Port
# Type: Integer
# Content Types: DCIM > Device
# Required: False

# 2. Create at least one Tenant:
# Tenancy > Tenants > Add
# Name: Your Customer
# Slug: customer-name

# 3. Create device role for probes:
# DCIM > Device Roles > Add
# Name: Network Probe
# Slug: network-probe

# 4. Create manufacturer and device type:
# DCIM > Manufacturers > Add
# Name: Generic
# Slug: generic
#
# DCIM > Device Types > Add
# Manufacturer: Generic
# Model: Network Probe
# Slug: network-probe

# 5. Create sites:
# DCIM > Sites > Add
# Name: Pending
# Slug: pending
# (Used for probes awaiting full registration)
#
# DCIM > Sites > Add
# Name: Remote Site
# Slug: remote-site
# (Or create customer-specific sites)
```

## Step 2: Proxy Server Setup (10 minutes)

```bash
# SSH into your DigitalOcean proxy
ssh root@proxy.example.com

# Create tunnelmgr user
useradd -m -s /bin/bash tunnelmgr

# Setup SSH directory for tunnelmgr
sudo -u tunnelmgr mkdir -p ~/.ssh
sudo -u tunnelmgr touch ~/.ssh/authorized_keys
sudo -u tunnelmgr chmod 700 ~/.ssh
sudo -u tunnelmgr chmod 600 ~/.ssh/authorized_keys

# Install Python and dependencies
apt update
apt install -y python3 python3-pip python3-venv

# Create gatekeeper user
useradd -r -s /bin/false gatekeeper

# Setup gatekeeper directory
mkdir -p /opt/gatekeeper
chown gatekeeper:gatekeeper /opt/gatekeeper
cd /opt/gatekeeper

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Copy files from your workstation
# On your workstation:
scp gatekeeper.py requirements.txt gatekeeper.service root@proxy.example.com:/opt/gatekeeper/

# Install dependencies
pip install -r requirements.txt

# Create environment file
cat > /opt/gatekeeper/.env <<EOF
NETBOX_URL=https://your-netbox.example.com
NETBOX_TOKEN=your-netbox-api-token
GATEKEEPER_PORT=8000
GATEKEEPER_HOST=0.0.0.0
EOF

# Install systemd service
cp /opt/gatekeeper/gatekeeper.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable gatekeeper
systemctl start gatekeeper

# Verify it's running
curl http://localhost:8000/health
```

## Step 3: Deployment (The "Zero-Touch" Method) (5 minutes)

For mass deployment on x86 hardware, we use a custom Debian ISO that automatically registers the probe on boot.

### 1. Build the ISO
You can build the ISO on any system with Docker installed.

```bash
# On your workstation
./scripts/build_iso_docker.sh
```
This produces `probe-setup.iso` in the project root.

### 2. Flash and Personalize
1. **Flash**: Use a tool like [Etcher](https://www.balena.io/etcher/) to flash the ISO to a USB drive or SSD.
2. **Personalize**: 
   - Plug the media into your workstation.
   - Open the FAT32 boot partition (usually labeled `LIVE`).
   - Create a file `probe_config.txt` and add:
     ```text
     TENANT_SLUG=your-customer-slug
     ```
   - (Optional) If you need to override the proxy, add `GATEKEEPER_URL=http://x.x.x.x:8000` to the file.

### 3. Boot
Plug the media into the target hardware and boot. The probe will:
- Boot into a minimal Debian environment.
- Automatically find the config file.
- Register with Gatekeeper and AWX.
- Establish the SSH tunnel.

---

## Step 4: AWX Configuration (10 minutes)

```bash
# Via AWX Web UI

# 1. Create Credentials
# - NetBox Credential (type: NetBox API Token)
# - Machine Credential (for Proxy SSH access)

# 2. Create Inventory
# - Name: Probes - NetBox
# - Type: Smart Inventory
# - Or use netbox_inventory.yml with ansible-inventory command

# 3. Create Job Template: Register Probe
# - Name: Register Probe
# - Job Type: Run
# - Inventory: Probes
# - Project: (upload playbooks)
# - Playbook: playbooks/register_probe.yml
# - Credentials: NetBox, Proxy SSH
# - CHECK: Allow Provision Callbacks
# - Host Config Key: Generate and save this
# - Extra Variables: tenant_slug (or set from callback)

# 4. Create Job Template: LAN Discovery
# - Name: LAN Discovery
# - Playbook: playbooks/discovery_lan.yml
# - Schedule: Daily at 2 AM
# - Survey: "Subnets to scan" (optional)

# 5. Create Job Template: Probe Heartbeat
# - Name: Probe Heartbeat
# - Playbook: playbooks/maintenance.yml
# - Extra Vars: tags=heartbeat
# - Schedule: Every 15 minutes
```

## Step 5: Verify Registration (5 minutes)

Once the probe boots, verify it in your management systems:

1. **NetBox**:
   - A new device should appear in the `Pending` site.
   - It should automatically transition to `Active` status and its assigned tenant.
2. **AWX**:
   - Check the `Register Probe` job logs for completion.
3. **SSH Access**:
   - From your workstation (via the proxy):
     ```bash
     # Port is assigned in NetBox custom field 'automation_proxy_port'
     ssh -p [PORT] root@proxy.example.com
     ```

```bash
# Check NetBox
# - Look for device named "probe-aa:bb:cc:dd:ee:ff"
# - Verify tenant is correct
# - Check automation_proxy_port custom field

# Check proxy
ssh tunnelmgr@proxy.example.com "grep Probe ~/.ssh/authorized_keys"

# Check AWX
# - Verify Register Probe job was triggered and succeeded
# - Check inventory for the new probe

# Test SSH tunnel
# From your workstation via proxy:
ssh -p 10001 root@localhost
```

## Common Quick Fixes

### Bootstrap fails with "NetBox connection failed"
```bash
# Check gatekeeper is running on proxy
ssh root@proxy.example.com "systemctl status gatekeeper"

# Check firewall
ssh root@proxy.example.com "ufw status"
# Add rule if needed:
# ufw allow 8000/tcp
```

### Autossh service won't start
```bash
# On probe
sudo systemctl status autossh-probe-10001.service

# Check if port is already allocated
netstat -tlnp | grep 10001
```

### AWX callback times out
```bash
# Verify callback URL in bootstrap_probe.py matches AWX
# Check AWX job template has "Allow Provision Callbacks" checked
# Look at AWX job output for errors
```

### Discovery finds no hosts
```bash
# Check nmap is installed
which nmap

# Test nmap manually
sudo nmap -sn 192.168.1.0/24

# Verify probe has access to local network
ip addr show eth0
```

## Scaling Up

For mass deployment:

1. **Custom ISO**: Use the `./scripts/build_iso_docker.sh` method to maintain a master image.
2. **Automation**: Personalize batches by simply creating the `probe_config.txt` file on each media.
3. **Monitoring**: Set up AWX job schedules for automated discovery and maintenance across the fleet.

## Next Steps

After quick start:

- Read [README.md](README.md) for detailed documentation
- Configure automated backups for NetBox
- Set up monitoring for gatekeeper and proxy
- Configure firewall rules for security
- Document customer-specific subnet configurations

## Troubleshooting Commands

```bash
# Proxy server
systemctl status gatekeeper
journalctl -u gatekeeper -f
cat /home/tunnelmgr/.ssh/authorized_keys
ps aux | grep autossh

# Probe
systemctl status probe-bootstrap
systemctl status autossh-probe-*
journalctl -u probe-bootstrap -f
cat /run/live/medium/probe_config.txt  # Or /boot/probe_config.txt

# NetBox API test
curl -H "Authorization: Token YOUR_TOKEN" \
  https://netbox.example.com/api/dcim/devices/

# Gatekeeper API test
curl "http://proxy.example.com:8000/provision/request-port?mac=aa:bb:cc:dd:ee:ff"
```

---

**Need Help?** Check the main README.md or contact infrastructure team.
