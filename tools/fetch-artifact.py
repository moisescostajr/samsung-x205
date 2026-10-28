#!/usr/bin/env python3
import subprocess, urllib.request, json, os, zipfile, io, shutil

# Retrieve token via osxkeychain
p = subprocess.Popen(["git", "credential", "fill"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
stdout, _ = p.communicate("protocol=https\nhost=github.com\n")
token = None
for line in stdout.splitlines():
    if line.startswith("password="):
        token = line.split("=", 1)[1].strip()
        break

if not token:
    raise SystemExit("Error: Could not retrieve GitHub token.")

REPO = "moisescostajr/samsung-x205"
API_URL = f"https://api.github.com/repos/{REPO}/actions/artifacts"

req = urllib.request.Request(API_URL, headers={
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json"
})
opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=__import__('ssl')._create_unverified_context()))
with opener.open(req) as resp:
    data = json.loads(resp.read().decode())

artifacts = data.get("artifacts", [])
if not artifacts:
    raise SystemExit("No artifacts found.")

latest = artifacts[0]
print(f"Downloading artifact: {latest['name']} (ID: {latest['id']}, Size: {latest['size_in_bytes']} bytes)...")

dl_url = latest["archive_download_url"]
dl_req = urllib.request.Request(dl_url, headers={
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json"
})

with opener.open(dl_req) as resp:
    zip_bytes = resp.read()

print(f"Downloaded {len(zip_bytes)} bytes. Extracting into boot-pack/...")
os.makedirs("boot-pack", exist_ok=True)
with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
    z.extractall("boot-pack")

print("[OK] Artifacts successfully extracted into boot-pack/!")
