"""Streamlit app: download NWM v3.0 Retrospective streamflow for chosen river reaches.

Run with:  streamlit run app.py
"""
import time
from datetime import date

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from nwm_flow import estimate, fetch_streamflow, load_reach_table, open_chrtout, resample, to_csv_bytes

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


ds = get_dataset()
reaches = get_reaches()
state = st.session_state
state.setdefault("selected", {})   # feature_id -> reach row (dict)
state.setdefault("point", None)    # (lat, lon) used to search for nearby reaches
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
    center = state.point or (39.5, -98.35)
    fmap = folium.Map(location=center, zoom_start=11 if state.point else 4, tiles="OpenStreetMap")
    if state.point:
        folium.Marker(state.point, tooltip="Search point", icon=folium.Icon(color="red")).add_to(fmap)
    for fid, r in state.selected.items():
        folium.CircleMarker((r["latitude"], r["longitude"]), radius=7, color="#1f77b4", fill=True,
                            tooltip=f"Selected: {fid}").add_to(fmap)
    clicked = st_folium(fmap, height=450, use_container_width=True, returned_objects=["last_clicked"])
    if clicked and clicked.get("last_clicked"):
        pt = (round(clicked["last_clicked"]["lat"], 5), round(clicked["last_clicked"]["lng"], 5))
        if pt != state.point:
            state.point = pt
            st.rerun()
    st.caption("Click on (or very near) the river you are interested in.")

with tab_coords:
    with st.form("coords"):
        c1, c2 = st.columns(2)
        lat = c1.number_input("Latitude", value=state.point[0] if state.point else 38.9497,
                              min_value=20.0, max_value=55.0, format="%.5f")
        lon = c2.number_input("Longitude (negative = west)", value=state.point[1] if state.point else -77.1275,
                              min_value=-130.0, max_value=-60.0, format="%.5f")
        if st.form_submit_button("Find nearest reaches"):
            state.point = (lat, lon)
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
elif state.result:
    st.info("Selection or period changed. Press **Fetch streamflow** again.")
