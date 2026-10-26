"""USGS streamflow gauges from the official USGS Water Data API.

The list holds every USGS monitoring location with a daily-mean discharge record
(parameter 00060, statistic 00003), i.e. the streamflow gauges shown on the
USGS National Water Dashboard. It is downloaded once (~14 MB, a few seconds)
and cached locally; the cache is refreshed after MAX_AGE_DAYS.
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

GAUGES_URL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/combined-metadata/items"
DAILY_URL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/daily/items"
GAUGE_PAGE_URL = "https://waterdata.usgs.gov/monitoring-location/USGS-{}/"
CACHE_PATH = Path.home() / ".cache" / "nwm-flow" / "usgs_gauges.parquet"
MAX_AGE_DAYS = 30
ACTIVE_DAYS = 60  # a gauge is "active" if its daily record ends less than this many days ago
# Bounding box of the NWM CONUS domain (lat_min, lat_max, lon_min, lon_max).
CONUS_BOUNDS = (20.0, 55.0, -130.0, -60.0)
CFS_PER_M3S = 35.3147

_PARAMS = {
    "f": "json",
    "parameter_code": "00060",   # discharge
    "statistic_id": "00003",     # daily mean
    "properties": "monitoring_location_id,monitoring_location_name,drainage_area,begin,end",
    "limit": 50_000,
}


def _features(url, params):
    """All features of a USGS Water Data API query, following paging links."""
    while url:
        resp = requests.get(url, params=params, timeout=300)
        resp.raise_for_status()
        page = resp.json()
        yield from page["features"]
        url = next((l["href"] for l in page.get("links", []) if l.get("rel") == "next"), None)
        params = None  # the next link already carries the query


def _download() -> pd.DataFrame:
    rows = []
    for f in _features(GAUGES_URL, _PARAMS):
        if f.get("geometry"):
            p = f["properties"]
            lon, lat = f["geometry"]["coordinates"][:2]
            rows.append((p["monitoring_location_id"], p["monitoring_location_name"], lat, lon,
                         p["drainage_area"], p["begin"], p["end"]))
    df = pd.DataFrame(rows, columns=["id", "name", "latitude", "longitude", "drainage_area_sqmi", "begin", "end"])
    df = df[df["id"].str.startswith("USGS-")]
    df["site_no"] = df.pop("id").str.removeprefix("USGS-")
    for col in ("begin", "end"):
        df[col] = pd.to_datetime(df[col], utc=True, format="ISO8601").dt.tz_localize(None).dt.normalize()
    # One row per site: a site can have more than one daily discharge series.
    df = df.groupby("site_no", as_index=False).agg(
        name=("name", "first"), latitude=("latitude", "first"), longitude=("longitude", "first"),
        drainage_area_sqmi=("drainage_area_sqmi", "first"), begin=("begin", "min"), end=("end", "max"))
    lat0, lat1, lon0, lon1 = CONUS_BOUNDS
    df = df[df["latitude"].between(lat0, lat1) & df["longitude"].between(lon0, lon1)]
    df["active"] = df["end"] >= pd.Timestamp.now().normalize() - pd.Timedelta(days=ACTIVE_DAYS)
    return df.reset_index(drop=True)


def load_gauges(refresh=False) -> pd.DataFrame:
    """USGS streamflow gauges in the NWM domain, one row per site.

    Columns: site_no, name, latitude, longitude, drainage_area_sqmi, begin, end
    (daily record period) and active. If the download fails, a stale cache is used
    when one exists.
    """
    if CACHE_PATH.exists() and not refresh:
        age_days = (time.time() - CACHE_PATH.stat().st_mtime) / 86400
        if age_days < MAX_AGE_DAYS:
            return pd.read_parquet(CACHE_PATH)
    try:
        df = _download()
    except (requests.RequestException, KeyError, ValueError):
        if CACHE_PATH.exists():
            return pd.read_parquet(CACHE_PATH)
        raise
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE_PATH, index=False)
    return df


def nearest_gauge(gauges: pd.DataFrame, lat, lon) -> pd.Series:
    """The gauge closest to (lat, lon)."""
    dlat = np.radians(gauges["latitude"].to_numpy() - lat)
    dlon = np.radians(gauges["longitude"].to_numpy() - lon) * np.cos(np.radians(lat))
    return gauges.iloc[int(np.argmin(dlat**2 + dlon**2))]


def fetch_observed(site_no, start, end) -> pd.Series:
    """USGS daily mean streamflow (m3/s) at a gauge, indexed by date (gauge local day).

    Days without a value (ice, equipment failure, before/after the record) are absent.
    If the site has several daily discharge series, the longest one is used.
    """
    params = {"f": "json", "monitoring_location_id": f"USGS-{site_no}", "parameter_code": "00060",
              "statistic_id": "00003", "time": f"{pd.Timestamp(start):%Y-%m-%d}/{pd.Timestamp(end):%Y-%m-%d}",
              "properties": "time_series_id,time,value,unit_of_measure", "limit": 50_000}
    df = pd.DataFrame([f["properties"] for f in _features(DAILY_URL, params)],
                      columns=["time_series_id", "time", "value", "unit_of_measure"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    if df.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], name="date"), name=site_no)
    df = df[df["time_series_id"] == df["time_series_id"].value_counts().idxmax()]
    if not (df["unit_of_measure"] == "ft^3/s").all():
        raise ValueError(f"Unexpected units for USGS {site_no}: {df['unit_of_measure'].unique().tolist()}")
    obs = pd.Series(df["value"].to_numpy() / CFS_PER_M3S, index=pd.DatetimeIndex(df["time"], name="date"),
                    name=site_no)
    return obs.sort_index()
