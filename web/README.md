# OMS L1 Web Dashboard

## Requirements

Install the Flask dashboard dependencies from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-web.txt
```

The dashboard also uses browser-side CDN assets:

- Plotly.js
- Font Awesome
- Google Fonts

## OMS Credentials

Create `env.py` in the repository root:

```bash
cp env.example.py env.py
```

Then fill in your own OMS client credentials:

```python
CLIENT_ID = "your_oms_client_id"
CLIENT_SECRET = "your_oms_client_secret"
```

Do not commit real credentials.

## Run

From the repository root:

```bash
python3.11 web/flask_app.py
```

Optional host and port:

```bash
OMS_DASHBOARD_HOST=0.0.0.0 OMS_DASHBOARD_PORT=8502 python3.11 web/flask_app.py
```

## Runtime Files

- Monitoring seed list defaults to `examples/MuonTriggers.txt`.
- CSV exports are written only when requested to `outcsv/web_exports/`.
