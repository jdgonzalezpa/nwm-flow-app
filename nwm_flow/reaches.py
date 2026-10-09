"""Reach (river segment) metadata: lookup by feature_id and nearest reach to a point."""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .store import open_chrtout

CACHE_PATH = Path.home() / ".cache" / "nwm-flow" / "reaches_v3.parquet"
EARTH_RADIUS_KM = 6371.0


def _unit_vectors(lat, lon):
    lat, lon = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])


class ReachTable:
    """All ~2.8M NWM reaches, in the same order as the store's feature_id axis."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        fid = df["feature_id"].to_numpy()
        self._sort = np.argsort(fid)
        self._sorted_fid = fid[self._sort]
        self._tree = None

    def index_for_feature_ids(self, ids) -> np.ndarray:
        """Positions of feature_ids along the store's feature_id axis."""
        ids = np.asarray(ids, dtype=np.int64)
        pos = np.searchsorted(self._sorted_fid, ids).clip(max=len(self._sorted_fid) - 1)
        found = self._sorted_fid[pos] == ids
        if not found.all():
            raise KeyError(f"Unknown NWM feature_id(s): {ids[~found].tolist()}")
        return self._sort[pos]

    def nearest_reaches(self, lat, lon, k=5, min_order=1) -> pd.DataFrame:
        """The k reaches closest to (lat, lon) with stream order >= min_order."""
        if self._tree is None:
            self._tree = cKDTree(_unit_vectors(self.df["latitude"], self.df["longitude"]))
        target = _unit_vectors([lat], [lon])[0]
        # Query extra neighbours so that filtering by stream order still leaves k results.
        n = k
        while True:
            chord, idx = self._tree.query(target, k=n)
            keep = self.df["order"].to_numpy()[idx] >= min_order
            if keep.sum() >= k or n >= len(self.df):
                break
            n *= 4
        chord, idx = chord[keep][:k], idx[keep][:k]
        out = self.df.iloc[idx].copy()
        out.insert(0, "index", idx)
        out["distance_km"] = 2 * EARTH_RADIUS_KM * np.arcsin(np.clip(chord / 2, 0, 1))
        return out.reset_index(drop=True)


def load_reach_table(refresh=False) -> ReachTable:
    """Load reach metadata, downloading it once (~60 MB) and caching it locally."""
    if CACHE_PATH.exists() and not refresh:
        return ReachTable(pd.read_parquet(CACHE_PATH))
    ds = open_chrtout()
    df = pd.DataFrame({
        "feature_id": ds["feature_id"].values.astype(np.int64),
        "latitude": ds["latitude"].values.astype(np.float32),
        "longitude": ds["longitude"].values.astype(np.float32),
        "order": ds["order"].values.astype(np.int16),
        "gage_id": pd.Series(ds["gage_id"].values).str.decode("utf-8").str.strip(),
    })
    df["gage_id"] = df["gage_id"].replace("", None)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE_PATH, index=False)
    return ReachTable(df)
