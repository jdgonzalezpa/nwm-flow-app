"""Streamlit app: download NWM v3.0 Retrospective streamflow for chosen river reaches.

Run with:  streamlit run app.py
"""
import re
import time
from datetime import date

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from nwm_flow import (estimate, fetch_observed, fetch_streamflow, fit_stats, load_gauges, load_reach_table,
                      monthly_mean, nearest_gauge, open_chrtout, resample, to_csv_bytes)
from nwm_flow.gauges import CFS_PER_M3S, GAUGE_PAGE_URL

ASSUMED_MBPS = 5.0           # typical download speed from AWS us-east-1; only used for the time hint
WARN_MB = 2000
DATA_START, DATA_END = date(1979, 2, 1), date(2023, 1, 31)
AGGREGATIONS = {"Hourly": None, "Daily mean": "D", "Monthly mean": "MS"}

st.set_page_config(page_title="NWM Retrospective Flow Downloader", page_icon="🌊", layout="wide")


@st.cache_resource(show_spinner="Connecting to the NWM dataset on AWS…")
def get_dataset():
    return open_chrtout()


@st.cache_resource(show_spinner="Loading the list of NWM river reaches (first run only, ~1 min)…")
def get_reaches():
    return load_reach_table()


def record_period(g, fmt="%Y", sep="–"):
    """Daily record period of a gauge, e.g. '1930–2026'; some gauges have no dates."""
    if pd.isna(g.begin) or pd.isna(g.end):
        return "period unknown"
    return f"{g.begin:{fmt}}{sep}{g.end:{fmt}}"


@st.cache_resource(show_spinner="Loading USGS streamflow gauges (first run only, a few seconds)…")
def get_gauges():
    """Gauges table and its GeoJSON map layer data, or (None, None) if USGS cannot be reached."""
    try:
        gauges = load_gauges()
    except Exception:
        return None, None
    features = [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [g.longitude, g.latitude]},
         "properties": {"site": g.site_no, "name": g.name, "active": bool(g.active),
                        "record": record_period(g) + (" (active)" if g.active else "")}}
        for g in gauges.itertuples()
    ]
    return gauges, {"type": "FeatureCollection", "features": features}


@st.cache_data(ttl=86400, show_spinner="Downloading USGS observed daily flow…")
def get_observed(site_no, start, end):
    return fetch_observed(site_no, start, end)


@st.cache_resource
def get_gauge_reaches():
    """USGS site number -> position of the NWM reach linked to that gauge."""
    linked = reaches.df["gage_id"].dropna()
    return dict(zip(linked, linked.index))


ds = get_dataset()
reaches = get_reaches()
gauges, gauges_geojson = get_gauges()
state = st.session_state
state.setdefault("selected", {})   # feature_id -> reach row (dict)
state.setdefault("point", None)    # (lat, lon) used to search for nearby reaches
state.setdefault("gauge", None)    # USGS site number of the clicked gauge
state.setdefault("last_click", None)
state.setdefault("last_obj", None)
state.setdefault("result", None)


def add_reaches(rows: pd.DataFrame):
    for r in rows.to_dict("records"):
        state.selected[int(r["feature_id"])] = r
    state.result = None


st.title("🌊 NWM Retrospective streamflow downloader")
st.caption(
    "Hourly simulated river flow (m³/s) from NOAA's National Water Model v3.0 CONUS Retrospective "
    "(1979-02-01 to 2023-01-31), read directly from the public AWS Open Data bucket. No AWS account needed."
)

# ---------------------------------------------------------------- 1. locations
st.header("1. Choose river reaches")
st.markdown(
    "The NWM splits every river in the US into short **reaches**, each with a numeric **feature_id**. "
    "Click the map or type coordinates to find the reaches nearby, or enter feature_ids you already know."
)
tab_map, tab_coords, tab_ids = st.tabs(["🗺️ Map", "📍 Lat / lon", "🔢 feature_id"])

