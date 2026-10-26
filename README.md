# NWM Retrospective streamflow downloader

A small local web app (and Python library) to download **hourly, daily or monthly river flow** (m³/s)
for any river reach in the contiguous US from the
[**NOAA National Water Model (NWM) v3.0 CONUS Retrospective**](https://registry.opendata.aws/nwm-archive/)
simulation, **1979-02-01 to 2023-01-31**.

It reads the public Zarr store on AWS directly. **No AWS account is needed.**

## Features

- 🗺️ Pick rivers by **clicking a map**, typing **lat/lon**, or entering NWM **feature_ids**
- 📡 Shows **USGS streamflow gauges** on the map (official USGS Water Data API); click one to add its NWM reach
- 🔎 Lists the nearest reaches with distance, **stream order** and **USGS gage** ID, so you pick the right river
- 📏 Shows a **download-size estimate** before fetching
- ⏱️ **Hourly, daily-mean or monthly-mean** output, with a progress bar during download
- 📈 Plot preview and summary statistics
- ⚖️ **Compare with USGS observations** for gauged reaches: overlay chart, r, NSE, KGE and volume bias
- 💾 **CSV export** (optionally with metadata header lines)
- 🐍 The same functions are available as a Python API for scripting

## Quick start

```bash
git clone https://github.com/jdgonzalezpa/nwm-flow-app.git
cd nwm-flow-app
python3 -m venv .venv            # if this fails: sudo apt install python3-venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open <http://localhost:8501>. The first start downloads the list of ~2.8 million river reaches
(~60 MB, under a minute) and caches it in `~/.cache/nwm-flow/`.

Then:

1. **Choose reaches.** Click the map near a river (or type coordinates), tick reaches in the table, press *Add*.
2. **Pick dates and time step.**
3. **Fetch streamflow** and **Download CSV**.

## Download speed in brief

The dataset is stored in blocks of 28 days × 30,000 reaches (~4.5 MB each), and whole blocks must be read.
For one reach at ~5 MB/s:

| Period | Data | Time |
|---|---|---|
| 1 year | ~60 MB | ~15–30 s |
| 10 years | ~600 MB | ~2–4 min |
| Full record (44 yr) | ~2.6 GB | ~9–15 min |

## Python

```python
from nwm_flow import open_chrtout, load_reach_table, fetch_streamflow, resample

ds, reaches = open_chrtout(), load_reach_table()
idx = reaches.nearest_reaches(38.9497, -77.1275, k=1, min_order=4)["index"].to_numpy()  # Potomac, USGS 01646500
daily = resample(fetch_streamflow(ds, idx, "2015-01-01", "2015-12-31"), "D")
```

## Documentation

| Document | Contents |
|---|---|
| [User guide](docs/user-guide.md) | Installation, every step of the app, CSV format, tips |
| [About the dataset](docs/dataset.md) | What the NWM Retrospective is, the S3/Zarr layout, chunking, caveats |
| [Python API](docs/python-api.md) | Library reference and scripting examples |
| [Developer guide](docs/developer-guide.md) | Architecture, design decisions, tests, how to extend |
| [Troubleshooting & FAQ](docs/troubleshooting.md) | Common problems and data questions |

## Important caveat

NWM Retrospective values are **model simulations, not observations**. Compare with USGS gauges where
possible before relying on them.

## Data source and license

Data: NOAA National Water Model CONUS Retrospective Dataset, via the
[AWS Registry of Open Data](https://registry.opendata.aws/nwm-archive/).
This project is not affiliated with or endorsed by NOAA or AWS.

Code: [MIT License](LICENSE).
