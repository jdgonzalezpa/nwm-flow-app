# Developer guide

## Project layout

```
nwm-flow-app/
├── app.py               # Streamlit user interface
├── nwm_flow/            # core library (no Streamlit dependency)
│   ├── __init__.py      # public API re-exports
│   ├── store.py         # dataset location, chunk constants, open_chrtout()
│   ├── reaches.py       # reach table cache, feature_id lookup, nearest-reach search
│   ├── gauges.py        # USGS gauge list and observed daily flow (USGS Water Data API)
│   ├── compare.py       # fit statistics (r, NSE, KGE, bias) and monthly means
│   └── download.py      # cost estimate, chunk-aligned fetching, resampling, CSV export
├── tests/test_core.py   # live smoke tests against AWS
├── docs/                # documentation
└── requirements.txt
```

`nwm_flow` does all the data work, and `app.py` is a thin UI on top of it. Keeping the library free of
Streamlit lets it be used from scripts and tested on its own.

## Data flow

```
user picks point / feature_ids
        │
        ▼
ReachTable (local parquet cache)        open_chrtout()  ──►  lazy xarray Dataset (S3, anonymous)
  • nearest_reaches (cKDTree)                   │
  • index_for_feature_ids (searchsorted)        │
        │  store indices                        │
        └──────────────► estimate() ◄───────────┤
                         fetch_streamflow() ◄───┘   (parallel S3 GETs via dask threads)
                                 │ hourly DataFrame
                                 ▼
                         resample() ──► to_csv_bytes() ──► download button
```

## Key design decisions

**Reach table cache.** The 1-D reach coordinates (`feature_id`, `latitude`, `longitude`, `order`,
`gage_id`) are each a single chunk. They are read once (~25 s) and saved as Parquet in
`~/.cache/nwm-flow/`, which makes later starts instant. The DataFrame row order matches the store's
`feature_id` axis, so a row position *is* the integer index used with `isel`.

**USGS gauges.** `gauges.py` requests the `combined-metadata` collection of the USGS Water Data
OGC API with `parameter_code=00060` (discharge) and `statistic_id=00003` (daily mean). One request
returns all ~25,900 series in a few seconds; paging links are followed if the API ever splits the list.
Series are merged per site (earliest begin, latest end), restricted to the CONUS box and cached as
Parquet for `MAX_AGE_DAYS` (30). A failed download falls back to a stale cache. In `app.py` the gauges
are one `folium.GeoJson` layer drawn on a canvas (`prefer_canvas=True`); a gauge click is recognised by
the site number in the clicked object's tooltip, and gauges link to reaches through the NWM `gage_id`.

**Observed vs simulated.** `fetch_observed` reads the `daily` collection (one request per gauge and
period; a full 44-year record is ~16,000 rows, well under the 50,000 page limit). When a site has more
than one daily discharge series, the longest is kept. Values arrive in ft³/s and are converted to m³/s.
The app caches observations for a day (`st.cache_data`) and compares NWM daily means (UTC days) with
USGS daily means (local days); monthly values come from `monthly_mean`, which drops incomplete months
so a gap in the record does not bias a month.

**Nearest-reach search.** Lat/lon are converted to 3-D unit vectors and indexed with
`scipy.spatial.cKDTree`. Euclidean (chord) distance between unit vectors is monotonic in
great-circle distance, so the nearest neighbours are exact. Chord length converts to km with
`2R·asin(c/2)`. With a stream-order filter, the query widens (×4) until `k` matching reaches are found.

**feature_id lookup.** `argsort` + `np.searchsorted` instead of a dict: memory-light for 2.8M IDs and
vectorised.

**Chunk-aligned fetching.** `fetch_streamflow` loads the selection in time blocks of
`12 × TIME_CHUNK` hours whose edges line up with the store's chunk boundaries, so no chunk is downloaded
twice. Each block runs on dask's threaded scheduler (16 workers), which issues parallel S3 GETs. Blocks
exist only to report progress. Larger blocks would not make the download faster.

**Cost estimate.** `distinct(index // FEATURE_CHUNK) × time_chunks_spanned × CHUNK_MB`. This is exact in
chunk count and approximate in MB. The UI time hint assumes ~5 MB/s (`ASSUMED_MBPS` in `app.py`).

**Resampling is done in the UI from cached hourly data.** Changing the time step does not refetch.
`state.result` stores `(request_key, hourly_df)`, and results are shown only while the reach selection and
dates match `request_key`.

**Zarr 3 with a Zarr v2 store.** Current xarray requires zarr ≥ 3. The store is Zarr format 2, so
`open_chrtout` passes `zarr_format=2` and `consolidated=True` to skip format detection and per-array
metadata requests.

## Streamlit notes

- `get_dataset()` and `get_reaches()` use `st.cache_resource`, so they are shared across sessions and reruns.
- The map uses `streamlit-folium` with `returned_objects=["last_clicked"]` so panning or zooming does not
  trigger reruns. Only clicks do.
- The candidate table uses `st.dataframe(on_select="rerun", selection_mode="multi-row")`
  (Streamlit ≥ 1.35).

## Running the tests

```bash
source .venv/bin/activate
pytest tests/ -q
```

The tests hit the live bucket: they build the reach cache if needed and download one month for one reach
(about 10 MB). They check:

- nearest-reach search snaps to the gauged Potomac reach (feature_id 4512772, USGS 01646500)
- feature_id lookup, including the error for unknown IDs
- fetched values are finite, non-negative and have the right length
- daily/monthly resampling and CSV header content
- the USGS gauge list and the observed-flow download, and the fit statistics

You can also script the UI with Streamlit's `streamlit.testing.v1.AppTest`. The folium map component
does not render there, but forms, buttons and the download flow do.

## Extending

| Goal | Where |
|---|---|
| Another variable (e.g. `velocity`) | Parameterise the variable name in `fetch_streamflow`. The chunking is the same for all CHRTOUT variables. Add a selector in `app.py`. |
| NWM v2.1 or another domain | Change `CHRTOUT_URL` in `store.py`, check the chunk sizes in the store's `.zmetadata`, and use a different `CACHE_PATH` in `reaches.py`. |
| Search by USGS gage ID | Look the site up in `load_gauges()` and use `get_gauge_reaches()` in `app.py`. |
| Other export formats | Add a function next to `to_csv_bytes` (e.g. `df.to_parquet`, or `xarray` → NetCDF) and another `st.download_button`. |
| Local units (cfs) | Multiply by 35.3147 before export, and label the CSV header accordingly. |

To inspect the store's structure without Python:

```bash
curl -s https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/CONUS/zarr/chrtout.zarr/.zmetadata | less
```

## Dependencies

| Package | Why |
|---|---|
| xarray, zarr (≥ 3), s3fs, dask | Lazy, parallel reading of the Zarr store from S3 |
| numpy, pandas, pyarrow | Arrays, time series, Parquet cache |
| scipy | KD-tree for nearest-reach search |
| streamlit, streamlit-folium, folium | Web UI and interactive map |
| pytest | Tests |
