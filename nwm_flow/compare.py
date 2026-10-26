"""Goodness-of-fit statistics between simulated (NWM) and observed (USGS) flow."""
import numpy as np
import pandas as pd


def fit_stats(sim: pd.Series, obs: pd.Series) -> dict:
    """Statistics over the dates where both series have a value.

    n, mean_obs, mean_sim, r (Pearson correlation), NSE (Nash-Sutcliffe efficiency),
    KGE (Kling-Gupta efficiency, 2009) and pbias (% volume bias, positive = NWM too high).
    """
    both = pd.concat([sim.rename("sim"), obs.rename("obs")], axis=1).dropna()
    s, o = both["sim"].to_numpy(), both["obs"].to_numpy()
    out = {"n": len(both), "mean_obs": np.nan, "mean_sim": np.nan,
           "r": np.nan, "NSE": np.nan, "KGE": np.nan, "pbias": np.nan}
    if len(both) < 2 or o.std() == 0 or o.sum() == 0:
        return out
    r = np.corrcoef(s, o)[0, 1]
    alpha, beta = s.std() / o.std(), s.mean() / o.mean()
    out.update(mean_obs=o.mean(), mean_sim=s.mean(), r=r,
               NSE=1 - ((s - o) ** 2).sum() / ((o - o.mean()) ** 2).sum(),
               KGE=1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2),
               pbias=100 * (s.sum() - o.sum()) / o.sum())
    return out


def monthly_mean(daily: pd.Series, min_fraction=0.9) -> pd.Series:
    """Monthly mean of daily values; months with fewer than min_fraction of their days are dropped."""
    grouped = daily.dropna().resample("MS")
    means, counts = grouped.mean(), grouped.count()
    return means[counts >= min_fraction * means.index.days_in_month]
