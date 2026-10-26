from io import StringIO

import pandas as pd
import plotly.graph_objects as go
import pycountry
import requests
import streamlit as st
from plotly.subplots import make_subplots


# ---------------------------------------------------------
# PAGE CONFIGURATION
# ---------------------------------------------------------

st.set_page_config(
    page_title="Real Exchange Rate Explorer",
    page_icon="🌍",
    layout="wide",
)

IMF_API_BASE = "https://api.imf.org/external/sdmx/3.0"
EARLIEST_MONTH = "1976-01"
REQUEST_TIMEOUT = 60

HEADERS = {
    "Accept": "text/csv",
    "User-Agent": "real-exchange-rate-app/1.0",
}


class IMFDataError(Exception):
    """Custom error for IMF download and parsing problems."""


# ---------------------------------------------------------
# COUNTRY AND CURRENCY LISTS
# ---------------------------------------------------------

CURRENCY_CODES = {
    "ARG": "ARS",
    "AUS": "AUD",
    "AUT": "EUR",
    "BEL": "EUR",
    "BGR": "BGN",
    "BRA": "BRL",
    "CAN": "CAD",
    "CHE": "CHF",
    "CHL": "CLP",
    "CHN": "CNY",
    "COL": "COP",
    "CZE": "CZK",
    "DEU": "EUR",
    "DNK": "DKK",
    "EGY": "EGP",
    "ESP": "EUR",
    "EST": "EUR",
    "FIN": "EUR",
    "FRA": "EUR",
    "GBR": "GBP",
    "GRC": "EUR",
    "HKG": "HKD",
    "HRV": "EUR",
    "HUN": "HUF",
    "IDN": "IDR",
    "IND": "INR",
    "IRL": "EUR",
    "ISL": "ISK",
    "ISR": "ILS",
    "ITA": "EUR",
    "JPN": "JPY",
    "KOR": "KRW",
    "LTU": "EUR",
    "LUX": "EUR",
    "LVA": "EUR",
    "MEX": "MXN",
    "MLT": "EUR",
    "MYS": "MYR",
    "NLD": "EUR",
    "NOR": "NOK",
    "NZL": "NZD",
    "PAK": "PKR",
    "PER": "PEN",
    "PHL": "PHP",
    "POL": "PLN",
    "PRT": "EUR",
    "ROU": "RON",
    "RUS": "RUB",
    "SAU": "SAR",
    "SGP": "SGD",
    "SVK": "EUR",
    "SVN": "EUR",
    "SWE": "SEK",
    "THA": "THB",
    "TUR": "TRY",
    "UKR": "UAH",
    "USA": "USD",
    "VNM": "VND",
    "ZAF": "ZAR",
    "G163": "EUR",
}


def build_economy_list():
    economies = {}

    for country in pycountry.countries:
        if hasattr(country, "alpha_3"):
            economies[country.name] = country.alpha_3

    economies["United Kingdom"] = "GBR"
    economies["United States"] = "USA"
    economies["Euro area"] = "G163"

    return dict(sorted(economies.items(), key=lambda item: item[0]))


ECONOMIES = build_economy_list()
ECONOMY_NAMES = list(ECONOMIES.keys())


# ---------------------------------------------------------
# IMF DATA FUNCTIONS
# ---------------------------------------------------------

def find_column(columns, possible_names):
    normalized_columns = {
        str(column).strip().upper(): column
        for column in columns
    }

    for possible_name in possible_names:
        if possible_name.upper() in normalized_columns:
            return normalized_columns[possible_name.upper()]

    return None


def build_imf_url(dataflow, key):
    return (
        f"{IMF_API_BASE}/data/dataflow/"
        f"IMF.STA/{dataflow}/+/{key}"
    )


