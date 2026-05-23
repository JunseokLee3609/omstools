from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"
EXPORT_DIR = REPO_ROOT / "outcsv" / "web_exports"
STATE_DIR = REPO_ROOT / "web" / ".state"
PROJECTION_SETTINGS_FILE = STATE_DIR / "projection_settings.json"
DASHBOARD_REFERENCE_SETTINGS_FILE = STATE_DIR / "dashboard_reference_settings.json"

DEFAULT_TRIGGER_FILE = EXAMPLES_DIR / "MuonTriggers.txt"
if not DEFAULT_TRIGGER_FILE.exists():
    DEFAULT_TRIGGER_FILE = EXAMPLES_DIR / "l1hlt.txt"

DEFAULT_RATE_FIELD = "pre_dt_before_prescale_rate"
RATE_FIELD_OPTIONS = {
    "Pre-DT before PS": "pre_dt_before_prescale_rate",
    "Pre-DT after PS": "pre_dt_rate",
    "Post-DT": "post_dt_rate",
    "Post-DT from HLT": "post_dt_hlt_rate",
}

DEFAULT_REFRESH_SECONDS = 30
DEFAULT_CURRENT_LS_WINDOW = 20
DEFAULT_PROJECTION_PLOT_LS_LIMIT = 120
DEFAULT_TARGET_MB_RATE = 52000.0
DEFAULT_REFERENCE_MB_RATE = 32000.0
