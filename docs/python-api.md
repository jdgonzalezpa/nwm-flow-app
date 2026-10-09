# Python API

Everything the web app does is available from Python through the `nwm_flow` package. This is useful
for scripts, notebooks, and batch downloads.

Run Python from the project folder with the virtual environment active (or add the folder to
`PYTHONPATH`).

## Quick example

```python
from nwm_flow import open_chrtout, load_reach_table, estimate, fetch_streamflow, resample, to_csv_bytes

ds = open_chrtout()          # lazy: reads metadata only
reaches = load_reach_table() # cached reach table (~2.8M rows)

# Find the Potomac River at Little Falls (USGS 01646500)
near = reaches.nearest_reaches(38.9497, -77.1275, k=3, min_order=4)
print(near)
idx = near["index"].iloc[:1].to_numpy()

print(estimate(ds, idx, "2015-01-01", "2015-12-31"))   # Estimate(chunks=14, megabytes=63.0)

hourly = fetch_streamflow(ds, idx, "2015-01-01", "2015-12-31",
                          progress_cb=lambda f: print(f"{f:.0%}"))
daily = resample(hourly, "D")

with open("potomac_2015_daily.csv", "wb") as f:
    f.write(to_csv_bytes(daily, reaches.df.iloc[idx]))
```

## Reference

### `nwm_flow.store`

| Name | Description |
|---|---|
| `open_chrtout() -> xarray.Dataset` | Opens the CHRTOUT Zarr store anonymously and lazily (metadata only). |
| `CHRTOUT_URL` | `s3://noaa-nwm-retrospective-3-0-pds/CONUS/zarr/chrtout.zarr` |
| `STORAGE_OPTIONS` | `{"anon": True}`, the fsspec/s3fs options for anonymous access |
| `TIME_CHUNK`, `FEATURE_CHUNK` | Chunk sizes of `streamflow` (672 hours, 30,000 reaches) |
| `CHUNK_MB` | Typical compressed chunk size used for estimates (4.5) |

### `nwm_flow.reaches`

#### `load_reach_table(refresh=False) -> ReachTable`
Returns the table of all reaches. On first use it downloads `feature_id`, `latitude`, `longitude`,
`order` and `gage_id` from the store and caches them at `~/.cache/nwm-flow/reaches_v3.parquet`.
Pass `refresh=True` to rebuild the cache.

#### `class ReachTable`
- **`.df`**: `pandas.DataFrame` with columns `feature_id`, `latitude`, `longitude`, `order`, `gage_id`
  (string or `None`). The row position equals the position along the store's `feature_id` axis, which
  is the **index** used by the download functions.
- **`.index_for_feature_ids(ids) -> np.ndarray`**: converts NWM feature_ids to indices. Raises
  `KeyError` listing any unknown IDs.
- **`.nearest_reaches(lat, lon, k=5, min_order=1) -> DataFrame`**: the `k` nearest reaches with
  `order >= min_order`, sorted by distance. Columns: `index`, all `.df` columns, and `distance_km`.

Find the reach for a USGS gage:

```python
row = reaches.df[reaches.df["gage_id"] == "01646500"]
idx = row.index.to_numpy()      # DataFrame index == store index
```

### `nwm_flow.download`

#### `estimate(ds, indices, start, end) -> Estimate`
`Estimate(chunks, megabytes)`: the number of Zarr chunks (and approximate MB) a request reads.

#### `fetch_streamflow(ds, indices, start, end, progress_cb=None) -> DataFrame`
Downloads hourly streamflow.
- `indices`: store indices (from `ReachTable`), not feature_ids.
- `start`, `end`: anything `pandas.Timestamp` accepts. Both are dates, and `end` is inclusive (the
  whole end day is included).
- `progress_cb(fraction)`: optional, called after each ~11-month block.
- Returns a DataFrame with a UTC `DatetimeIndex` named `time_utc` and one float column per feature_id
  (m³/s, NaN where missing).
- Raises `ValueError` if the period is outside the dataset.

#### `resample(df, freq=None) -> DataFrame`
`freq=None` returns hourly data unchanged. `"D"` gives daily means and `"MS"` monthly means (any pandas
offset alias works). Adds an `n_hours` column with the number of hourly values in each period.

#### `to_csv_bytes(df, reaches=None, header=True) -> bytes`
CSV with values formatted to 3 decimals. If `header=True`, writes `#` comment lines describing the source,
units and (if `reaches` is given) each reach. Read such files with `pd.read_csv(path, comment="#")`.

## Batch download example

Download daily flow for every reach that has a USGS gage in a bounding box:

```python
from nwm_flow import *

ds, reaches = open_chrtout(), load_reach_table()
df = reaches.df
box = df[df.gage_id.notna() & df.latitude.between(38.5, 39.5) & df.longitude.between(-77.8, -76.8)]
idx = box.index.to_numpy()
print(len(idx), "gauged reaches;", estimate(ds, idx, "2010-01-01", "2019-12-31"))
# -> 64 gauged reaches; Estimate(chunks=786, megabytes=3537.0)   (check before running!)

daily = resample(fetch_streamflow(ds, idx, "2010-01-01", "2019-12-31"), "D")
daily.to_parquet("gauged_daily_2010s.parquet")
```

## Accessing other variables

`open_chrtout()` returns a regular xarray Dataset, so any variable can be read the same way:

```python
v = ds["velocity"].isel(feature_id=idx).sel(time=slice("2015-06-01", "2015-06-30")).load()
```