def parse_imf_csv(response_text, description):
    try:
        data = pd.read_csv(StringIO(response_text))
    except Exception as exc:
        raise IMFDataError(
            f"The IMF response for {description} could not be read as CSV. "
            f"Technical detail: {exc}"
        ) from exc

    if data.empty:
        raise IMFDataError(
            f"The IMF returned no observations for {description}."
        )

    time_column = find_column(
        data.columns,
        ["TIME_PERIOD", "TIME", "PERIOD"],
    )

    value_column = find_column(
        data.columns,
        ["OBS_VALUE", "VALUE", "OBSERVATION_VALUE"],
    )

    if time_column is None or value_column is None:
        received_columns = ", ".join(str(column) for column in data.columns)

        raise IMFDataError(
            f"The IMF response for {description} did not contain the "
            f"expected time and value columns. Received columns: "
            f"{received_columns}"
        )

    parsed = data[[time_column, value_column]].copy()
    parsed.columns = ["Date", "Value"]

    parsed["Date"] = pd.to_datetime(
        parsed["Date"].astype(str).str.slice(0, 7),
        format="%Y-%m",
        errors="coerce",
    )

    parsed["Value"] = pd.to_numeric(
        parsed["Value"],
        errors="coerce",
    )

    parsed = parsed.dropna(subset=["Date", "Value"])
    parsed = parsed[parsed["Value"] > 0]
    parsed = parsed.drop_duplicates(subset=["Date"], keep="last")
    parsed = parsed.sort_values("Date")

    if parsed.empty:
        raise IMFDataError(
            f"No valid monthly observations were found for {description}."
        )

    return parsed.set_index("Date")["Value"].astype(float)


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_imf_series(dataflow, key, description):
    url = build_imf_url(dataflow, key)

    params = {
        "c[TIME_PERIOD]": f"ge:{EARLIEST_MONTH}",
    }

    try:
        response = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise IMFDataError(
            f"The IMF request timed out for {description}. Please try again."
        ) from exc
    except requests.RequestException as exc:
        raise IMFDataError(
            f"The IMF request failed for {description}. "
            f"Technical detail: {exc}"
        ) from exc

    if response.status_code != 200:
        response_preview = response.text[:300].replace("\n", " ")

        raise IMFDataError(
            f"The IMF returned HTTP {response.status_code} for "
            f"{description}. IMF response: {response_preview}"
        )

    content_type = response.headers.get("Content-Type", "").lower()

    if "html" in content_type:
        raise IMFDataError(
            f"The IMF returned a web page instead of data for "
            f"{description}. The IMF service may be temporarily unavailable."
        )

    return parse_imf_csv(response.text, description)


def get_cpi(country_code, country_name):
    key = f"{country_code}.CPI._T.IX.M"

    return fetch_imf_series(
        dataflow="CPI",
        key=key,
        description=f"{country_name} monthly CPI",
    )


def get_fx(country_code, country_name):
    if country_code == "USA":
        return None

    key = f"{country_code}.XDC_USD.PA_RT.M"

    return fetch_imf_series(
        dataflow="ER",
        key=key,
        description=(
            f"{country_name} exchange rate in local currency per USD"
        ),
    )


# ---------------------------------------------------------
# CALCULATION FUNCTIONS
# ---------------------------------------------------------

def combine_input_series(
    country1_name,
    country1_code,
    country2_name,
    country2_code,
):
    p1 = get_cpi(country1_code, country1_name).rename("P1")
    p2 = get_cpi(country2_code, country2_name).rename("P2")

    fx1 = get_fx(country1_code, country1_name)
    fx2 = get_fx(country2_code, country2_name)

    series_to_join = [p1, p2]

    if fx1 is not None:
        series_to_join.append(fx1.rename("FX1"))

    if fx2 is not None:
        series_to_join.append(fx2.rename("FX2"))

    combined = pd.concat(
        series_to_join,
        axis=1,
        join="outer",
    ).sort_index()

    if country1_code == "USA":
        combined["FX1"] = 1.0

    if country2_code == "USA":
        combined["FX2"] = 1.0

    required_columns = ["P1", "P2", "FX1", "FX2"]

    for column in required_columns:
        if column not in combined.columns:
            combined[column] = pd.NA

    combined = combined[required_columns]
    combined = combined.apply(pd.to_numeric, errors="coerce")

    valid_rows = (
        combined["P1"].gt(0)
        & combined["P2"].gt(0)
        & combined["FX1"].gt(0)
        & combined["FX2"].gt(0)
    )

    combined = combined.loc[valid_rows].copy()

    if combined.empty:
        raise IMFDataError(
            "The selected economies do not have overlapping valid monthly "
            "CPI and exchange-rate observations."
        )

    # Country 2 currency per one unit of Country 1 currency.
    combined["S"] = combined["FX2"] / combined["FX1"]

    # Real exchange rate.
    combined["RER"] = (
        combined["S"]
        * combined["P1"]
        / combined["P2"]
    )

    return combined