with tab_map:
    show_gauges = gauges is not None and st.checkbox(
        "Show USGS streamflow gauges", value=True,
        help="All USGS gauges with a daily streamflow record, from the USGS Water Data API "
             "(the source of the USGS National Water Dashboard).")
    center = state.point or (39.5, -98.35)
    fmap = folium.Map(location=center, zoom_start=11 if state.point else 4, tiles="OpenStreetMap",
                      prefer_canvas=True)
    if show_gauges:
        folium.GeoJson(
            gauges_geojson, name="USGS gauges",
            marker=folium.CircleMarker(radius=4, weight=1, fill=True, fill_opacity=0.8),
            style_function=lambda f: {"color": "#1a7f37" if f["properties"]["active"] else "#6e6e6e",
                                      "fillColor": "#2ca02c" if f["properties"]["active"] else "#bdbdbd"},
            tooltip=folium.GeoJsonTooltip(["site", "name", "record"], aliases=["USGS gage", "Name", "Daily record"]),
        ).add_to(fmap)
    if state.point:
        folium.Marker(state.point, tooltip="Search point", icon=folium.Icon(color="red")).add_to(fmap)
    for fid, r in state.selected.items():
        folium.CircleMarker((r["latitude"], r["longitude"]), radius=7, color="#1f77b4", fill=True,
                            tooltip=f"Selected: {fid}").add_to(fmap)
    clicked = st_folium(fmap, height=450, use_container_width=True,
                        returned_objects=["last_clicked", "last_object_clicked", "last_object_clicked_tooltip"])
    if clicked:
        obj, click = clicked.get("last_object_clicked"), clicked.get("last_clicked")
        site = re.search(r"USGS gage\s+(\d{8,15})", clicked.get("last_object_clicked_tooltip") or "")
        if obj and obj != state.last_obj and site and show_gauges:
            # A gauge was clicked: search around the gauge itself rather than the click position.
            state.last_obj, state.last_click = obj, click
            g = gauges[gauges["site_no"] == site.group(1)]
            g = g.iloc[0] if len(g) else nearest_gauge(gauges, obj["lat"], obj["lng"])
            state.gauge = g["site_no"]
            state.point = (round(g["latitude"], 5), round(g["longitude"], 5))
            st.rerun()
        elif click and click != state.last_click:
            state.last_click, state.last_obj = click, obj
            pt = (round(click["lat"], 5), round(click["lng"], 5))
            if pt != state.point:
                state.point, state.gauge = pt, None
                st.rerun()
    st.caption("Click on (or very near) the river you are interested in, or click a USGS gauge.")
    if show_gauges:
        st.caption("🟢 active USGS gauge (daily record up to date) · ⚪ discontinued gauge. "
                   "Hover a gauge for its name and record period.")
    elif gauges is None:
        st.caption("USGS gauge locations could not be loaded (no connection to api.waterdata.usgs.gov).")

with tab_coords:
    with st.form("coords"):
        c1, c2 = st.columns(2)
        lat = c1.number_input("Latitude", value=state.point[0] if state.point else 38.9497,
                              min_value=20.0, max_value=55.0, format="%.5f")
        lon = c2.number_input("Longitude (negative = west)", value=state.point[1] if state.point else -77.1275,
                              min_value=-130.0, max_value=-60.0, format="%.5f")
        if st.form_submit_button("Find nearest reaches"):
            state.point, state.gauge = (lat, lon), None
            st.rerun()

with tab_ids:
    with st.form("ids"):
        text = st.text_area("feature_id(s), separated by commas, spaces or new lines", placeholder="4512772")
        if st.form_submit_button("Add"):
            try:
                ids = [int(t) for t in text.replace(",", " ").split()]
                if ids:
                    add_reaches(reaches.df.iloc[reaches.index_for_feature_ids(ids)])
                    st.rerun()
            except ValueError:
                st.error("feature_ids must be whole numbers.")
            except KeyError as e:
                st.error(e.args[0])

if state.gauge and gauges is not None:
    g = gauges[gauges["site_no"] == state.gauge].iloc[0]
    status = "active" if g["active"] else "discontinued"
    area = f" · drainage area {g['drainage_area_sqmi']:,.0f} mi²" if pd.notna(g["drainage_area_sqmi"]) else ""
    st.subheader(f"USGS gage {g['site_no']}: {g['name']}")
    st.markdown(f"Daily streamflow record {record_period(g, '%Y-%m-%d', ' to ')} ({status}){area} · "
                f"[USGS page]({GAUGE_PAGE_URL.format(g['site_no'])})")
    pos = get_gauge_reaches().get(g["site_no"])
    if pos is None:
        st.caption("No NWM reach is linked to this gauge. Pick the matching reach from the table below.")
    else:
        linked = reaches.df.iloc[[pos]]
        fid = int(linked["feature_id"].iloc[0])
        if st.button(f"Add NWM reach {fid} (linked to this gauge)", disabled=fid in state.selected):
            add_reaches(linked)
            st.rerun()

