"""Estimate, fetch, aggregate and export streamflow time series."""
import io
from dataclasses import dataclass

import dask
import numpy as np
import pandas as pd

from .store import CHRTOUT_URL, CHUNK_MB, FEATURE_CHUNK, TIME_CHUNK

BLOCK_HOURS = 12 * TIME_CHUNK  # time span loaded per progress step (~11 months)


@dataclass
class Estimate:
    chunks: int
    megabytes: float


def time_bounds(ds, start, end):
    """Integer positions [i0, i1) of the requested period on the time axis."""
    times = ds.indexes["time"]
    i0 = times.searchsorted(pd.Timestamp(start))
    i1 = times.searchsorted(pd.Timestamp(end) + pd.Timedelta(days=1))  # end date inclusive
    return int(i0), int(i1)


def estimate(ds, indices, start, end) -> Estimate:
    """How many chunks (and roughly how many MB) a request has to download."""
    i0, i1 = time_bounds(ds, start, end)
    if i1 <= i0:
        return Estimate(0, 0.0)
    feature_chunks = len(np.unique(np.asarray(indices) // FEATURE_CHUNK))
    time_chunks = (i1 - 1) // TIME_CHUNK - i0 // TIME_CHUNK + 1
    n = feature_chunks * time_chunks
    return Estimate(n, n * CHUNK_MB)


def fetch_streamflow(ds, indices, start, end, progress_cb=None) -> pd.DataFrame:
    """Hourly streamflow (m3/s), one column per feature_id, UTC time index."""
    i0, i1 = time_bounds(ds, start, end)
    if i1 <= i0:
        raise ValueError("The selected period is outside the dataset (1979-02-01 to 2023-01-31).")
    indices = np.asarray(indices)
    flow = ds["streamflow"].isel(feature_id=indices)
    # Align blocks with the store's chunk boundaries so no chunk is downloaded twice.
    edges = list(range(i0 - i0 % BLOCK_HOURS + BLOCK_HOURS, i1, BLOCK_HOURS))
    edges = [i0, *edges, i1]
    parts = []
    with dask.config.set(scheduler="threads", num_workers=16):
        for n, (a, b) in enumerate(zip(edges[:-1], edges[1:]), 1):
            parts.append(flow.isel(time=slice(a, b)).load())
            if progress_cb:
                progress_cb(n / (len(edges) - 1))
    data = np.concatenate([p.values for p in parts])
    times = np.concatenate([p["time"].values for p in parts])
    df = pd.DataFrame(data, index=pd.DatetimeIndex(times, name="time_utc"),
                      columns=ds["feature_id"].values[indices])
    df.columns.name = "feature_id"
    return df


def resample(df: pd.DataFrame, freq=None) -> pd.DataFrame:
    """Mean flow per day ("D") or month ("MS"); hourly data is returned unchanged.

    A ``n_hours`` column shows how many hourly values went into each period, so
    partial first/last periods are easy to spot.
    """
    if freq is None:
        return df
    grouped = df.resample(freq)
    out = grouped.mean()
    out["n_hours"] = grouped.count().iloc[:, 0]
    out.index.name = {"D": "date_utc", "MS": "month_utc"}.get(freq, df.index.name)
    return out


def to_csv_bytes(df: pd.DataFrame, reaches: pd.DataFrame | None = None, header=True) -> bytes:
    """CSV export. With ``header=True``, '#' comment lines describe the source and reaches."""
    buf = io.StringIO()
    if header:
        buf.write("# NOAA National Water Model v3.0 CONUS Retrospective, CHRTOUT streamflow\n")
        buf.write(f"# Source: {CHRTOUT_URL}\n")
        buf.write("# Units: m3/s; times in UTC; columns are NWM feature_id (reach) values\n")
        if reaches is not None:
            for r in reaches.itertuples():
                gage = f", USGS gage {r.gage_id}" if getattr(r, "gage_id", None) else ""
                buf.write(f"# feature_id {r.feature_id}: lat {r.latitude:.5f}, lon {r.longitude:.5f}, "
                          f"stream order {r.order}{gage}\n")
    df.to_csv(buf, float_format="%.3f")
    return buf.getvalue().encode()