def calculate_selected_sample(
    full_data,
    start_month,
    end_month,
    country1_name,
    country1_code,
    country2_name,
    country2_code,
):
    sample = full_data.loc[
        (full_data.index >= start_month)
        & (full_data.index <= end_month)
    ].copy()

    sample = sample.dropna(
        subset=["P1", "P2", "FX1", "FX2", "S", "RER"]
    )

    if sample.empty:
        raise IMFDataError(
            "No complete observations are available inside the selected "
            "sample period."
        )

    rer_star = sample["RER"].mean()

    if pd.isna(rer_star) or rer_star == 0:
        raise IMFDataError(
            "The selected period did not produce a valid average RER."
        )

    sample["RER_star"] = rer_star
    sample["Real_Index"] = (
        100.0 * sample["RER"] / sample["RER_star"]
    )

    sample.insert(0, "Country_2_IMF_Code", country2_code)
    sample.insert(0, "Country_1_IMF_Code", country1_code)
    sample.insert(0, "Country_2", country2_name)
    sample.insert(0, "Country_1", country1_name)

    sample.index.name = "Date"

    return sample


def month_label(timestamp):
    return timestamp.strftime("%B %Y")


# ---------------------------------------------------------
# CHART FUNCTION
# ---------------------------------------------------------

def make_chart(sample, chart_choice, nominal_axis_label):
    if chart_choice == "Both":
        figure = make_subplots(
            specs=[[{"secondary_y": True}]]
        )

        figure.add_trace(
            go.Scatter(
                x=sample.index,
                y=sample["Real_Index"],
                name="Real Index",
                mode="lines",
                line={
                    "color": "#1565C0",
                    "width": 2.5,
                },
                hovertemplate=(
                    "%{x|%b %Y}<br>"
                    "Real Index: %{y:.4f}"
                    "<extra></extra>"
                ),
            ),
            secondary_y=False,
        )

        figure.add_trace(
            go.Scatter(
                x=sample.index,
                y=sample["S"],
                name=f"Nominal S(t): {nominal_axis_label}",
                mode="lines",
                line={
                    "color": "#E67E22",
                    "width": 2.5,
                },
                hovertemplate=(
                    "%{x|%b %Y}<br>"
                    + nominal_axis_label
                    + ": %{y:.6f}"
                    + "<extra></extra>"
                ),
            ),
            secondary_y=True,
        )

        figure.add_hline(
            y=100,
            line_dash="dash",
            line_color="gray",
            opacity=0.7,
            secondary_y=False,
        )

        figure.update_yaxes(
            title_text="Real Index, average = 100",
            secondary_y=False,
        )

        figure.update_yaxes(
            title_text=f"Nominal S(t), {nominal_axis_label}",
            secondary_y=True,
        )

    elif chart_choice == "Real":
        figure = go.Figure()

        figure.add_trace(
            go.Scatter(
                x=sample.index,
                y=sample["Real_Index"],
                name="Real Index",
                mode="lines",
                line={
                    "color": "#1565C0",
                    "width": 2.5,
                },
                hovertemplate=(
                    "%{x|%b %Y}<br>"
                    "Real Index: %{y:.4f}"
                    "<extra></extra>"
                ),
            )
        )

        figure.add_hline(
            y=100,
            line_dash="dash",
            line_color="gray",
            opacity=0.7,
        )

        figure.update_yaxes(
            title_text="Real Index, average = 100"
        )

    else:
        figure = go.Figure()

        figure.add_trace(
            go.Scatter(
                x=sample.index,
                y=sample["S"],
                name=f"Nominal S(t): {nominal_axis_label}",
                mode="lines",
                line={
                    "color": "#E67E22",
                    "width": 2.5,
                },
                hovertemplate=(
                    "%{x|%b %Y}<br>"
                    + nominal_axis_label
                    + ": %{y:.6f}"
                    + "<extra></extra>"
                ),
            )
        )

        figure.update_yaxes(
            title_text=f"Nominal S(t), {nominal_axis_label}"
        )

    figure.update_layout(
        title=f"{chart_choice} Exchange Rate View",
        xaxis_title="Month",
        hovermode="x unified",
        template="plotly_white",
        height=600,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
        margin={
            "l": 60,
            "r": 60,
            "t": 90,
            "b": 60,
        },
    )

    return figure


# ---------------------------------------------------------
# APPLICATION
# ---------------------------------------------------------

st.title("🌍 Real Exchange Rate Explorer")

st.write(
    "Compare the nominal and CPI-adjusted real exchange rate between "
    "two economies using monthly IMF data."
)

