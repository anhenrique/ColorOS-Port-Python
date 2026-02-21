#!/usr/bin/env python3
import os
import sys
import json
import glob
import subprocess
from pathlib import Path

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_OWNER = "toraidl"
REPO_NAME = "ColorOS-Port-Python"
TAG_NAME = "assets"
API_BASE = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"

def run_curl(url, method="GET", data=None, headers=None, file_path=None):
    cmd = ["curl", "-s", "-X", method, url]
    
    if headers:
        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
            
    if data:
        cmd.extend(["-d", json.dumps(data)])
        
    if file_path:
        cmd.extend(["--data-binary", f"@{file_path}"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running curl: {e}")
        print(f"Output: {e.output}")
        print(f"Stderr: {e.stderr}")
        return None

def get_release_by_tag(tag):
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"{API_BASE}/releases/tags/{tag}"
    response = run_curl(url, headers=headers)
    if response:
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return None
    return None

def create_release(tag):
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "tag_name": tag,
        "name": "Assets Release",
        "body": "Automated assets release for large files.",
        "draft": False,
        "prerelease": False
    }
    url = f"{API_BASE}/releases"
    response = run_curl(url, method="POST", data=data, headers=headers)
    if response:
        try:
            resp_json = json.loads(response)
            if "id" not in resp_json:
                print(f"Failed to create release. Response: {json.dumps(resp_json, indent=2)}")
            return resp_json
        except json.JSONDecodeError:
            print(f"Failed to decode JSON response: {response}")
            return None
    return None

def upload_asset(upload_url, file_path):
    filename = os.path.basename(file_path)
    # Removing template param {?name,label} from upload_url if present
    base_upload_url = upload_url.split("{")[0]
    target_url = f"{base_upload_url}?name={filename}"
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/zip",
        "Accept": "application/vnd.github.v3+json"
    }
    
    print(f"Uploading {filename}...")
    # Use direct curl call with file
    cmd = [
        "curl", "-s", "-X", "POST", target_url,
        "-H", f"Authorization: token {GITHUB_TOKEN}",
        "-H", "Content-Type: application/zip",
        "-H", "Accept: application/vnd.github.v3+json",
        "--data-binary", f"@{file_path}"
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print(f"Successfully uploaded {filename}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to upload {filename}: {e}")

def main():
    if not GITHUB_TOKEN:
        print("Error: GITHUB_TOKEN environment variable is not set.")
        print("Please export GITHUB_TOKEN=<your_token> and try again.")
        sys.exit(1)

    print(f"Checking for release tag '{TAG_NAME}'...")
    release = get_release_by_tag(TAG_NAME)
    
    if not release or "id" not in release:
        print(f"Release '{TAG_NAME}' not found. Creating it...")
        release = create_release(TAG_NAME)
        if not release or "id" not in release:
            print("Failed to create release.")
            sys.exit(1)
            
    upload_url = release["upload_url"]
    existing_assets = {asset["name"]: asset["id"] for asset in release.get("assets", [])}
    
    # Find zip files
    zip_files = []
    # devices/common/*.zip
    zip_files.extend(glob.glob("devices/common/*.zip"))
    # devices/target/*/*.zip
    zip_files.extend(glob.glob("devices/target/*/*.zip"))
    
    if not zip_files:
        print("No .zip files found to upload.")
        sys.exit(0)
        
    print(f"Found {len(zip_files)} files to check/upload.")
    
    for zip_file in zip_files:
        filename = os.path.basename(zip_file)
        if filename in existing_assets:
            print(f"Skipping {filename} (already exists in release).")
            continue
            
        upload_asset(upload_url, zip_file)

if __name__ == "__main__":
    main()
