# User guide

This guide walks through installing and using the NWM Retrospective streamflow downloader.
You do not need an AWS account or any prior experience with the National Water Model.

- [Requirements](#requirements)
- [Installation](#installation)
- [Starting the app](#starting-the-app)
- [Step 1: Choose river reaches](#step-1-choose-river-reaches)
- [Step 2: Period and time step](#step-2-period-and-time-step)
- [Step 3: Download](#step-3-download)
- [Step 4: Results and CSV](#step-4-results-and-csv)
- [The CSV file](#the-csv-file)
- [Tips](#tips)

## Requirements

- Linux, macOS, or Windows with WSL (Windows Subsystem for Linux)
- Python 3.10 or newer
- An internet connection. Downloads read directly from Amazon S3, so faster connections help a lot.
- About 100 MB of disk space for the Python packages and the reach cache

## Installation

```bash
git clone https://github.com/jdgonzalezpa/nwm-flow-app.git
cd nwm-flow-app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If `python3 -m venv` fails on Ubuntu/Debian, install the venv package first: `sudo apt install python3-venv`.

## Starting the app

```bash
cd nwm-flow-app
source .venv/bin/activate
streamlit run app.py
```

Streamlit prints a local URL, usually <http://localhost:8501>. Open it in a browser.
On WSL, the Windows browser can open `localhost` addresses served from Linux.

To stop the app, press `Ctrl+C` in the terminal.

**First start:** the app downloads the coordinates and attributes of all 2,776,734 NWM river reaches
(about 60 MB, around 25 s to 1 min). They are saved to `~/.cache/nwm-flow/reaches_v3.parquet`, so later
starts are instant.

## Step 1: Choose river reaches

The NWM splits every river in the contiguous US into short segments called **reaches**. Each reach
has a numeric ID called a **feature_id** (the same as the NHDPlus v2 COMID). You download flow for one or
more reaches.

There are three ways to find them:

| Tab | Use when |
|---|---|
| 🗺️ **Map** | You want to point at a river. Zoom in and click on, or very near, the river. |
| 📍 **Lat / lon** | You have coordinates (decimal degrees, longitude negative for the western hemisphere). |
| 🔢 **feature_id** | You already know the NWM feature_id(s). Paste them separated by commas, spaces or new lines, then press **Add**. |

After a map click or a coordinate search, a table lists the 8 nearest reaches:

| Column | Meaning |
|---|---|
| feature_id | NWM reach identifier |
| distance (km) | Great-circle distance from your point to the reach's reference point |
| stream order | River size (Strahler order): 1 = smallest headwater creek, 7–10 = large rivers |
| USGS gage | ID of the USGS streamgage located on this reach, if any |
| latitude / longitude | Reach reference point |

Tick one or more rows and press **Add N selected reach(es)**. Selected reaches appear as blue circles
on the map and in the **Selected reaches** table. **Clear selection** removes them all.

**Choosing the right reach.** A click on a big river often lands closer to a small tributary than to the
main stem. Raise the **Minimum stream order** slider to hide small streams. A reach with a USGS gage is
a good choice if you want to compare the simulation with observations.

## Step 2: Period and time step

- **Start date / End date**: anywhere in 1979-02-01 to 2023-01-31. The end date is inclusive.
- **Time step**:
  - *Hourly*: the raw model output.
  - *Daily mean*: average of the hourly values in each UTC day.
  - *Monthly mean*: average of the hourly values in each calendar month (UTC).

All times are **UTC**. Daily means are therefore UTC days, not local days.

You can change the time step after downloading without fetching again.

## Step 3: Download

Before downloading, the app shows an estimate such as:

> This request reads **14 data chunks (≈ 63 MB)**, under a minute.

The dataset is stored in blocks ("chunks") of 28 days × 30,000 reaches, and the app must download
whole blocks even when you need one reach. Roughly:

| Request (one reach) | Data read | Time at ~5 MB/s |
|---|---|---|
| 1 month | ~5–10 MB | a few seconds |
| 1 year | ~60 MB | ~15–30 s |
| 10 years | ~600 MB | ~2–4 min |
| Full record (44 years) | ~2.6 GB | ~9–15 min |

Adding more reaches costs nothing extra when they fall in the same blocks. Reaches with similar
feature_ids, such as neighbouring segments of one river, often do. Reaches far apart in feature_id
multiply the cost. Requests above ~2 GB show a warning.

Press **⬇️ Fetch streamflow**. A progress bar shows the elapsed and estimated remaining time.

## Step 4: Results and CSV

When the download finishes, the app shows:

- a line chart of flow (m³/s) for each reach at the selected time step
- summary statistics (count, mean, standard deviation, min, quartiles, max)
- a **💾 Download CSV** button

If you change the selected reaches or the dates, the results are cleared and you need to fetch again.

## The CSV file

File name pattern: `nwm_v3_streamflow_<step>_<start>_<end>.csv`, for example
`nwm_v3_streamflow_daily_20150101_20151231.csv`.

Example (daily, with the optional description lines ticked):

```text
# NOAA National Water Model v3.0 CONUS Retrospective, CHRTOUT streamflow
# Source: s3://noaa-nwm-retrospective-3-0-pds/CONUS/zarr/chrtout.zarr
# Units: m3/s; times in UTC; columns are NWM feature_id (reach) values
# feature_id 4512772: lat 38.94818, lon -77.12970, stream order 7, USGS gage 01646500
date_utc,4512772,n_hours
2015-01-01,271.107,24
2015-01-02,266.795,24
```

- First column: time (`time_utc`, `date_utc` or `month_utc`).
- One column per reach, named by feature_id, values in **m³/s** (3 decimals).
- `n_hours` (daily/monthly only): number of hourly values averaged into each row. Check it to spot
  partial first or last periods.
- The `#` description lines are **off by default** so the file opens cleanly in Excel. With pandas you can
  keep them and read the file with `pd.read_csv(path, comment="#")`.

To convert to ft³/s (cfs), multiply by 35.3147.

## Tips

- Try a short period first to check that you chose the right reach.
- For long records of many scattered reaches, consider running the app (or the [Python API](python-api.md))
  on a cloud machine in AWS region `us-east-1`. Downloads there are much faster.
- See [troubleshooting.md](troubleshooting.md) if something goes wrong.
