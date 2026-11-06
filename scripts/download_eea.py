#!/usr/bin/env python3
"""Download the documented EEA-derived *pilot* annual station observations.

Original product: Zenodo 10.5281/zenodo.17085064.
Important: this is a curated/gap-filled product, not the untouched EEA E1a archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

FILENAME = "airquality.no2.o3.so2.pm10.pm2p5_4.annual_pnt_20150101_20231231_eu_epsg.3035_v20240718.parquet"
SOURCE = f"https://zenodo.org/records/17085064/files/{FILENAME}?download=1"
EXPECTED_MD5 = "6a08eccd6b355683f34fda77512ce038"
RAW = Path("data/raw/eea") / FILENAME
POLLUTANTS = ("NO2", "O3", "PM2.5")


def download_file(destination: Path, force: bool = False) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        digest = hashlib.md5(destination.read_bytes()).hexdigest()
        if digest == EXPECTED_MD5:
            return digest
        raise ValueError("Cached Parquet checksum mismatch; use --force to redownload.")
    session = requests.Session()
    retry = Retry(total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    temp = destination.with_suffix(".part")
    digest = hashlib.md5()
    try:
        with session.get(SOURCE, stream=True, timeout=(30, 180)) as res:
            res.raise_for_status()
            with temp.open("wb") as out:
                for chunk in res.iter_content(1024 * 1024):
                    if chunk:
                        digest.update(chunk)
                        out.write(chunk)
        if digest.hexdigest() != EXPECTED_MD5:
            raise ValueError(f"Downloaded checksum mismatch: {digest.hexdigest()}")
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
    return digest.hexdigest()


def col(df: pd.DataFrame, *names: str) -> str:
    cols = {str(name).lower(): str(name) for name in df.columns}
    for name in names:
        if name.lower() in cols:
            return cols[name.lower()]
    raise KeyError(f"Cannot find {names}; available columns: {list(df.columns)}")


def maybe_col(df: pd.DataFrame, name: str):
    return next((c for c in df.columns if str(c).lower() == name.lower()), None)


def build_long_table(raw_path: Path) -> pd.DataFrame:
    gdf = gpd.read_parquet(raw_path)
    if gdf.crs is None:
        raise ValueError("Input GeoParquet has no CRS; refusing to guess coordinates.")
    geo = gdf.to_crs("EPSG:4326")
    station_id = col(geo, "Air.Quality.Station.EoI.Code")
    year_col = col(geo, "year")
    country = col(geo, "Countrycode")
    type_col = maybe_col(geo, "Station.Type")
    area_col = maybe_col(geo, "Station.Area")
    result = []
    for pollutant in POLLUTANTS:
        value_col = col(geo, pollutant)
        coverage_col = maybe_col(geo, f"cov.year_{pollutant}")
        block = pd.DataFrame({
            "station_id": geo[station_id].astype("string").str.strip(),
            "year": pd.to_numeric(geo[year_col], errors="coerce"),
            "country": geo[country].astype("string"),
            "station_type": geo[type_col].astype("string") if type_col else pd.Series(pd.NA, index=geo.index),
            "station_area": geo[area_col].astype("string") if area_col else pd.Series(pd.NA, index=geo.index),
            "lon": geo.geometry.x,
            "lat": geo.geometry.y,
            "pollutant": pollutant,
            "observation_ug_m3": pd.to_numeric(geo[value_col], errors="coerce"),
            "coverage": pd.to_numeric(geo[coverage_col], errors="coerce") if coverage_col else np.nan,
        })
        block = block.dropna(subset=["station_id", "year", "lon", "lat", "observation_ug_m3"])
        block = block.loc[
            block["year"].between(2015, 2023)
            & block["lat"].between(-90, 90)
            & block["lon"].between(-180, 180)
            & (block["observation_ug_m3"] >= 0)
        ].copy()
        # Coverage is measured in the original data product; do not fill unknown values.
        block["year"] = block["year"].astype("int16")
        block["source"] = "zenodo:17085064:v3_derived_EEA"
        block["pm25_gapfill_status"] = (
            "possibly_gapfilled_in_source" if pollutant == "PM2.5" else "not_applicable"
        )
        result.append(block)
    out = pd.concat(result, ignore_index=True)
    keys = ["station_id", "year", "pollutant"]
    dup = out.duplicated(keys, keep=False)
    if dup.any():
        raise ValueError(
            f"Non-unique station/year/pollutant keys ({int(dup.sum())} rows). "
            "Do not average different station records blindly."
        )
    out = out.sort_values(["year", "pollutant", "station_id"]).reset_index(drop=True)
    if out.empty:
        raise ValueError("No valid station-years found. Check source schema and QC.")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/processed/eea_stations_annual_2015_2023.csv"))
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    digest = download_file(args.raw, force=args.force)
    table = build_long_table(args.raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.output, index=False, float_format="%.8g")
    audit = {
        "source": SOURCE, "zenodo_record": "10.5281/zenodo.17085064",
        "source_md5": digest, "rows": len(table),
        "years": sorted(table.year.unique().tolist()),
        "rows_by_pollutant": table.groupby("pollutant").size().to_dict(),
        "unique_stations_by_pollutant": table.groupby("pollutant").station_id.nunique().to_dict(),
        "warning": "Derived EEA data; source authors report PM2.5 gap-filling. Not independent E1a verification.",
        "columns": list(table.columns),
    }
    meta = Path("data/metadata/eea_annual_audit.json")
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
