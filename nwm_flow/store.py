"""Access to the NWM v3.0 CONUS Retrospective channel-output Zarr store on AWS.

The bucket is part of the AWS Open Data program: it is public and read anonymously,
so no AWS account or credentials are needed.
"""
import xarray as xr

CHRTOUT_URL = "s3://noaa-nwm-retrospective-3-0-pds/CONUS/zarr/chrtout.zarr"
STORAGE_OPTIONS = {"anon": True}

# Chunk layout of `streamflow` (time, feature_id) in the store.
TIME_CHUNK = 672        # hours (28 days)
FEATURE_CHUNK = 30_000  # reaches
CHUNK_MB = 4.5          # typical compressed size of one chunk


def open_chrtout() -> xr.Dataset:
    """Open the store lazily; only metadata is read here."""
    return xr.open_zarr(CHRTOUT_URL, storage_options=STORAGE_OPTIONS,
                        consolidated=True, zarr_format=2)
