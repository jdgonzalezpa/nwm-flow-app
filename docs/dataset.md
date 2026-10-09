# About the dataset

## What is the NWM Retrospective?

The **National Water Model (NWM)** is a hydrologic model run by NOAA's Office of Water Prediction.
It simulates streamflow and other water-cycle variables over the whole contiguous United States (CONUS).
It is built on the WRF-Hydro framework, and its river network comes from NHDPlus Version 2.

The **Retrospective** (also called a reanalysis or historical simulation) is a long, continuous
run of the model driven by observed and analysed weather, rather than by forecasts. It gives a
consistent hourly flow record for about 2.7 million river reaches, including the many rivers that
have no streamgage.

This app uses **NWM v3.0 Retrospective**, which covers **1979-02-01 to 2023-01-31** (hourly, UTC).

> **The data are model simulations, not measurements.** Accuracy varies by region, season and river size.
> Where possible, compare against USGS observations before relying on the numbers.

Official resources:

- AWS Registry of Open Data: <https://registry.opendata.aws/nwm-archive/>
- NOAA OWP National Water Model: <https://water.noaa.gov/about/nwm>
- Bucket browser: <https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/index.html>

## Where the data live

The data are in a public Amazon S3 bucket under the AWS Open Data Sponsorship Program. Anyone can
read them anonymously, with no AWS account, credentials or charges to you.

| Item | Value |
|---|---|
| Bucket | `noaa-nwm-retrospective-3-0-pds` (region `us-east-1`) |
| Store used | `s3://noaa-nwm-retrospective-3-0-pds/CONUS/zarr/chrtout.zarr` |
| Format | Zarr v2, consolidated metadata, zstd compression |

The bucket also has other Zarr stores (`gwout`, `lakeout`, `ldasout`, `rtout`, `forcing`) and the original
NetCDF files. This app only uses `chrtout` (channel routing output).

## What is Zarr?

Zarr is a format for large multi-dimensional arrays stored as many small compressed files
("chunks") in cloud storage. A program can download only the chunks it needs instead of whole files.
That is what makes it possible to extract a time series from a ~100 TB dataset over a home connection.

## Structure of `chrtout.zarr`

Dimensions: `time` = 385,704 hours, `feature_id` = 2,776,734 reaches.

| Variable | Dims | Description |
|---|---|---|
| **`streamflow`** | time, feature_id | River flow, **m³/s**. Used by this app. |
| `velocity` | time, feature_id | Flow velocity, m/s |
| `q_lateral` | time, feature_id | Lateral inflow to the reach, m³/s |
| `qSfcLatRunoff`, `qBucket`, `qBtmVertRunoff` | time, feature_id | Runoff components |
| `time` | time | Hourly timestamps, `hours since 1979-02-01T01:00`, UTC |
| `feature_id` | feature_id | Reach ID (NHDPlus v2 COMID) |
| `latitude`, `longitude` | feature_id | Reach reference point, degrees |
| `order` | feature_id | Strahler stream order |
| `elevation` | feature_id | Reach elevation, m |
| `gage_id` | feature_id | USGS gage ID on the reach (blank for most reaches) |

`streamflow` is stored as 32-bit integers with `scale_factor = 0.01` and `missing_value = -999900`.
xarray applies these automatically, so you get floating-point m³/s with missing values as NaN.

### Chunking and what it means for download speed

Time-varying variables are chunked as **672 time steps (28 days) × 30,000 reaches**. Each compressed
chunk is about 4–5 MB.

Reading one value means downloading its whole chunk. So:

- **Time cost** grows with the period: one year ≈ 14 time chunks, the full record ≈ 574.
- **Reach cost** grows with the number of *distinct reach blocks*, where block = position along the
  `feature_id` axis divided by 30,000. Reaches in the same block are almost free to add.

Estimated download ≈ (distinct reach blocks) × (time chunks) × 4.5 MB.
The app uses this formula for the estimate it shows before each download.

The chunk layout suits "the whole CONUS for a few weeks" better than "one point for 44 years".
For many long point series, the fastest option is to run the code inside AWS `us-east-1`.

## Reach coordinates and stream order

Each reach has a single reference latitude/longitude. The app finds "nearest reaches" by great-circle
distance to these points, so on long reaches the closest reach to a click is not always the one whose
line passes under it. That is why the app shows several candidates along with stream order and distance.

Stream order (Strahler): 1 = headwater streams with no tributaries. Where two streams of order *n*
meet, the result has order *n + 1*. Large rivers in CONUS are typically 7–10.

## Other versions

NWM v2.1 Retrospective (1979–2020) is also on AWS (`s3://noaa-nwm-retrospective-2-1-zarr-pds`).
This app uses v3.0, which is newer and longer. To use v2.1 you would change `CHRTOUT_URL`
and check the chunk constants in `nwm_flow/store.py` (see the [developer guide](developer-guide.md)).

## Citation

When using these data, cite the dataset as recommended on the AWS registry page, for example:

> NOAA National Water Model CONUS Retrospective Dataset, https://registry.opendata.aws/nwm-archive,
> accessed <date>.
