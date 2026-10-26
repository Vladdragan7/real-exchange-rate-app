import io
import re
import pandas as pd
import plotly.graph_objects as go
import pycountry
import requests
import streamlit as st
from plotly.subplots import make_subplots

st.set_page_config(page_title="Real Exchange Rate Explorer", page_icon="🌍", layout="wide")
BASE = "https://api.imf.org/external/sdmx/3.0"
HEADERS = {"Accept": "text/csv", "User-Agent": "real-exchange-rate-app/1.1"}

CURRENCIES = {
    "USA":"USD","GBR":"GBP","G163":"EUR","AUS":"AUD","AUT":"EUR","BEL":"EUR","BGR":"BGN",
    "BRA":"BRL","CAN":"CAD","CHE":"CHF","CHL":"CLP","CHN":"CNY","COL":"COP","CZE":"CZK",
    "DEU":"EUR","DNK":"DKK","EGY":"EGP","ESP":"EUR","EST":"EUR","FIN":"EUR","FRA":"EUR",
    "GRC":"EUR","HKG":"HKD","HRV":"EUR","HUN":"HUF","IDN":"IDR","IND":"INR","IRL":"EUR",
    "ISL":"ISK","ISR":"ILS","ITA":"EUR","JPN":"JPY","KOR":"KRW","LTU":"EUR","LUX":"EUR",
    "LVA":"EUR","MEX":"MXN","MLT":"EUR","MYS":"MYR","NLD":"EUR","NOR":"NOK","NZL":"NZD",
    "PAK":"PKR","PER":"PEN","PHL":"PHP","POL":"PLN","PRT":"EUR","ROU":"RON","RUS":"RUB",
    "SAU":"SAR","SGP":"SGD","SVK":"EUR","SVN":"EUR","SWE":"SEK","THA":"THB","TUR":"TRY",
    "UKR":"UAH","VNM":"VND","ZAF":"ZAR"
}

class IMFError(Exception):
    pass

def economies():
    result = {c.name: c.alpha_3 for c in pycountry.countries if hasattr(c, "alpha_3")}
    result.update({"United Kingdom":"GBR", "United States":"USA", "Euro area":"G163"})
    return dict(sorted(result.items()))

ECONOMIES = economies()
NAMES = list(ECONOMIES)

def parse_month(value):
    """Accept IMF monthly labels such as 2024-01 and 2024-M01."""
    text = str(value).strip()
    match = re.search(r"(\d{4})-M?(\d{1,2})", text)
    if not match:
        return pd.NaT
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return pd.NaT
    return pd.Timestamp(year=year, month=month, day=1)

