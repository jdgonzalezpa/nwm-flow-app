"""Smoke tests against the live AWS dataset (need internet access)."""
import numpy as np
import pytest

import pandas as pd

from nwm_flow import (estimate, fetch_observed, fetch_streamflow, fit_stats, load_gauges, load_reach_table,
                      monthly_mean, nearest_gauge, open_chrtout, resample, to_csv_bytes)

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


def test_usgs_gauges():
    gauges = load_gauges()
    assert len(gauges) > 20_000 and gauges["site_no"].is_unique
    g = nearest_gauge(gauges, 38.9497, -77.1275)
    assert g["site_no"] == "01646500" and g["begin"].year == 1930


def test_observed_vs_simulated(ds, reaches):
    obs = fetch_observed("01646500", "2010-06-01", "2010-06-30")
    assert len(obs) == 30 and (obs > 0).all()            # m3/s, one value per day
    sim = resample(fetch_streamflow(ds, reaches.index_for_feature_ids([POTOMAC]), "2010-06-01", "2010-06-30"), "D")
    stats = fit_stats(sim[POTOMAC], obs)
    assert stats["n"] == 30 and 0.5 < stats["mean_sim"] / stats["mean_obs"] < 2   # same order of magnitude
    assert len(monthly_mean(obs)) == 1 and monthly_mean(obs.iloc[:20]).empty


def test_fit_stats_perfect_match():
    obs = pd.Series([1.0, 2.0, 4.0, 3.0], index=pd.date_range("2020-01-01", periods=4))
    stats = fit_stats(obs, obs)
    assert stats["NSE"] == 1 and stats["KGE"] == 1 and stats["pbias"] == 0
