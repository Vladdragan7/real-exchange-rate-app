Real Exchange Rate Explorer
This repository contains a Streamlit application that retrieves monthly CPI and exchange-rate data from the IMF and calculates bilateral nominal and real exchange rates.

Economic calculations
The nominal exchange rate is defined as:

S(t) = units of Country 2 currency per one unit of Country 1 currency
Because the IMF exchange rates are expressed as local-currency units per U.S. dollar, the application calculates:

S(t) = FX2(t) / FX1(t)
The real exchange rate is:

RER(t) = S(t) × P1(t) / P2(t)
For the selected period:

RER* = average of RER(t) over valid selected observations
The Real Index is:

Real Index(t) = 100 × RER(t) / RER*
The application recalculates RER* whenever the selected countries or dates change.

Application features
The application allows users to:

Select Country 1 and Country 2
Select the Euro area using IMF code G163
Select a start and end month
Display a Real, Nominal, or Both chart
View separate chart axes when Both is selected
Download the selected data and calculations as a CSV
Preview the selected data
Perform a manual RER verification
Confirm that the selected-period Real Index averages 100
IMF data
The application uses the IMF SDMX 3.0 API.

The CPI series follows this structure:

{ISO3}.CPI._T.IX.M
The exchange-rate series follows this structure:

{ISO3}.XDC_USD.PA_RT.M
The application requests observations beginning in January 1976 when available.

IMF exchange rates represent local-currency units per U.S. dollar. The application uses 1.0 as the U.S. exchange rate in USD per USD.

UK and U.S. test
When the United Kingdom is Country 1 and the United States is Country 2:

FX1 = GBP per USD
FX2 = USD per USD = 1
S = FX2 / FX1
The resulting nominal exchange-rate direction is:

USD per GBP
Repository files
The repository contains:

app.py
requirements.txt
README.md
All three files must remain at the top level of the repository.

Python version
The application is designed for Python 3.12.

Run the application locally
Install the required packages:

pip install -r requirements.txt
Start the application:

streamlit run app.py
Streamlit deployment
To deploy the application through Streamlit Community Cloud:

Sign in using the GitHub account that owns this repository.
Choose Create app.
Select this repository.
Select the main branch.
Enter app.py as the main file path.
Select Python 3.12 in the advanced settings.
Leave Secrets empty.
Deploy the application.
CSV export
The downloadable CSV includes:

Date
Country 1 and Country 2
IMF country codes
Country 1 CPI, P1
Country 2 CPI, P2
Country 1 currency per USD, FX1
Country 2 currency per USD, FX2
Nominal bilateral exchange rate, S
Real exchange rate, RER
Selected-period average real exchange rate, RER_star
Real Index
Data limitations
IMF data coverage varies by economy and series. Certain series may begin after January 1976, end before the present, or contain missing monthly observations.

The application calculates results only for months containing all required CPI and exchange-rate values. Live downloads may also be affected by temporary IMF service or network issues.