def find_col(columns, choices):
    lookup = {str(c).strip().upper(): c for c in columns}
    for choice in choices:
        if choice in lookup:
            return lookup[choice]
    return None

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_series(flow, key, label):
    url = f"{BASE}/data/dataflow/IMF.STA/{flow}/+/{key}"
    try:
        response = requests.get(
            url,
            params={"c[TIME_PERIOD]": "ge:1976-01"},
            headers=HEADERS,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise IMFError(f"IMF request failed for {label}: {exc}") from exc

    if response.status_code != 200:
        raise IMFError(f"IMF returned HTTP {response.status_code} for {label}: {response.text[:250]}")

    try:
        frame = pd.read_csv(io.StringIO(response.text))
    except Exception as exc:
        raise IMFError(f"IMF response for {label} was not readable CSV: {exc}") from exc

    if frame.empty:
        raise IMFError(f"The IMF returned no observations for {label}.")

    time_col = find_col(frame.columns, ["TIME_PERIOD", "TIME", "PERIOD"])
    value_col = find_col(frame.columns, ["OBS_VALUE", "VALUE", "OBSERVATION_VALUE"])
    if time_col is None or value_col is None:
        raise IMFError(f"Unexpected IMF columns for {label}: {', '.join(map(str, frame.columns))}")

    output = frame[[time_col, value_col]].copy()
    output.columns = ["Date", "Value"]
    output["Date"] = output["Date"].map(parse_month)
    output["Value"] = pd.to_numeric(output["Value"], errors="coerce")
    output = output.dropna().query("Value > 0").drop_duplicates("Date", keep="last").sort_values("Date")
    if output.empty:
        sample_periods = frame[time_col].dropna().astype(str).head(5).tolist()
        raise IMFError(f"No valid monthly observations were found for {label}. Sample IMF periods: {sample_periods}")
    return output.set_index("Date")["Value"].astype(float)

def cpi(code, name):
    return fetch_series("CPI", f"{code}.CPI._T.IX.M", f"{name} monthly CPI")

def fx(code, name):
    if code == "USA":
        return None
    return fetch_series("ER", f"{code}.XDC_USD.PA_RT.M", f"{name} exchange rate")

def prepare(name1, code1, name2, code2):
    series = [cpi(code1, name1).rename("P1"), cpi(code2, name2).rename("P2")]
    fx1, fx2 = fx(code1, name1), fx(code2, name2)
    if fx1 is not None: series.append(fx1.rename("FX1"))
    if fx2 is not None: series.append(fx2.rename("FX2"))
    data = pd.concat(series, axis=1).sort_index()
    if code1 == "USA": data["FX1"] = 1.0
    if code2 == "USA": data["FX2"] = 1.0
    data = data.dropna(subset=["P1","P2","FX1","FX2"])
    data = data[(data[["P1","P2","FX1","FX2"]] > 0).all(axis=1)].copy()
    if data.empty:
        raise IMFError("No overlapping valid CPI and exchange-rate observations were found.")
    data["S"] = data["FX2"] / data["FX1"]
    data["RER"] = data["S"] * data["P1"] / data["P2"]
    return data

st.title("🌍 Real Exchange Rate Explorer")
st.write("Compare nominal and CPI-adjusted real exchange rates using monthly IMF data.")
with st.expander("Formulas and exchange-rate direction"):
    st.markdown("**S(t) = FX2(t) / FX1(t)**  \n**RER(t) = S(t) × P1(t) / P2(t)**  \n**Real Index(t) = 100 × RER(t) / RER\***")

c1, c2 = st.columns(2)
name1 = c1.selectbox("Country 1", NAMES, index=NAMES.index("United Kingdom"))
name2 = c2.selectbox("Country 2", NAMES, index=NAMES.index("United States"))
code1, code2 = ECONOMIES[name1], ECONOMIES[name2]
cur1, cur2 = CURRENCIES.get(code1, f"{name1} currency"), CURRENCIES.get(code2, f"{name2} currency")
direction = f"{cur2} per {cur1}"
st.info(f"Selected direction: **{direction}**. This means units of {name2} currency per one unit of {name1} currency.")

try:
    with st.spinner("Downloading IMF data..."):
        full = prepare(name1, code1, name2, code2)
except IMFError as exc:
    st.error(str(exc))
    st.stop()

minimum, maximum = full.index.min(), full.index.max()
default_start = max(minimum, pd.Timestamp("2000-01-01"))
a, b, c = st.columns(3)
start = pd.Timestamp(a.date_input("Start month", default_start.date(), min_value=minimum.date(), max_value=maximum.date())).to_period("M").to_timestamp()
end = pd.Timestamp(b.date_input("End month", maximum.date(), min_value=minimum.date(), max_value=maximum.date())).to_period("M").to_timestamp()
view = c.radio("Chart", ["Real", "Nominal", "Both"])
if start > end:
    st.error("Start month must not be after end month.")
    st.stop()

sample = full.loc[start:end].copy()
if sample.empty:
    st.error("No valid observations exist in the selected period.")
    st.stop()
sample["RER_star"] = sample["RER"].mean()
sample["Real_Index"] = 100 * sample["RER"] / sample["RER_star"]

m1, m2, m3 = st.columns(3)
m1.metric("Valid months", len(sample))
m2.metric("RER*", f"{sample['RER_star'].iloc[0]:.6f}")
m3.metric("Average Real Index", f"{sample['Real_Index'].mean():.6f}")

if view == "Both":
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=sample.index, y=sample["Real_Index"], name="Real Index"), secondary_y=False)
    fig.add_trace(go.Scatter(x=sample.index, y=sample["S"], name=f"Nominal S(t): {direction}"), secondary_y=True)
    fig.update_yaxes(title_text="Real Index", secondary_y=False)
    fig.update_yaxes(title_text=direction, secondary_y=True)
elif view == "Real":
    fig = go.Figure(go.Scatter(x=sample.index, y=sample["Real_Index"], name="Real Index"))
    fig.update_yaxes(title_text="Real Index, average = 100")
else:
    fig = go.Figure(go.Scatter(x=sample.index, y=sample["S"], name=f"Nominal S(t): {direction}"))
    fig.update_yaxes(title_text=direction)
fig.update_layout(template="plotly_white", height=560, xaxis_title="Month", hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)

export = sample.reset_index().rename(columns={"index":"Date"})
export.insert(1, "Country_1", name1)
export.insert(2, "Country_2", name2)
export.insert(3, "Country_1_IMF_Code", code1)
export.insert(4, "Country_2_IMF_Code", code2)
export["Date"] = export["Date"].dt.strftime("%Y-%m")
columns = ["Date","Country_1","Country_2","Country_1_IMF_Code","Country_2_IMF_Code","P1","P2","FX1","FX2","S","RER","RER_star","Real_Index"]
export = export[columns]
st.download_button("Download selected sample as CSV", export.to_csv(index=False, float_format="%.12f"), "real_exchange_rate.csv", "text/csv")
st.subheader("Selected-sample data preview")
st.dataframe(export, use_container_width=True, hide_index=True)

st.subheader("Manual RER verification")
row = sample.iloc[0]
manual_s = row["FX2"] / row["FX1"]
manual_rer = manual_s * row["P1"] / row["P2"]
st.code(f"""Date: {sample.index[0]:%Y-%m}
S = FX2 / FX1 = {row['FX2']:.12f} / {row['FX1']:.12f} = {manual_s:.12f} {direction}
RER = S × P1 / P2 = {manual_s:.12f} × {row['P1']:.12f} / {row['P2']:.12f} = {manual_rer:.12f}
Application RER = {row['RER']:.12f}
Difference = {manual_rer - row['RER']:.12f}""")