if state.point:
    st.subheader(f"Reaches near {state.point[0]:.5f}, {state.point[1]:.5f}")
    min_order = st.slider(
        "Minimum stream order", 1, 10, 1,
        help="Stream order measures river size: 1 = smallest headwater creeks, 7+ = large rivers. "
             "Raise it if the nearest results are tiny tributaries instead of the main river.",
    )
    cand = reaches.nearest_reaches(*state.point, k=8, min_order=min_order)
    show = cand[["feature_id", "distance_km", "order", "gage_id", "latitude", "longitude"]]
    pick = st.dataframe(
        show, hide_index=True, on_select="rerun", selection_mode="multi-row",
        column_config={"distance_km": st.column_config.NumberColumn("distance (km)", format="%.2f"),
                       "order": "stream order", "gage_id": "USGS gage"},
    )
    rows = pick.selection.rows
    if st.button(f"Add {len(rows)} selected reach(es)", disabled=not rows):
        add_reaches(cand.iloc[rows])
        st.rerun()
    st.caption("Tick rows in the table, then press Add. A USGS gage ID means that reach has an observation station.")

if state.selected:
    st.subheader("Selected reaches")
    sel = pd.DataFrame(state.selected.values())[["feature_id", "latitude", "longitude", "order", "gage_id"]]
    st.dataframe(sel, hide_index=True, column_config={"order": "stream order", "gage_id": "USGS gage"})
    if st.button("Clear selection"):
        state.selected, state.result = {}, None
        st.rerun()
else:
    st.info("No reaches selected yet.")
    st.stop()

# ---------------------------------------------------------------- 2. period
st.header("2. Period and time step")
c1, c2, c3 = st.columns(3)
start = c1.date_input("Start date", date(2013, 1, 1), min_value=DATA_START, max_value=DATA_END)
end = c2.date_input("End date (inclusive)", DATA_END, min_value=DATA_START, max_value=DATA_END)
agg = c3.radio("Time step", list(AGGREGATIONS), horizontal=True)
if end < start:
    st.error("End date must be after start date.")
    st.stop()

# ---------------------------------------------------------------- 3. download
st.header("3. Download")
indices = reaches.index_for_feature_ids(list(state.selected))
est = estimate(ds, indices, start, end)
minutes = est.megabytes / ASSUMED_MBPS / 60
st.markdown(
    f"This request reads **{est.chunks:,} data chunks (≈ {est.megabytes:,.0f} MB)**, "
    f"roughly **{minutes:.0f}–{2 * minutes:.0f} min** at typical speeds."
    if minutes >= 1 else
    f"This request reads **{est.chunks:,} data chunks (≈ {est.megabytes:,.0f} MB)**, under a minute."
)
st.caption(
    "The dataset is stored in blocks of 28 days × 30,000 reaches, so whole blocks must be downloaded "
    "even for a single reach. Reaches with nearby feature_ids often share blocks and add little extra."
)
if est.megabytes > WARN_MB:
    st.warning("This is a large download. Consider a shorter period for a first try.")

request = (tuple(state.selected), start, end)
if st.button("⬇️ Fetch streamflow", type="primary"):
    bar = st.progress(0.0, text="Starting…")
    t0 = time.time()

    def progress(frac):
        elapsed = time.time() - t0
        remaining = elapsed / frac * (1 - frac)
        bar.progress(frac, text=f"{frac:.0%} done · {elapsed:.0f} s elapsed · ~{remaining:.0f} s left")

    try:
        state.result = (request, fetch_streamflow(ds, indices, start, end, progress))
        bar.progress(1.0, text=f"Done in {time.time() - t0:.0f} s")
    except Exception as e:  # network errors etc.: show them instead of crashing the app
        bar.empty()
        st.error(f"Download failed: {e}")

