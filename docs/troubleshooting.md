# Troubleshooting and FAQ

## Installation

**`python3 -m venv .venv` fails with "ensurepip is not available".**
Install the venv module: `sudo apt install python3-venv`, then retry.

**`streamlit: command not found`.**
Activate the virtual environment first: `source .venv/bin/activate`.

**`TypeError: open_group() got an unexpected keyword argument 'zarr_format'`.**
You have zarr 2 with a recent xarray. Upgrade: `pip install "zarr>=3"`.

## Running

**The browser doesn't open / I can't reach localhost:8501 from Windows.**
Open <http://localhost:8501> manually in the Windows browser. If port 8501 is busy, Streamlit picks
another port. Use the URL printed in the terminal, or choose one: `streamlit run app.py --server.port 8502`.

**The first start is slow.**
On first use, the app downloads the reach list (~60 MB). Later starts read it from
`~/.cache/nwm-flow/reaches_v3.parquet`.

**I want to refresh or delete the cache.**
Delete `~/.cache/nwm-flow/`. The app rebuilds it on the next start.

## Downloads

**Downloads are slow.**
Expected: the data come from AWS `us-east-1` in 4–5 MB chunks, and a full 44-year record for one reach
reads ~2.6 GB. To speed things up:
- request shorter periods
- group reaches with nearby feature_ids (they share chunks)
- run the code on a cloud machine in AWS `us-east-1`

**"Download failed: …" with a network or timeout error.**
Usually a temporary network or S3 problem. Press **Fetch streamflow** again. For very long requests,
split the period into pieces.

**"The selected period is outside the dataset".**
v3.0 Retrospective covers 1979-02-01 to 2023-01-31 only.

## Data questions

**The nearest reach is a small creek, not the river I clicked.**
Each reach is located by a single reference point. Raise **Minimum stream order** (e.g. to 4–6 for
large rivers) or zoom in and click closer to the river line.

**How do I find the reach for a USGS gage?**
Gauged reaches show their gage ID in the candidate table. Search near the gage location, or in Python:
`reaches.df[reaches.df.gage_id == "01646500"]`.

**What are the units and time zone?**
Cubic metres per second (m³/s), UTC. Multiply by 35.3147 for cubic feet per second.

**Why does the CSV have an `n_hours` column?**
For daily and monthly means it counts the hourly values in each period, so you can spot partial periods
at the start or end of your range (e.g. a month with only 120 hours).

**Can I trust these numbers?**
They are model simulations. Performance varies by region, especially in snow-dominated, arid,
heavily regulated (dams, diversions) and urban basins. Compare with USGS observations where available.

**Excel shows strange first lines.**
You ticked "Include description lines". Download again with it unticked, or delete the `#` lines.
