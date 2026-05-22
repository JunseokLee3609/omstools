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

By default the app uses:

```text
http://127.0.0.1:8502
```

## 5. Run on a Visible Host

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

## 6. Monitoring Seed Lists

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

## 7. CSV Export

Projection CSV files are not written continuously.

They are saved only when the web UI's export button is clicked. Exported files are written under:

```text
outcsv/web_exports/
```

This directory is ignored by git.

## 8. Main Pages

- `Dashboard`: current run summary and selected L1 seed rates.
- `Bunch Projection`: reference run setup, comparison run setup, projection table, and rate plots.
- `L1 Prescale Table`: prescale information for a run, with optional monitoring seed filtering.
- `Monitoring Seeds`: configure which L1 seeds are used by monitoring and projection views.
- `CSV Exports`: browse CSV files exported from the web UI.
- `Settings`: app-level settings such as refresh interval and rate field.

## 9. Troubleshooting

### Port Already in Use

Check which process is listening:

```bash
ss -ltnp | grep 8502
```

Use a different port if needed:

```bash
OMS_DASHBOARD_PORT=8503 python3.11 web/flask_app.py
```

### Cannot Connect from Browser

Make sure the app was started with:

```bash
OMS_DASHBOARD_HOST=0.0.0.0
```

Also check that the browser URL uses the remote host/IP, not `127.0.0.1`.

### OMS Authentication Fails

Check that:

- `env.py` exists in the repository root.
- `CLIENT_ID` and `CLIENT_SECRET` are filled with valid OMS credentials.
- The Python environment installed `omsapi` and `tsgauth` from `requirements-web.txt`.

### JavaScript or Plot Problems After Updating

Hard-refresh the browser page, or open it in a new private window, so old cached JavaScript is not reused.

## 10. Developer Checks

Useful quick checks before pushing changes:

```bash
python3.11 -m py_compile web/flask_app.py web/services/oms_data.py web/services/projection.py
node --check web/static/app.js
python3.11 -m unittest tests.test_projection
```