with st.expander(
    "Formulas and exchange-rate direction",
    expanded=False,
):
    st.markdown(
        """
### Nominal exchange rate

**S(t) = FX2(t) / FX1(t)**

FX1 is Country 1 currency units per U.S. dollar.

FX2 is Country 2 currency units per U.S. dollar.

Therefore, S(t) is units of Country 2 currency per one unit of
Country 1 currency.

### Real exchange rate

**RER(t) = S(t) × P1(t) / P2(t)**

### Selected-period benchmark

**RER* = average RER(t) over valid months in the selected period**

### Real Index

**Real Index(t) = 100 × RER(t) / RER***

The application recalculates RER* every time the selected countries
or dates change. The nominal exchange rate is not normalized.
"""
    )


# ---------------------------------------------------------
# COUNTRY SELECTION
# ---------------------------------------------------------

country_columns = st.columns(2)

default_country1_index = ECONOMY_NAMES.index("United Kingdom")
default_country2_index = ECONOMY_NAMES.index("United States")

with country_columnscountry1_name = st.selectbox(
        "Country 1",
        options=ECONOMY_NAMES,
        index=default_country1_index,
    )

with country_columnscountry2_name = st.selectbox(
        "Country 2",
        options=ECONOMY_NAMES,
        index=default_country2_index,
    )

country1_code = ECONOMIES[country1_name]
country2_code = ECONOMIES[country2_name]

currency1 = CURRENCY_CODES.get(
    country1_code,
    f"{country1_name} currency",
)

currency2 = CURRENCY_CODES.get(
    country2_code,
    f"{country2_name} currency",
)

nominal_axis_label = f"{currency2} per {currency1}"

st.info(
    f"Selected direction: **{nominal_axis_label}**. "
    f"This means units of {country2_name} currency per one unit of "
    f"{country1_name} currency."
)

if country1_code == country2_code:
    st.warning(
        "You selected the same economy twice. The nominal exchange rate "
        "will equal 1 where the underlying data are valid."
    )


# ---------------------------------------------------------
# DOWNLOAD AND ALIGN IMF DATA
# ---------------------------------------------------------

with st.spinner("Downloading and aligning IMF data..."):
    try:
        full_data = combine_input_series(
            country1_name=country1_name,
            country1_code=country1_code,
            country2_name=country2_name,
            country2_code=country2_code,
        )
    except IMFDataError as exc:
        st.error(str(exc))
        st.info(
            "IMF coverage varies by country. Try another country pair or "
            "try again if the IMF service is temporarily unavailable."
        )
        st.stop()
    except Exception as exc:
        st.error(
            "An unexpected error occurred while preparing the IMF data. "
            f"Technical detail: {exc}"
        )
        st.stop()


minimum_month = (
    full_data.index.min()
    .to_period("M")
    .to_timestamp()
)

maximum_month = (
    full_data.index.max()
    .to_period("M")
    .to_timestamp()
)

st.caption(
    f"Complete overlapping observations are available from "
    f"**{month_label(minimum_month)}** through "
    f"**{month_label(maximum_month)}**."
)

default_start = max(
    minimum_month,
    pd.Timestamp("2000-01-01"),
)

if default_start > maximum_month:
    default_start = minimum_month


# ---------------------------------------------------------
# DATE AND CHART SELECTION
# ---------------------------------------------------------

date_columns = st.columns(3)

with date_columnsstart_date = st.date_input(
        "Start month",
        value=default_start.date(),
        min_value=minimum_month.date(),
        max_value=maximum_month.date(),
    )

with date_columnsend_date = st.date_input(
        "End month",
        value=maximum_month.date(),
        min_value=minimum_month.date(),
        max_value=maximum_month.date(),
    )

with date_columnschart_choice = st.radio(
        "Chart",
        options=["Real", "Nominal", "Both"],
        horizontal=True,
    )

start_month = (
    pd.Timestamp(start_date)
    .to_period("M")
    .to_timestamp()
)

end_month = (
    pd.Timestamp(end_date)
    .to_period("M")
    .to_timestamp()
)

if start_month > end_month:
    st.error(
        "The start month must be earlier than or equal to the end month."
    )
    st.stop()


# ---------------------------------------------------------
# SELECTED-SAMPLE CALCULATIONS
# ---------------------------------------------------------

