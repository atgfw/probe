import requests, os
from dotenv import load_dotenv
load_dotenv()
NB_URL = os.getenv("NETBOX_URL").rstrip("/")
NB_TOKEN = os.getenv("NETBOX_TOKEN")
headers = {"Authorization": f"Token {NB_TOKEN}"}
url = f"https://{NB_URL}/api/dcim/devices/?device_type=network-probe&ordering=-last_updated"
try:
    r = requests.get(url, headers=headers, verify=False, timeout=10)
    if r.status_code == 200:
        results = r.json().get("results", [])
        if results:
            for d in results[:5]:
                print(f"Device: {d.get('name')} | Status: {d.get('status', {}).get('value')} | Last Updated: {d.get('last_updated')}")
        else:
            print("No network probes found in NetBox.")
    else:
        print(f"Error {r.status_code}: {r.text}")
except Exception as e:
    print(f"Connection Error: {e}")
