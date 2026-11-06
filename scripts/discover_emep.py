#!/usr/bin/env python3
"""Inventory *actual* EMEP/MSC-W NetCDF files on MET Norway THREDDS.

Does not infer nonexistent file names. Downloading is opt-in: --download --name EXACT.nc
Always audit reporting/model version and emissions before combining years.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests

ROOT = "https://thredds.met.no"
DEFAULT_CATALOG = ROOT + "/thredds/catalog/data/EMEP/2024_Reporting/catalog.xml"
XMLNS = "{http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0}"
XLINK = "{http://www.w3.org/1999/xlink}"


def index_catalog(url: str, max_depth: int = 2):
    seen = set()
    rows = []
    session = requests.Session()

    def walk(current, depth):
        if current in seen:
            return
        seen.add(current)
        response = session.get(current, timeout=(30, 90))
        response.raise_for_status()
        root = ET.fromstring(response.content)
        for element in root.iter():
            if element.tag == XMLNS + "dataset":
                path = element.attrib.get("urlPath", "")
                if path.lower().endswith(".nc"):
                    name = element.attrib.get("name", Path(path).name)
                    yearly = re.search(r"(20\d{2})met", name, re.IGNORECASE)
                    rows.append({
                        "catalog_url": current,
                        "name": name,
                        "model_year": yearly.group(1) if yearly else "",
                        "url_path": path,
                        "download_url": ROOT + "/thredds/fileServer/" + path.lstrip("/"),
                        "opendap_url": ROOT + "/thredds/dodsC/" + path.lstrip("/"),
                    })
        if depth < max_depth:
            for child in root.iter(XMLNS + "catalogRef"):
                href = child.attrib.get(XLINK + "href", "")
                if href:
                    walk(urljoin(current, href), depth + 1)

    walk(url, 0)
    return sorted({r["download_url"]: r for r in rows}.values(), key=lambda r: r["name"])


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = ["catalog_url", "name", "model_year", "url_path", "download_url", "opendap_url"]
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def download_selected(record: dict, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    try:
        with requests.get(record["download_url"], stream=True, timeout=(30, 180)) as res:
            res.raise_for_status()
            with partial.open("wb") as fp:
                for chunk in res.iter_content(1024 * 1024):
                    if chunk:
                        fp.write(chunk)
                        digest.update(chunk)
        with partial.open("rb") as fp:
            if fp.read(3) not in (b"CDF", b"\x89HD"):
                raise ValueError("Not a recognizable NetCDF header (CDF / HDF5).")
        partial.replace(dest)
        print(f"Saved {dest}; sha256={digest.hexdigest()}")
    finally:
        partial.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path("data/metadata/emep_catalog_2024_reporting.csv"))
    parser.add_argument("--download", action="store_true", help="Download exactly one listed file")
    parser.add_argument("--name", help="Exact filename from the catalogue, required with --download")
    parser.add_argument("--dest", type=Path, default=Path("data/raw/emep"))
    args = parser.parse_args()
    if args.download and not args.name:
        parser.error("Use --name EXACT.nc with --download; avoid accidental bulk download.")
    if args.depth < 0 or args.depth > 5:
        parser.error("--depth must be between 0 and 5")
    files = index_catalog(args.catalog, args.depth)
    write_csv(args.output, files)
    print(f"Catalogued {len(files)} NetCDF files in {args.output}")
    print("Selected examples:")
    for row in files[:15]:
        print("  ", row["name"], row["model_year"])
    if args.download:
        matches = [row for row in files if row["name"] == args.name]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one match for {args.name!r}; found {len(matches)}")
        download_selected(matches[0], args.dest / Path(args.name).name)


if __name__ == "__main__":
    main()
