#!/usr/bin/env python3
"""LVFS firmware metadata browser and downloader.

Downloads the LVFS AppStream metadata once (caching it locally) and lets
you search for firmware by name, vendor, or device ID without making
repeated requests to the server.
"""

import argparse
import gzip
import hashlib
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen, urlretrieve

METADATA_URL = "https://cdn.fwupd.org/downloads/firmware.xml.gz"
CACHE_DIR = Path.home() / ".cache" / "lvfs-dl"
METADATA_CACHE = CACHE_DIR / "firmware.xml.gz"
CACHE_MAX_AGE = timedelta(hours=24)


# ---------------------------------------------------------------------------
# Metadata cache
# ---------------------------------------------------------------------------

def _needs_refresh() -> bool:
    if not METADATA_CACHE.exists():
        return True
    age = datetime.now() - datetime.fromtimestamp(METADATA_CACHE.stat().st_mtime)
    return age > CACHE_MAX_AGE


def _progress_hook(count, block_size, total_size):
    if total_size <= 0:
        return
    downloaded = min(count * block_size, total_size)
    pct = downloaded * 100 / total_size
    mb_done = downloaded / 1_048_576
    mb_total = total_size / 1_048_576
    print(f"\r  {pct:5.1f}%  {mb_done:.1f} / {mb_total:.1f} MB", end="", flush=True)


