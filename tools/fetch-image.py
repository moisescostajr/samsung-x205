#!/usr/bin/env python3
"""Download, verify and reassemble the latest GTA8 rootfs image.

The GitHub release stores the xz-compressed image as several <2 GiB parts plus
SHA256SUMS and manifest.txt. This script downloads them, verifies the parts and
the whole xz stream, decompresses with Python's lzma module (no Homebrew xz
needed) and writes rootfs/disk.raw for tools/write-sdcard.sh.

Examples:
    ./tools/fetch-image.py
    ./tools/fetch-image.py --boot-pack
    ./tools/fetch-image.py --tag image-latest --force
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAG = "image-latest"
DEFAULT_REPO = "moisescostajr/samsung-x205"
USER_AGENT = "gta8-fetch-image/1.0"


def log(msg: str) -> None:
    print(f"gta8-fetch: {msg}", flush=True)


def die(msg: str) -> "NoReturn":
    print(f"gta8-fetch: ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def repo_slug() -> str:
    try:
        url = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return DEFAULT_REPO
    # Handle git@github.com:owner/repo.git and https://.../owner/repo.git
    m = re.search(r"github\.com[:/]+([^/]+)/([^/#?]+)", url)
    if not m:
        return DEFAULT_REPO
    return f"{m.group(1)}/{m.group(2).removesuffix('.git')}"


def github_token() -> str | None:
    """Use the token git already has, without ever printing it."""
    try:
        p = subprocess.run(
            ["git", "credential", "fill"],
            cwd=REPO_ROOT,
            input="protocol=https\nhost=github.com\n\n",
            text=True, capture_output=True, timeout=15,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except Exception:
        return None
    for line in p.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip() or None
    return None


def tls_context() -> ssl.SSLContext:
    """Return a context with a CA bundle Python can actually find.

    The python.org macOS build does not ship a trust store, so plain
    urlopen() fails with CERTIFICATE_VERIFY_FAILED even though curl works.
    macOS keeps the system roots in /etc/ssl/cert.pem.
    """
    for cafile in (os.environ.get("SSL_CERT_FILE"), "/etc/ssl/cert.pem"):
        if cafile and Path(cafile).is_file():
            try:
                return ssl.create_default_context(cafile=cafile)
            except ssl.SSLError:
                continue
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CONTEXT = tls_context()


def api_get(url: str, token: str | None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as resp:
        return json.loads(resp.read().decode())


def open_asset(url: str, token: str | None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/octet-stream"}
    # Release download URLs redirect to a pre-signed object store; sending an
    # Authorization header there can break the signature. The public repo does
    # not need it.
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=120, context=SSL_CONTEXT)


def download(url: str, dest: Path, token: str | None, what: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with open_asset(url, token) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        next_report = 64 * 1024 * 1024
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if done >= next_report:
                if total:
                    log(f"  {what}: {done / 1048576:.0f}/{total / 1048576:.0f} MiB")
                else:
                    log(f"  {what}: {done / 1048576:.0f} MiB")
                next_report += 64 * 1024 * 1024
    if total and tmp.stat().st_size != total:
        die(f"{what}: short download ({tmp.stat().st_size} != {total})")
    os.replace(tmp, dest)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_sums(path: Path) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0]
    return sums


def safe_extract(archive: Path, dest: Path) -> None:
    dest = dest.resolve()
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            target = (dest / member.name).resolve()
            if target != dest and dest not in target.parents:
                die(f"refusing unsafe tar member: {member.name}")
        tf.extractall(dest)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None, help="owner/repo (default: git remote)")
    ap.add_argument("--tag", default=DEFAULT_TAG, help="release tag")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "rootfs" / "disk.raw")
    ap.add_argument("--boot-pack", action="store_true",
                    help="also download gta8-boot-pack.tar.gz into boot-pack/")
    ap.add_argument("--keep-xz", action="store_true",
                    help="keep the reassembled .xz after decompression")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing output image")
    args = ap.parse_args()

    out: Path = args.out
    if out.exists() and not args.force:
        die(f"{out} already exists (use --force to overwrite)")
    out.parent.mkdir(parents=True, exist_ok=True)

    repo = args.repo or repo_slug()
    token = github_token()
    log(f"repository: {repo}")
    log(f"release: {args.tag}")

    api = f"https://api.github.com/repos/{repo}/releases/tags/{urllib.parse.quote(args.tag)}"
    try:
        try:
            release = api_get(api, token)
        except urllib.error.HTTPError as e:
            if e.code == 401 and token:
                log("stored token was rejected; retrying anonymously")
                release = api_get(api, None)
            else:
                raise
    except urllib.error.HTTPError as e:
        if e.code != 404:
            die(f"GitHub API: HTTP {e.code}")
        log(f"tag {args.tag} not found; using the latest release")
        release = api_get(f"https://api.github.com/repos/{repo}/releases/latest", None)

    assets = {a["name"]: a for a in release.get("assets", [])}
    if not assets:
        die("release has no assets")

    work = Path(tempfile.mkdtemp(prefix="gta8-image-", dir=str(out.parent)))
    try:
        sums_path = work / "SHA256SUMS"
        if "SHA256SUMS" in assets:
            download(assets["SHA256SUMS"]["browser_download_url"], sums_path, token, "SHA256SUMS")
            sums = parse_sums(sums_path)
        else:
            sums = {}

        manifest_path = work / "manifest.txt"
        manifest: dict[str, str] = {}
        if "manifest.txt" in assets:
            download(assets["manifest.txt"]["browser_download_url"], manifest_path, token, "manifest.txt")
            for line in manifest_path.read_text().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    manifest[k.strip()] = v.strip()

        parts = sorted(
            (n for n in assets if re.fullmatch(r"gta8-rootfs\.img\.xz\.part\.\d+", n)),
            key=lambda n: int(n.rsplit(".", 1)[1]),
        )
        remote_xz: Path = work / "gta8-rootfs.img.xz"
        if parts:
            log(f"downloading {len(parts)} image part(s)")
            with open(remote_xz, "wb") as combined:
                for i, name in enumerate(parts, 1):
                    part = work / name
                    download(assets[name]["browser_download_url"], part, token, f"part {i}/{len(parts)}")
                    if name in sums:
                        got = sha256(part)
                        if got != sums[name]:
                            die(f"checksum mismatch for {name}")
                    with open(part, "rb") as f:
                        shutil.copyfileobj(f, combined, 1024 * 1024)
                    part.unlink()
        elif "gta8-rootfs.img.xz" in assets:
            log("downloading single image asset")
            download(assets["gta8-rootfs.img.xz"]["browser_download_url"],
                     remote_xz, token, "image")
        else:
            die("release has no gta8-rootfs.img.xz or .part.N assets")

        xz_hash = sha256(remote_xz)
        want = manifest.get("sha256_xz")
        if want and xz_hash != want:
            die(f"xz checksum mismatch ({xz_hash} != {want})")
        log(f"xz sha256: {xz_hash}")

        tmp_out = out.with_name(out.name + ".tmp")
        log(f"decompressing to {out}")
        total_out = 0
        with lzma.open(remote_xz, "rb") as src, open(tmp_out, "wb") as dst:
            for chunk in iter(lambda: src.read(4 * 1024 * 1024), b""):
                dst.write(chunk)
                total_out += len(chunk)
        want_size = manifest.get("size_bytes")
        if want_size and total_out != int(want_size):
            tmp_out.unlink(missing_ok=True)
            die(f"decompressed size mismatch ({total_out} != {want_size})")
        os.replace(tmp_out, out)
        os.chmod(out, 0o644)
        log(f"wrote {out} ({total_out / 1073741824:.2f} GiB)")
        if args.keep_xz:
            keep = out.parent / "gta8-rootfs.img.xz"
            shutil.move(str(remote_xz), str(keep))
            log(f"kept compressed image at {keep}")
        else:
            remote_xz.unlink(missing_ok=True)

        if args.boot_pack:
            name = "gta8-boot-pack.tar.gz"
            if name not in assets:
                die("release has no gta8-boot-pack.tar.gz")
            archive = work / name
            download(assets[name]["browser_download_url"], archive, token, name)
            if name in sums:
                got = sha256(archive)
                if got != sums[name]:
                    die(f"checksum mismatch for {name}")
            dest = REPO_ROOT / "boot-pack"
            dest.mkdir(parents=True, exist_ok=True)
            safe_extract(archive, dest)
            log(f"extracted boot pack into {dest}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