try:
    sample = calculate_selected_sample(
        full_data=full_data,
        start_month=start_month,
        end_month=end_month,
        country1_name=country1_name,
        country1_code=country1_code,
        country2_name=country2_name,
        country2_code=country2_code,
    )
except IMFDataError as exc:
    st.error(str(exc))
    st.stop()

rer_star = sample["RER_star"].iloc[0]
real_index_average = sample["Real_Index"].mean()

metric_columns = st.columns(4)

with metric_columnsst.metric(
        "Valid months",
        f"{len(sample):,}",
    )

with metric_columnsst.metric(
        "RER*",
        f"{rer_star:.6f}",
    )

with metric_columnsst.metric(
        "Average Real Index",
        f"{real_index_average:.6f}",
    )

with metric_columnsst.metric(
        "Latest nominal S(t)",
        f"{sample['S'].iloc[-1]:.6f}",
    )


# ---------------------------------------------------------
# CHART
# ---------------------------------------------------------

figure = make_chart(
    sample=sample,
    chart_choice=chart_choice,
    nominal_axis_label=nominal_axis_label,
)

st.plotly_chart(
    figure,
    use_container_width=True,
)

if abs(real_index_average - 100.0) < 0.000001:
    st.success(
        "Check passed: the Real Index averages 100 over the valid "
        "selected observations."
    )
else:
    st.warning(
        "The Real Index differs slightly from 100 because of numerical "
        "rounding."
    )


# ---------------------------------------------------------
# CSV EXPORT
# ---------------------------------------------------------

export_data = sample.reset_index().copy()

export_data["Date"] = export_data["Date"].dt.strftime("%Y-%m")

export_columns = [
    "Date",
    "Country_1",
    "Country_2",
    "Country_1_IMF_Code",
    "Country_2_IMF_Code",
    "P1",
    "P2",
    "FX1",
    "FX2",
    "S",
    "RER",
    "RER_star",
    "Real_Index",
]

export_data = export_data[export_columns]

csv_data = export_data.to_csv(
    index=False,
    float_format="%.12f",
).encode("utf-8")

st.download_button(
    label="Download selected sample as CSV",
    data=csv_data,
    file_name=(
        f"real_exchange_rate_"
        f"{country1_code.lower()}_"
        f"{country2_code.lower()}_"
        f"{start_month:%Y-%m}_"
        f"{end_month:%Y-%m}.csv"
    ),
    mime="text/csv",
)


# ---------------------------------------------------------
# DATA PREVIEW
# ---------------------------------------------------------

st.subheader("Selected-sample data preview")

display_data = export_data.copy()

numeric_columns = [
    "P1",
    "P2",
    "FX1",
    "FX2",
    "S",
    "RER",
    "RER_star",
    "Real_Index",
]

display_data[numeric_columns] = (
    display_data[numeric_columns].round(6)
)

st.dataframe(
    display_data,
    use_container_width=True,
    hide_index=True,
)


# ---------------------------------------------------------
# MANUAL VERIFICATION
# ---------------------------------------------------------

st.subheader("Manual RER verification")

row_number = st.number_input(
    "Choose an observation number",
    min_value=1,
    max_value=len(sample),
    value=1,
    step=1,
)

verification_position = int(row_number) - 1
verification_row = sample.iloc[verification_position]
verification_date = sample.index[verification_position]

manual_s = (
    verification_row["FX2"]
    / verification_row["FX1"]
)

manual_rer = (
    manual_s
    * verification_row["P1"]
    / verification_row["P2"]
)

verification_text = f"""
Date: {verification_date:%Y-%m}

FX1 = {verification_row['FX1']:.12f} {currency1} per USD
FX2 = {verification_row['FX2']:.12f} {currency2} per USD

S = FX2 / FX1
S = {verification_row['FX2']:.12f} / {verification_row['FX1']:.12f}
S = {manual_s:.12f} {nominal_axis_label}

P1 = {verification_row['P1']:.12f}
P2 = {verification_row['P2']:.12f}

RER = S × P1 / P2
RER = {manual_s:.12f} × {verification_row['P1']:.12f} / {verification_row['P2']:.12f}
RER = {manual_rer:.12f}

Application RER = {verification_row['RER']:.12f}
Difference = {manual_rer - verification_row['RER']:.12f}
"""

st.code(verification_text)

st.caption(
    "Source: IMF SDMX 3.0 API. Data coverage varies by country and "
    "series. Months missing any required CPI or exchange-rate input are "
    "excluded from the calculations."
)