def fetch_metadata(force: bool = False) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not force and not _needs_refresh():
        age = datetime.now() - datetime.fromtimestamp(METADATA_CACHE.stat().st_mtime)
        h, m = divmod(age.seconds, 3600)
        m //= 60
        print(f"Using cached metadata (age {h}h {m:02d}m, refresh with --refresh).")
        return
    print(f"Fetching {METADATA_URL} ...")
    urlretrieve(METADATA_URL, METADATA_CACHE, reporthook=_progress_hook)
    print(f"\nCached to {METADATA_CACHE}")


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def _text(el, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _vendor(component) -> str:
    # AppStream uses either <developer_name> or <developer><name>
    v = _text(component, "developer_name")
    if not v:
        v = _text(component, "developer/name")
    return v or "Unknown"


def _parse_releases(component) -> list[dict]:
    releases = []
    for rel in component.findall(".//release"):
        entry: dict = {
            "version": rel.get("version", ""),
            "date": rel.get("date", ""),
            "urgency": rel.get("urgency", ""),
            "url": "",
            "filename": "",
            "sha256": "",
            "size": 0,
        }
        loc = rel.find(".//location")
        if loc is not None and loc.text:
            entry["url"] = loc.text.strip()
        for cs in rel.findall(".//checksum"):
            if cs.get("type") == "sha256":
                entry["sha256"] = (cs.text or "").strip()
                entry["filename"] = cs.get("filename", "")
        sz = rel.find(".//size[@type='download']")
        if sz is not None and sz.text:
            try:
                entry["size"] = int(sz.text)
            except ValueError:
                pass
        # Only include releases that have a download URL
        if entry["url"]:
            releases.append(entry)
    return releases


def parse_metadata() -> list[dict]:
    print("Parsing metadata ...", end=" ", flush=True)
    with gzip.open(METADATA_CACHE, "rb") as fh:
        root = ET.parse(fh).getroot()

    packages = []
    for component in root.findall(".//component"):
        releases = _parse_releases(component)
        if not releases:
            continue
        pkg = {
            "id": _text(component, "id"),
            "name": _text(component, "name") or _text(component, "id"),
            "summary": _text(component, "summary"),
            "vendor": _vendor(component),
            "releases": releases,
        }
        packages.append(pkg)

    print(f"{len(packages):,} packages loaded.")
    return packages


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(packages: list[dict], query: str) -> list[dict]:
    q = query.lower()
    results = []
    for pkg in packages:
        haystack = " ".join([
            pkg["name"], pkg["vendor"], pkg["summary"], pkg["id"]
        ]).lower()
        # Require all whitespace-separated tokens to match
        if all(token in haystack for token in q.split()):
            results.append(pkg)
    return results


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _fmt_size(n: int) -> str:
    if n <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def display_results(results: list[dict]) -> None:
    if not results:
        print("No matching firmware found.")
        return
    print(f"\nFound {len(results)} package(s):\n")
    for i, pkg in enumerate(results, 1):
        latest = pkg["releases"][0]
        size_str = _fmt_size(latest["size"])
        size_part = f"  {size_str}" if size_str else ""
        print(f"  [{i:3d}]  {pkg['name']}")
        print(f"         Vendor:  {pkg['vendor']}")
        print(f"         Version: {latest['version']}  ({latest['date']}){size_part}")
        if pkg["summary"]:
            print(f"         {pkg['summary'][:88]}")
        print()


def _pick(prompt: str, count: int, default: int = 1) -> int | None:
    while True:
        raw = input(prompt).strip()
        if raw.lower() in ("q", "quit", ""):
            return None
        try:
            n = int(raw)
            if 1 <= n <= count:
                return n
        except ValueError:
            pass
        print(f"  Enter a number between 1 and {count}, or 'q' to quit.")


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_firmware(pkg: dict, release: dict, dest_dir: Path) -> Path | None:
    url = release["url"]
    filename = release["filename"] or urlparse(url).path.split("/")[-1]
    dest = dest_dir / filename

    if dest.exists():
        expected = release["sha256"]
        if expected and _sha256_file(dest) == expected:
            print(f"Already downloaded and verified: {dest}")
            return dest
        print("Local file exists but checksum does not match; re-downloading.")

    print(f"\nDownloading {filename}")
    print(f"  URL: {url}")
    urlretrieve(url, dest, reporthook=_progress_hook)
    print()

    if release["sha256"]:
        print("Verifying SHA-256 checksum ... ", end="", flush=True)
        actual = _sha256_file(dest)
        if actual == release["sha256"]:
            print("OK")
        else:
            print("FAILED")
            print(f"  Expected: {release['sha256']}")
            print(f"  Got:      {actual}")
            print("  The download may be corrupt or tampered with.")
            return None

    print(f"Saved: {dest}")
    return dest


# ---------------------------------------------------------------------------
# Interactive selection
# ---------------------------------------------------------------------------

def interactive_select(results: list[dict]) -> tuple[dict, dict] | tuple[None, None]:
    choice = _pick(f"Select package [1–{len(results)}] (q=quit): ", len(results))
    if choice is None:
        return None, None
    pkg = results[choice - 1]

    releases = pkg["releases"]
    if len(releases) == 1:
        return pkg, releases[0]

    print(f"\nReleases for {pkg['name']}:")
    for i, rel in enumerate(releases, 1):
        size_str = _fmt_size(rel["size"])
        size_part = f"  ({size_str})" if size_str else ""
        print(f"  [{i}]  {rel['version']}  {rel['date']}{size_part}")

    r = _pick(f"Select release [1–{len(releases)}] (q=quit): ", len(releases))
    if r is None:
        return None, None
    return pkg, releases[r - 1]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Browse and download firmware from the Linux Vendor Firmware Service.",
        epilog="Metadata is cached locally for 24 hours to minimise server requests.",
    )
    parser.add_argument(
        "query",
        nargs="?",
        help='Search term, e.g. "Dell Precision" or "Lenovo ThinkPad BIOS"',
    )
    parser.add_argument(
        "--refresh", "-r",
        action="store_true",
        help="Force re-download of metadata even if the cache is fresh",
    )
    parser.add_argument(
        "--output", "-o",
        default=".",
        metavar="DIR",
        help="Directory in which to save downloaded firmware (default: current dir)",
    )
    args = parser.parse_args()

    fetch_metadata(force=args.refresh)
    packages = parse_metadata()

    if args.query:
        query = args.query
    else:
        try:
            query = input('\nSearch (e.g. "Dell Precision", "Lenovo", "BIOS"): ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if not query:
            parser.print_help()
            sys.exit(1)

    results = search(packages, query)
    display_results(results)

    if not results:
        sys.exit(1)

    try:
        pkg, release = interactive_select(results)
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    if pkg is None:
        print("Aborted.")
        sys.exit(0)

    dest_dir = Path(args.output)
    dest_dir.mkdir(parents=True, exist_ok=True)
    download_firmware(pkg, release, dest_dir)


if __name__ == "__main__":
    main()
