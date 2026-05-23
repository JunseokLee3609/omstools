# OMS L1 Web Dashboard

Flask-based web dashboard for checking CMS OMS L1 rates, monitoring selected L1 seeds, comparing Heavy Ion reference runs, and exporting projection CSV files.

## 1. Clone

Clone the repository and move to the repository root:

```bash
git clone git@github.com:JunseokLee3609/omstools.git
cd omstools
```

If you use HTTPS instead of SSH:

```bash
git clone https://github.com/JunseokLee3609/omstools.git
cd omstools
```

## 2. Create Python Environment

Python 3.11 is recommended.

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-web.txt
```

On lxplus, if `python3.11` is not available, check available Python versions:

```bash
python3 --version
which python3
```

Then use the available Python 3 executable consistently for both the virtual environment and the app.

## 3. Configure OMS Credentials

Create a local `env.py` from the template:

```bash
cp env.example.py env.py
```

Edit `env.py` and fill in your own OMS API credentials:

```python
CLIENT_ID = "your_oms_client_id"
CLIENT_SECRET = "your_oms_client_secret"
```

Do not commit real credentials. `env.py` is ignored by git.

## 4. Run Locally

From the repository root:

```bash
. .venv/bin/activate
python3.11 web/flask_app.py
```

By default the app listens on localhost:

```text
http://127.0.0.1:8502
http://localhost:8502
```

This mode is for a browser running on the same machine as the Flask process.

## 5. Run Through Localhost With SSH Tunnel

Use this when the app runs on lxplus or another remote machine, but you want to open it in your local browser as `localhost`.

On the remote machine, start the dashboard. Binding to `127.0.0.1` is enough for an SSH tunnel:

```bash
. .venv/bin/activate
OMS_DASHBOARD_HOST=127.0.0.1 OMS_DASHBOARD_PORT=8502 python3.11 web/flask_app.py
```

From your local laptop or desktop, open a separate terminal and create the tunnel:

```bash
ssh -L 8502:127.0.0.1:8502 <username>@lxplus.cern.ch
```

Then open this in the local browser:

```text
http://localhost:8502
```

If local port `8502` is already in use, map a different local port:

```bash
ssh -L 8503:127.0.0.1:8502 <username>@lxplus.cern.ch
```

Then open:

```text
http://localhost:8503
```

The first port is the local browser port. The second port is the remote Flask server port.

## 6. Run on a Visible Host

For lxplus or another remote machine, bind the server to `0.0.0.0`:

```bash
. .venv/bin/activate
OMS_DASHBOARD_HOST=0.0.0.0 OMS_DASHBOARD_PORT=8502 python3.11 web/flask_app.py
```

Then open:

```text
http://<host-name-or-ip>:8502
```

Example:

```text
http://188.185.xx.xx:8502
```

If the port is already in use, either stop the old process or use another port:

```bash
OMS_DASHBOARD_HOST=0.0.0.0 OMS_DASHBOARD_PORT=8503 python3.11 web/flask_app.py
```

## 7. Monitoring Seed Lists

The default monitoring seed list is:

```text
examples/MuonTriggers.txt
```

Other example lists can be stored under:

```text
examples/*.txt
```

Each file should contain one L1 seed name per line:

```text
L1_ZeroBias
L1_SingleMuOpen_BptxAND
L1_MinimumBiasHF1_AND_BptxAND
```

The web UI also provides a Monitoring Seeds page where seeds can be moved between the available seed list and the monitoring seed list.

## 8. Projection Settings and Runtime Files

The Bunch Projection page stores the reference run, comparison builder entries, and related UI settings under:

```text
web/.state/
```

This directory is ignored by git.

## 9. CSV Export

Projection CSV files are not written continuously.

They are saved only when the web UI's export button is clicked. Exported files are written under:

```text
outcsv/web_exports/
```

This directory is ignored by git.

## 10. Main Pages

- `Dashboard`: current run summary, selected L1 seed rates, and current-run reference ratio plot.
- `Bunch Projection`: reference run setup, comparison run setup, projection table, suspicious LS report, and rate plots.
- `L1 Prescale Table`: prescale information for a run, with optional monitoring seed filtering.
- `Monitoring Seeds`: configure which L1 seeds are used by monitoring and projection views.
- `CSV Exports`: browse CSV files exported from the web UI.
- `Settings`: app-level settings such as refresh interval and rate field.

## 11. Troubleshooting

### Port Already in Use

Check which process is listening on the remote machine:

```bash
ss -ltnp | grep 8502
```

Check which process is listening on a local Linux or macOS machine:

```bash
lsof -iTCP:8502 -sTCP:LISTEN
```

Use a different port if needed:

```bash
OMS_DASHBOARD_PORT=8503 python3.11 web/flask_app.py
```

### Cannot Connect from Browser

For direct remote access, make sure the app was started with:

```bash
OMS_DASHBOARD_HOST=0.0.0.0
```

Also check that the browser URL uses the remote host/IP, not `127.0.0.1`.

For SSH tunnel access, keep the browser URL as:

```text
http://localhost:<local-port>
```

and make sure the tunnel command is still running.

### OMS Authentication Fails

Check that:

- `env.py` exists in the repository root.
- `CLIENT_ID` and `CLIENT_SECRET` are filled with valid OMS credentials.
- The Python environment installed `omsapi` and `tsgauth` from `requirements-web.txt`.

### JavaScript or Plot Problems After Updating

Hard-refresh the browser page, or open it in a new private window, so old cached JavaScript is not reused.

## 12. Developer Checks

Useful quick checks before pushing changes:

```bash
python3.11 -m py_compile web/flask_app.py web/services/oms_data.py web/services/projection.py
node --check web/static/app.js
python3.11 -m unittest tests.test_projection
```
