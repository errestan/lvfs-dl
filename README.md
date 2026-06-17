# lvfs-dl

A command-line tool for browsing and downloading firmware from the
[Linux Vendor Firmware Service (LVFS)](https://fwupd.org/).

Metadata is downloaded once and cached locally for 24 hours, so all searches
and filtering happen offline without repeated round-trips to the LVFS servers.

## Requirements

- Python 3.10 or later (uses `X | Y` union type hints)
- No third-party packages — only the Python standard library

## Installation

Install from a checkout with `pip`:

```sh
git clone https://github.com/youruser/lvfs-dl.git
cd lvfs-dl
pip install .
```

This installs an `lvfs-dl` command onto your `PATH`. To install in editable
mode for development, use `pip install -e .` instead.

It is recommended to install with [`pipx`](https://pypa.github.io/pipx/) to keep
the tool isolated in its own environment:

```sh
pipx install .
```

## Usage

```
lvfs-dl [-h] [--refresh] [--output DIR] [query]
```

| Argument | Description |
|---|---|
| `query` | Search term (optional — prompted interactively if omitted) |
| `-r`, `--refresh` | Force re-download of metadata even if the cache is fresh |
| `-o DIR`, `--output DIR` | Directory in which to save downloaded firmware (default: `.`) |

### Examples

Search for Dell Precision firmware:

```sh
lvfs-dl "Dell Precision"
```

Narrow the search to a specific model:

```sh
lvfs-dl "Precision 3660"
```

Search by vendor:

```sh
lvfs-dl Lenovo
```

Save the downloaded firmware to a specific directory:

```sh
lvfs-dl -o ~/firmware "Dell Precision 3660"
```

Force a metadata refresh (e.g. after a firmware update is published):

```sh
lvfs-dl --refresh "Dell Precision"
```

Interactive mode (query is prompted):

```sh
lvfs-dl
```

### Search syntax

Whitespace-separated tokens are **ANDed**: every token must appear somewhere in
the package name, vendor, summary, or component ID.  The search is
case-insensitive.

```sh
lvfs-dl "Dell BIOS"     # name/summary must contain both "dell" and "bios"
lvfs-dl "Lenovo UEFI"
```

## How it works

1. On first run (or when `--refresh` is passed) `firmware.xml.gz` is fetched
   from `https://cdn.fwupd.org/downloads/` and saved to
   `~/.cache/lvfs-dl/firmware.xml.gz`.
2. The cache is reused for 24 hours before a refresh is triggered
   automatically.
3. The AppStream XML is parsed entirely in memory — all searching and filtering
   is done locally with no further network activity.
4. When you select a firmware package the `.cab` file is downloaded from the
   URL listed in the metadata and its SHA-256 checksum is verified against the
   value recorded in the metadata.  If the file is already present and the
   checksum matches, the download is skipped.

## Cached files

| Path | Purpose |
|---|---|
| `~/.cache/lvfs-dl/firmware.xml.gz` | LVFS AppStream metadata (refreshed every 24 h) |

## License

This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; version 2 of the License.

See [LICENSE](LICENSE) for the full text.
