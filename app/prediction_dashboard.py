"""
Streamlit dashboard for flight delay prediction.

Run:
    streamlit run app/prediction_dashboard.py
"""

from pathlib import Path
import sys

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model.train_delay_model import FEATURE_COLUMNS


MODEL_PATH = PROJECT_ROOT / "models" / "flight_delay_model.pkl"

CARRIERS = [
    "AA", "AS", "B6", "DL", "F9", "G4", "HA", "NK", "OO", "UA", "WN", "YV",
]

AIRPORTS = [
    "ATL", "BOS", "CLT", "DCA", "DEN", "DFW", "DTW", "EWR", "FLL", "IAD",
    "IAH", "JFK", "LAS", "LAX", "LGA", "MCO", "MIA", "MSP", "ORD", "PHX",
    "SEA", "SFO", "SLC", "TPA",
]

DAYS = {
    "Monday": 1,
    "Tuesday": 2,
    "Wednesday": 3,
    "Thursday": 4,
    "Friday": 5,
    "Saturday": 6,
    "Sunday": 7,
}


@st.cache_resource
def load_model():
    try:
        import joblib
    except ModuleNotFoundError:
        st.error("Missing dependency: joblib. Run `pip install -r requirements.txt`.")
        st.stop()

    if not MODEL_PATH.exists():
        st.error("Model file not found. Train the model first.")
        st.code("venv\\Scripts\\python.exe src\\model\\train_delay_model.py --year 2023 --max-rows-per-file 100000")
        st.stop()

    return joblib.load(MODEL_PATH)


def build_prediction_row(
    carrier: str,
    origin: str,
    dest: str,
    month: int,
    day_of_week: int,
    dep_hour: int,
    arr_hour: int,
    distance: float,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "carrier_code": carrier,
                "origin_airport": origin,
                "dest_airport": dest,
                "month": month,
                "day_of_week": day_of_week,
                "scheduled_departure_hour": dep_hour,
                "scheduled_arrival_hour": arr_hour,
                "distance_miles": distance,
            }
        ],
        columns=FEATURE_COLUMNS,
    )


def risk_label(probability: float) -> str:
    if probability >= 0.65:
        return "High delay risk"
    if probability >= 0.4:
        return "Medium delay risk"
    return "Low delay risk"


st.set_page_config(
    page_title="Flight Delay Predictor",
    page_icon="✈️",
    layout="wide",
)

st.title("Flight Delay Predictor")

model = load_model()

left, right = st.columns([1, 1])

with left:
    carrier = st.selectbox("Carrier", CARRIERS, index=CARRIERS.index("AA"))
    origin = st.selectbox("Origin airport", AIRPORTS, index=AIRPORTS.index("JFK"))
    dest = st.selectbox("Destination airport", AIRPORTS, index=AIRPORTS.index("LAX"))
    distance = st.number_input("Distance miles", min_value=50.0, max_value=6000.0, value=2475.0, step=25.0)

with right:
    month = st.slider("Month", min_value=1, max_value=12, value=7)
    day_name = st.selectbox("Day of week", list(DAYS.keys()), index=4)
    dep_hour = st.slider("Scheduled departure hour", min_value=0, max_value=23, value=18)
    arr_hour = st.slider("Scheduled arrival hour", min_value=0, max_value=23, value=21)

if origin == dest:
    st.warning("Origin and destination should be different airports.")

predict = st.button("Predict Delay Risk", type="primary", use_container_width=True)

if predict:
    row = build_prediction_row(
        carrier=carrier,
        origin=origin,
        dest=dest,
        month=month,
        day_of_week=DAYS[day_name],
        dep_hour=dep_hour,
        arr_hour=arr_hour,
        distance=distance,
    )

    probability = float(model.predict_proba(row)[0, 1])
    prediction = int(model.predict(row)[0])

    st.divider()
    metric_col, label_col = st.columns([1, 2])

    with metric_col:
        st.metric("Delay risk", f"{probability:.1%}")

    with label_col:
        st.subheader("Delayed" if prediction else "Not delayed")
        st.write(risk_label(probability))

    st.progress(min(max(probability, 0.0), 1.0))

    with st.expander("Prediction input"):
        st.dataframe(row, use_container_width=True, hide_index=True)
