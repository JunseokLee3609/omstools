import sys
import time
from html import escape
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web import config
from web.services import oms_data, projection


st.set_page_config(page_title="OMS L1 Rate Dashboard", layout="wide")

PLOT_COLORS = [
    "#2563eb",
    "#d97706",
    "#059669",
    "#dc2626",
    "#0891b2",
    "#be185d",
    "#4d7c0f",
    "#7c3aed",
    "#475569",
    "#ea580c",
]


def _init_state() -> None:
    st.session_state.setdefault("refresh_seconds", config.DEFAULT_REFRESH_SECONDS)
    st.session_state.setdefault("rate_field", config.DEFAULT_RATE_FIELD)
    st.session_state.setdefault("trigger_file", str(config.DEFAULT_TRIGGER_FILE))
    st.session_state.setdefault("projection_result", pd.DataFrame())
    st.session_state.setdefault("projection_models", pd.DataFrame())
    st.session_state.setdefault("reference_inputs", {})


def cache_bucket() -> int:
    refresh = max(5, int(st.session_state.get("refresh_seconds", config.DEFAULT_REFRESH_SECONDS)))
    return int(time.time() // refresh)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_current_run(_bucket: int) -> dict:
    return oms_data.get_current_global_run()


@st.cache_data(ttl=3600, show_spinner=False)
def cached_run_summary(run: int, _bucket: int) -> dict:
    return oms_data.get_run_summary(run)


@st.cache_data(ttl=120, show_spinner=False)
def cached_triggers(path: str) -> List[str]:
    return oms_data.load_trigger_list(path)


@st.cache_data(ttl=60, show_spinner=False)
def cached_l1_rates(
    run: int,
    pathnames: Tuple[str, ...],
    ls_min: Optional[int],
    ls_max: Optional[int],
    rate_field: str,
    _bucket: int,
) -> pd.DataFrame:
    return oms_data.get_l1_ls_rates(
        run=run,
        pathnames=list(pathnames),
        ls_min=ls_min,
        ls_max=ls_max,
        rate_field=rate_field,
    )


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --oms-bg: #f6f8fb;
            --oms-panel: #ffffff;
            --oms-border: #d9e2ec;
            --oms-muted: #64748b;
            --oms-text: #172033;
            --oms-blue: #2563eb;
            --oms-cyan: #0891b2;
            --oms-green: #059669;
            --oms-red: #dc2626;
            --oms-amber: #d97706;
        }
        .stApp {
            background:
                linear-gradient(180deg, #f7fafc 0%, #f2f6fb 52%, #eef4f9 100%);
            color: var(--oms-text);
        }
        [data-testid="stSidebar"] {
            background: #111827;
            border-right: 1px solid #0f172a;
        }
        [data-testid="stSidebar"] * {
            color: #e5edf7;
        }
        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] textarea,
        [data-testid="stSidebar"] select {
            color: #172033;
        }
        [data-testid="stSidebar"] [role="radiogroup"] label {
            border-radius: 8px;
            padding: 0.22rem 0.35rem;
        }
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 3rem;
            max-width: 1500px;
        }
        h1, h2, h3 {
            letter-spacing: 0;
        }
        div[data-testid="stMetric"] {
            background: var(--oms-panel);
            border: 1px solid var(--oms-border);
            border-radius: 8px;
            padding: 0.85rem 1rem;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.05);
        }
        div[data-testid="stMetricLabel"] {
            color: var(--oms-muted);
        }
        div[data-testid="stMetricValue"] {
            color: var(--oms-text);
            font-weight: 700;
        }
        .oms-titlebar {
            background: #ffffff;
            border: 1px solid var(--oms-border);
            border-left: 5px solid var(--oms-blue);
            border-radius: 8px;
            padding: 1rem 1.15rem;
            margin-bottom: 1rem;
            box-shadow: 0 10px 25px rgba(15, 23, 42, 0.06);
        }
        .oms-titlebar h1 {
            margin: 0;
            font-size: 1.65rem;
            line-height: 1.2;
        }
        .oms-titlebar p {
            margin: 0.35rem 0 0 0;
            color: var(--oms-muted);
        }
        .oms-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 999px;
            padding: 0.22rem 0.58rem;
            font-size: 0.78rem;
            font-weight: 700;
            border: 1px solid transparent;
            white-space: nowrap;
        }
        .oms-badge.live {
            color: #065f46;
            background: #d1fae5;
            border-color: #a7f3d0;
        }
        .oms-badge.closed {
            color: #92400e;
            background: #fef3c7;
            border-color: #fde68a;
        }
        .oms-badge.neutral {
            color: #334155;
            background: #e2e8f0;
            border-color: #cbd5e1;
        }
        .oms-section {
            margin-top: 1.25rem;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 1rem;
        }
        .oms-section h2 {
            margin: 0;
            font-size: 1.05rem;
        }
        .oms-section span {
            color: var(--oms-muted);
            font-size: 0.86rem;
        }
        .oms-kv {
            background: #ffffff;
            border: 1px solid var(--oms-border);
            border-radius: 8px;
            padding: 0.8rem 0.95rem;
            min-height: 5.2rem;
        }
        .oms-kv .label {
            color: var(--oms-muted);
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .oms-kv .value {
            margin-top: 0.35rem;
            font-size: 1.25rem;
            font-weight: 750;
            color: var(--oms-text);
            overflow-wrap: anywhere;
        }
        .oms-kv .hint {
            margin-top: 0.2rem;
            color: var(--oms-muted);
            font-size: 0.8rem;
        }
        .oms-context {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin: 0.25rem 0 0.85rem 0;
        }
        .oms-context code {
            background: #eef6ff;
            border: 1px solid #bfdbfe;
            color: #1e3a8a;
            border-radius: 999px;
            padding: 0.25rem 0.55rem;
            font-size: 0.82rem;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid var(--oms-border);
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
        }
        div[data-testid="stPlotlyChart"] {
            background: #ffffff;
            border: 1px solid var(--oms-border);
            border-radius: 8px;
            padding: 0.35rem;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
        }
        .stButton > button,
        .stFormSubmitButton > button {
            border-radius: 7px;
            font-weight: 700;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_number(value, digits: int = 2, default: str = "-") -> str:
    if value is None or pd.isna(value):
        return default
    if isinstance(value, (int, float)):
        if abs(value) >= 10000:
            return f"{value:,.0f}"
        return f"{value:,.{digits}f}"
    return str(value)


def render_title(title: str, subtitle: str = "", badge: str = "", live: bool = False) -> None:
    badge_html = ""
    if badge:
        badge_class = "live" if live else "closed"
        badge_html = f'<span class="oms-badge {badge_class}">{escape(str(badge))}</span>'
    st.markdown(
        f"""
        <div class="oms-titlebar">
            <div style="display:flex; justify-content:space-between; gap:1rem; align-items:flex-start;">
                <div>
                    <h1>{escape(str(title))}</h1>
                    <p>{escape(str(subtitle))}</p>
                </div>
                {badge_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section(title: str, note: str = "") -> None:
    st.markdown(
        f"""
        <div class="oms-section">
            <h2>{escape(str(title))}</h2>
            <span>{escape(str(note))}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kv(label: str, value, hint: str = "") -> None:
    display_value = format_number(value) if isinstance(value, (int, float)) else value
    st.markdown(
        f"""
        <div class="oms-kv">
            <div class="label">{escape(str(label))}</div>
            <div class="value">{escape(str(display_value))}</div>
            <div class="hint">{escape(str(hint))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_context_chips(items: dict) -> None:
    chips = "".join(
        f"<code>{escape(str(key))}: {escape(str(value))}</code>"
        for key, value in items.items()
    )
    st.markdown(f'<div class="oms-context">{chips}</div>', unsafe_allow_html=True)


def style_plot(fig: go.Figure, height: int = 430) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=18, r=18, t=34, b=18),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            font=dict(size=11),
        ),
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="#ffffff",
        font=dict(family="Arial, sans-serif", color="#172033"),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#e5eaf0", zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="#e5eaf0", zeroline=False)
    return fig


def format_rate_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    formatted = df.copy()
    for column in ["rate", "expected_rate", "deviation", "deviation_pct", "r_squared", "init_lumi"]:
        if column in formatted.columns:
            formatted[column] = pd.to_numeric(formatted[column], errors="coerce")
    return formatted


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown("## OMS Toolkit")
        st.caption("L1 rate monitor")
        page = st.radio(
            "Page",
            ["Dashboard", "Bunch Projection", "L1 Table", "Settings"],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("Shared settings")
        st.session_state["trigger_file"] = st.text_input(
            "L1 trigger file",
            value=st.session_state["trigger_file"],
        )
        rate_label_by_value = {v: k for k, v in config.RATE_FIELD_OPTIONS.items()}
        selected_label = st.selectbox(
            "L1 rate field",
            options=list(config.RATE_FIELD_OPTIONS.keys()),
            index=list(config.RATE_FIELD_OPTIONS.keys()).index(
                rate_label_by_value.get(
                    st.session_state["rate_field"],
                    "Pre-DT before PS",
                )
            ),
        )
        st.session_state["rate_field"] = config.RATE_FIELD_OPTIONS[selected_label]
        return page


def load_current_context() -> Tuple[Optional[dict], Optional[dict]]:
    try:
        bucket = cache_bucket()
        current = cached_current_run(bucket)
        summary = cached_run_summary(int(current["run_number"]), bucket)
        return current, summary
    except Exception as exc:
        st.error(f"Failed to load current GLOBAL-RUN from OMS: {exc}")
        return None, None


def load_trigger_context() -> List[str]:
    try:
        triggers = cached_triggers(st.session_state["trigger_file"])
    except Exception as exc:
        st.warning(f"Could not load trigger file: {exc}")
        return []
    if not triggers:
        st.warning("Trigger file is empty.")
    return triggers


def render_status_cards(summary: dict) -> None:
    cols = st.columns(5)
    with cols[0]:
        render_kv("Run", summary.get("run_number", "-"), "GLOBAL-RUN")
    with cols[1]:
        render_kv("Fill", summary.get("fill_number", "-"), "OMS fill")
    with cols[2]:
        render_kv("Last LS", summary.get("last_lumisection_number", "-"), "latest lumisection")
    with cols[3]:
        render_kv("L1 rate", format_number(summary.get("l1_rate")), "Hz")
    with cols[4]:
        render_kv("Bunches", summary.get("bunches_colliding") or "-", "colliding")

    cols = st.columns(4)
    with cols[0]:
        render_kv("Stable beam", "Yes" if summary.get("stable_beam") else "No", "")
    with cols[1]:
        render_kv("Delivered lumi", format_number(summary.get("delivered_lumi")), "")
    with cols[2]:
        render_kv("Recorded lumi", format_number(summary.get("recorded_lumi")), "")
    with cols[3]:
        render_kv("HLT throughput", format_number(summary.get("hlt_physics_throughput")), "GB/s")

    render_context_chips(
        {
            "L1 menu": summary.get("l1_menu") or "-",
            "L1 key": summary.get("l1_key") or "-",
            "HLT key": summary.get("hlt_key") or "-",
        }
    )


def render_dashboard() -> None:
    current, summary = load_current_context()
    if not summary:
        return
    live = summary.get("end_time") is None
    render_title(
        "OMS L1 Rate Dashboard",
        "Current GLOBAL-RUN status and selected L1 seed rates",
        "LIVE" if live else "CLOSED",
        live=live,
    )

    render_status_cards(summary)
    triggers = load_trigger_context()
    if not triggers:
        return

    last_ls = summary.get("last_lumisection_number")
    if not last_ls:
        st.info("Current run has no lumisection information yet.")
        return

    render_section("Selected L1 Seeds", f"{len(triggers)} seeds from trigger file")
    window = st.slider("Recent LS window", min_value=1, max_value=100, value=20)
    ls_min = max(1, int(last_ls) - int(window) + 1)
    with st.spinner("Loading recent L1 rates..."):
        rates = cached_l1_rates(
            int(summary["run_number"]),
            tuple(triggers),
            ls_min,
            int(last_ls),
            st.session_state["rate_field"],
            cache_bucket(),
        )

    latest = projection.latest_by_pathname(rates)
    if latest.empty:
        st.warning("No L1 rates were found for the selected trigger list.")
    else:
        st.dataframe(
            format_rate_table(latest[["pathname", "lumisection", "rate", "init_lumi", "beams_stable"]]),
            width="stretch",
            hide_index=True,
        )

        fig = px.line(
            rates,
            x="lumisection",
            y="rate",
            color="pathname",
            markers=True,
            color_discrete_sequence=PLOT_COLORS,
            labels={"rate": "Rate [Hz]", "lumisection": "LS"},
        )
        fig = style_plot(fig)
        st.plotly_chart(fig, width="stretch")


def render_bunch_projection() -> None:
    current, summary = load_current_context()
    if not summary:
        return
    render_title(
        "Bunch Projection",
        "Compare current L1 rates against a Heavy Ion reference run scaled by lumi per bunch",
        "MODEL",
        live=True,
    )

    triggers = load_trigger_context()
    if not triggers:
        return

    default_last_ls = int(summary.get("last_lumisection_number") or 1)
    with st.form("projection_form"):
        cols = st.columns(4)
        reference_run = cols[0].number_input("Reference run", min_value=1, value=387892, step=1)
        reference_ls_min = cols[1].number_input("Reference LS min", min_value=1, value=100, step=1)
        reference_ls_max = cols[2].number_input("Reference LS max", min_value=1, value=200, step=1)
        current_run = cols[3].number_input(
            "Current run",
            min_value=1,
            value=int(summary["run_number"]),
            step=1,
        )

        cols = st.columns(3)
        current_ls_window = cols[0].number_input(
            "Current LS window",
            min_value=1,
            value=min(config.DEFAULT_CURRENT_LS_WINDOW, default_last_ls),
            step=1,
        )
        override_reference_bunches = cols[1].number_input(
            "Reference bunch override",
            min_value=0,
            value=0,
            step=1,
        )
        override_current_bunches = cols[2].number_input(
            "Current bunch override",
            min_value=0,
            value=0,
            step=1,
        )
        submitted = st.form_submit_button("Run projection", type="primary")

    if submitted:
        if int(reference_ls_max) < int(reference_ls_min):
            st.error("Reference LS max must be greater than or equal to LS min.")
            return

        try:
            bucket = cache_bucket()
            ref_summary = cached_run_summary(int(reference_run), bucket)
            cur_summary = cached_run_summary(int(current_run), bucket)
            reference_bunches = int(override_reference_bunches) or ref_summary.get("bunches_colliding")
            current_bunches = int(override_current_bunches) or cur_summary.get("bunches_colliding")
            current_last_ls = int(cur_summary.get("last_lumisection_number") or default_last_ls)
            current_ls_min = max(1, current_last_ls - int(current_ls_window) + 1)

            with st.spinner("Loading reference and current L1 rates..."):
                reference_df = cached_l1_rates(
                    int(reference_run),
                    tuple(triggers),
                    int(reference_ls_min),
                    int(reference_ls_max),
                    st.session_state["rate_field"],
                    bucket,
                )
                current_df = cached_l1_rates(
                    int(current_run),
                    tuple(triggers),
                    current_ls_min,
                    current_last_ls,
                    st.session_state["rate_field"],
                    bucket,
                )

            models = projection.fit_bunch_projection(reference_df, reference_bunches)
            projected = projection.apply_projection(current_df, current_bunches, models)

            st.session_state["projection_models"] = projection.models_to_dataframe(models)
            st.session_state["projection_result"] = projected
            st.session_state["reference_inputs"] = {
                "reference_run": int(reference_run),
                "reference_ls": f"{int(reference_ls_min)}-{int(reference_ls_max)}",
                "current_run": int(current_run),
                "current_ls": f"{current_ls_min}-{current_last_ls}",
                "reference_bunches": reference_bunches,
                "current_bunches": current_bunches,
            }
        except Exception as exc:
            st.error(f"Projection failed: {exc}")
            return

    projected = st.session_state.get("projection_result", pd.DataFrame())
    models_df = st.session_state.get("projection_models", pd.DataFrame())
    inputs = st.session_state.get("reference_inputs", {})

    if projected.empty:
        st.info("Run a projection to compare current L1 rates with a reference HI run.")
        return

    render_section("Projection Context", "reference and current comparison window")
    render_context_chips(inputs)

    render_section("Latest Deviation", "sorted by selected trigger list")
    latest = projection.latest_by_pathname(projected)
    st.dataframe(
        format_rate_table(
            latest[
                [
                    "pathname",
                    "lumisection",
                    "rate",
                    "expected_rate",
                    "deviation",
                    "deviation_pct",
                    "r_squared",
                    "model_status",
                ]
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    fig = px.line(
        projected,
        x="lumisection",
        y="deviation_pct",
        color="pathname",
        markers=True,
        color_discrete_sequence=PLOT_COLORS,
        labels={"deviation_pct": "Deviation [%]", "lumisection": "LS"},
    )
    fig.add_hline(y=0, line_width=1, line_dash="dash", line_color="#64748b")
    fig = style_plot(fig)
    st.plotly_chart(fig, width="stretch")

    render_section("Fit Models", "baseline quality for each L1 seed")
    st.dataframe(format_rate_table(models_df), width="stretch", hide_index=True)


def render_l1_table() -> None:
    render_title(
        "L1 Table",
        "Current seed-by-seed rate, projected expectation, and deviation",
        "TABLE",
        live=True,
    )
    projected = st.session_state.get("projection_result", pd.DataFrame())
    if projected.empty:
        st.info("No projection table is available yet. Run Bunch Projection first.")
        return
    latest = projection.latest_by_pathname(projected)
    st.dataframe(
        format_rate_table(latest.sort_values("deviation_pct", ascending=False, na_position="last")),
        width="stretch",
        hide_index=True,
    )


def render_settings() -> None:
    render_title("Settings", "Dashboard refresh, cache, and local repository context", "CONFIG", live=True)
    st.session_state["refresh_seconds"] = st.number_input(
        "Refresh TTL seconds",
        min_value=5,
        max_value=600,
        value=int(st.session_state["refresh_seconds"]),
        step=5,
    )
    st.write("Repository root")
    st.code(str(config.REPO_ROOT))
    st.write("Current cache keys can be reset if OMS data changed unexpectedly.")
    if st.button("Clear Streamlit cache"):
        st.cache_data.clear()
        st.success("Cache cleared.")


def main() -> None:
    _init_state()
    apply_theme()
    page = render_sidebar()
    if page == "Dashboard":
        render_dashboard()
    elif page == "Bunch Projection":
        render_bunch_projection()
    elif page == "L1 Table":
        render_l1_table()
    elif page == "Settings":
        render_settings()


if __name__ == "__main__":
    main()