# ---------------------------------------------------------------- 4. results
if state.result and state.result[0] == request:
    hourly = state.result[1]
    out = resample(hourly, AGGREGATIONS[agg])
    flows = out.drop(columns="n_hours", errors="ignore")
    flows.columns = [str(c) for c in flows.columns]
    st.subheader(f"{agg} streamflow (m³/s)")
    st.line_chart(flows, y_label="m³/s")
    st.dataframe(flows.describe().T.round(2))

    meta = pd.DataFrame(state.selected.values())
    with_header = st.checkbox("Include description lines (starting with #) at the top of the CSV",
                              value=False, help="Leave unticked for the cleanest import into Excel.")
    name = f"nwm_v3_streamflow_{agg.split()[0].lower()}_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    st.download_button("💾 Download CSV", to_csv_bytes(out, meta, header=with_header), name, "text/csv")

    # ------------------------------------------------------------ comparison with USGS observations
    st.header("4. Compare with USGS observations")
    gauged = {fid: r["gage_id"] for fid, r in state.selected.items() if isinstance(r.get("gage_id"), str)}
    if not gauged:
        st.info("None of the selected reaches is linked to a USGS gauge. Pick a reach with a USGS gage ID "
                "(or click a gauge on the map) to compare the simulation with observations.")
        st.stop()
    fid = st.selectbox("Reach", list(gauged), format_func=lambda f: f"{f} · USGS gage {gauged[f]}")
    site = gauged[fid]
    try:
        obs_daily = get_observed(site, start, end)
    except Exception as e:  # network errors etc.
        st.error(f"Could not download USGS observations for {site}: {e}")
        st.stop()
    if obs_daily.empty:
        st.warning(f"USGS gage {site} has no daily streamflow values between {start} and {end}.")
        st.stop()

    sim_daily = hourly[fid].resample("D").mean()
    sim_daily.index.name = "date"
    series = {"Daily": (sim_daily, obs_daily), "Monthly": (monthly_mean(sim_daily), monthly_mean(obs_daily))}
    step = "Monthly" if agg == "Monthly mean" else "Daily"
    sim, obs = series[step]
    both = pd.DataFrame({"NWM (simulated)": sim, "USGS (observed)": obs})
    both.index.name = "month" if step == "Monthly" else "date"

    st.subheader(f"{step} mean flow at USGS gage {site} (m³/s)")
    st.line_chart(both, y_label="m³/s", color=["#1f77b4", "#ff7f0e"])
    stats = fit_stats(sim, obs)
    c = st.columns(4)
    c[0].metric("Correlation r", f"{stats['r']:.2f}", help="1 = perfect timing of highs and lows.")
    c[1].metric("NSE", f"{stats['NSE']:.2f}", help="Nash-Sutcliffe efficiency: 1 = perfect, 0 = no better "
                                                    "than the observed mean, < 0 = worse.")
    c[2].metric("KGE", f"{stats['KGE']:.2f}", help="Kling-Gupta efficiency: 1 = perfect. Combines correlation, "
                                                    "variability and bias.")
    c[3].metric("Volume bias", f"{stats['pbias']:+.1f} %", help="Positive = NWM simulates more water than observed.")
    table = pd.DataFrame({k: fit_stats(*v) for k, v in series.items()}).T
    table = table.rename(columns={"n": "values compared", "mean_obs": "mean observed (m³/s)",
                                  "mean_sim": "mean NWM (m³/s)", "pbias": "volume bias (%)"})
    st.dataframe(table.round(2).astype({"values compared": int}))
    st.caption(
        f"USGS daily means are converted from ft³/s to m³/s (÷ {CFS_PER_M3S}). Only days (or months) with both "
        "values are compared; months missing more than 10% of their days are left out. NWM days are UTC "
        "days and USGS days are local days, which shifts daily values by a few hours. "
        "NWM values are model simulations; differences from observations are model error, not download errors."
    )
    st.download_button(f"💾 Download {step.lower()} comparison CSV", both.to_csv(float_format="%.3f").encode(),
                       f"nwm_vs_usgs_{site}_{step.lower()}_{start:%Y%m%d}_{end:%Y%m%d}.csv", "text/csv")
elif state.result:
    st.info("Selection or period changed. Press **Fetch streamflow** again.")
