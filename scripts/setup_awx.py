#!/usr/bin/env python3
"""
Setup AWX resources for the probe discovery system.
- Creates Project
- Creates Inventory
- Creates Job Templates (Register Probe, LAN Discovery)
"""

import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

AWX_HOST = os.getenv("AWX_HOST").rstrip("/")
AWX_TOKEN = os.getenv("AWX_TOKEN")
NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")

if not AWX_HOST or not AWX_TOKEN:
    print("Error: AWX_HOST or AWX_TOKEN not set in .env")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {AWX_TOKEN}",
    "Content-Type": "application/json"
}

def awx_request(method, endpoint, data=None):
    url = f"{AWX_HOST}/api/v2/{endpoint.lstrip('/')}"
    response = requests.request(method, url, headers=HEADERS, json=data, verify=False)
    if response.status_code not in [200, 201, 204]:
        print(f"Error {response.status_code} on {url}: {response.text}")
    return response.json() if response.status_code != 204 else {}

print(f"Connecting to AWX at {AWX_HOST}...")

# 1. Get Organization ID (assuming Default exists)
orgs = awx_request("GET", "organizations/?name=Default")
if not orgs.get("results"):
    # Fallback to get first organization
    orgs = awx_request("GET", "organizations/")
    
if not orgs.get("results"):
    print("Error: Could not find an organization in AWX")
    sys.exit(1)

org_id = orgs["results"][0]["id"]
print(f"✓ Using Organization ID: {org_id}")

# 2. Create Project
print("\nCreating Project 'Probe System'...")
project_data = {
    "name": "Probe System",
    "scm_type": "git",
    "scm_url": "https://github.com/atgfw/probe.git",
    "scm_update_on_launch": True,
    "organization": org_id
}

# Check if exists
existing_projects = awx_request("GET", f"projects/?name={project_data['name']}")
if existing_projects.get("results"):
    project_id = existing_projects["results"][0]["id"]
    print(f"  ✓ Project already exists (ID: {project_id})")
    # Trigger update
    awx_request("POST", f"projects/{project_id}/update/")
else:
    prj = awx_request("POST", "projects/", project_data)
    project_id = prj["id"]
    print(f"  + Created Project (ID: {project_id})")
    # Wait for completion/sync
    print("  Waiting for project sync...")
    time.sleep(5)

# 3. Create Inventory
print("\nCreating Inventory 'Network Probes'...")
inventory_data = {
    "name": "Network Probes",
    "organization": org_id
}
existing_inv = awx_request("GET", f"inventories/?name={inventory_data['name']}")
if existing_inv.get("results"):
    inventory_id = existing_inv["results"][0]["id"]
    print(f"  ✓ Inventory already exists (ID: {inventory_id})")
else:
    inv = awx_request("POST", "inventories/", inventory_data)
    inventory_id = inv["id"]
    print(f"  + Created Inventory (ID: {inventory_id})")

# 4. Create Job Template: Register Probe
print("\nCreating Job Template 'Register Probe'...")
jt_register_data = {
    "name": "Register Probe",
    "project": project_id,
    "playbook": "playbooks/register_probe.yml",
    "inventory": inventory_id,
    "allow_callbacks": True,
    "ask_variables_on_launch": True,
    "extra_vars": f"netbox_url: {NETBOX_URL}\nnetbox_token: {NETBOX_TOKEN}\n"
}
existing_jt = awx_request("GET", f"job_templates/?name={jt_register_data['name']}")
if existing_jt.get("results"):
    jt_id = existing_jt["results"][0]["id"]
    awx_request("PATCH", f"job_templates/{jt_id}/", jt_register_data)
    print(f"  ✓ Updated Job Template (ID: {jt_id})")
else:
    jt = awx_request("POST", "job_templates/", jt_register_data)
    jt_id = jt["id"]
    print(f"  + Created Job Template (ID: {jt_id})")

# Get Callback Details
jt_details = awx_request("GET", f"job_templates/{jt_id}/")
callback_url = f"{AWX_HOST}{jt_details['url']}callback/"
host_config_key = jt_details.get("host_config_key", "GENERATE_ONE_IN_UI")

print(f"\n! CALLBACK CONFIGURATION !")
print(f"URL: {callback_url}")
print(f"Host Config Key: {host_config_key}")
print("! Add these to your bootstrap_probe.py or .env on the probe !")

# 5. Create Job Template: LAN Discovery
print("\nCreating Job Template 'LAN Discovery'...")
jt_discovery_data = {
    "name": "LAN Discovery",
    "project": project_id,
    "playbook": "playbooks/discovery_lan.yml",
    "inventory": inventory_id,
    "extra_vars": f"netbox_url: {NETBOX_URL}\nnetbox_token: {NETBOX_TOKEN}\n"
}
existing_jt_disc = awx_request("GET", f"job_templates/?name={jt_discovery_data['name']}")
if existing_jt_disc.get("results"):
    jt_disc_id = existing_jt_disc["results"][0]["id"]
    awx_request("PATCH", f"job_templates/{jt_disc_id}/", jt_discovery_data)
    print(f"  ✓ Updated Job Template (ID: {jt_disc_id})")
else:
    jt_disc = awx_request("POST", "job_templates/", jt_discovery_data)
    print(f"  + Created Job Template (ID: {jt_disc['id']})")

print("\n" + "="*50)
print("AWX Setup successful!")
print("="*50)
