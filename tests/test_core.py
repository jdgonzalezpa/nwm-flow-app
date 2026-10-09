"""Smoke tests against the live AWS dataset (need internet access)."""
import numpy as np
import pytest

from nwm_flow import estimate, fetch_streamflow, load_reach_table, open_chrtout, resample, to_csv_bytes

POTOMAC = 4512772  # reach at USGS gage 01646500, Potomac River near Washington DC


@pytest.fixture(scope="module")
def ds():
    return open_chrtout()


@pytest.fixture(scope="module")
def reaches():
    return load_reach_table()


def test_nearest_reach_snaps_to_potomac(reaches):
    near = reaches.nearest_reaches(38.9497, -77.1275, k=3, min_order=4)
    assert near.loc[0, "feature_id"] == POTOMAC
    assert near.loc[0, "distance_km"] < 1
    assert (near["order"] >= 4).all()


def test_feature_id_lookup(reaches):
    idx = reaches.index_for_feature_ids([POTOMAC])
    assert reaches.df["feature_id"].iloc[idx[0]] == POTOMAC
    with pytest.raises(KeyError):
        reaches.index_for_feature_ids([123])


def test_fetch_one_month(ds, reaches):
    idx = reaches.index_for_feature_ids([POTOMAC])
    assert estimate(ds, idx, "2010-06-01", "2010-06-30").chunks in (1, 2)
    df = fetch_streamflow(ds, idx, "2010-06-01", "2010-06-30")
    assert len(df) == 720
    assert list(df.columns) == [POTOMAC]
    assert np.isfinite(df.values).all() and (df.values >= 0).all()

    daily = resample(df, "D")
    assert len(daily) == 30 and (daily["n_hours"] == 24).all()
    assert len(resample(df, "MS")) == 1
    csv = to_csv_bytes(daily, reaches.df.iloc[idx]).decode()
    assert csv.startswith("#") and "01646500" in csv
