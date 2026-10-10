# pyrefly: ignore [missing-import]
import streamlit as st
# pyrefly: ignore [missing-import]
from PIL import Image
import pandas as pd
import copy
import datetime
import hashlib
import io
import json
import os
import html
import time
import api_service


def build_batch_xlsx(rows):
    """Real .xlsx (typed dates and numbers) so Excel doesn't reinterpret dates or show ####."""
    buffer = io.BytesIO()
    frame = pd.DataFrame(rows)
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="สรุป")
        sheet = writer.sheets["สรุป"]
        for column_cells in sheet.columns:
            longest = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
            sheet.column_dimensions[column_cells[0].column_letter].width = min(max(longest + 3, 12), 60)
            header = column_cells[0].value
            for cell in column_cells[1:]:
                if header == "วันที่" and isinstance(cell.value, datetime.date):
                    cell.number_format = "yyyy-mm-dd"
                elif header == "ยอดเงิน (บาท)" and isinstance(cell.value, (int, float)):
                    cell.number_format = "#,##0.00"
    return buffer.getvalue()


def parse_optional_amount(value):
    text = str(value or "").replace(",", "").replace("บาท", "").strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return float(text)


def render_metric_card(label, value, icon):
    st.markdown(
        f"""<div class="doc-metric-card">
            <div class="doc-metric-label"><span>{html.escape(icon)}</span>{html.escape(str(label))}</div>
            <div class="doc-metric-value">{html.escape(str(value))}</div>
        </div>""",
        unsafe_allow_html=True,
    )


# ==================== Page Configuration ====================
st.set_page_config(
    page_title="ระบบวิเคราะห์เอกสารและใบเสร็จอัจฉริยะ (ThaiDocAI)",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== Theme State ====================
if "theme_mode" not in st.session_state:
    st.session_state.theme_mode = "☀️ สว่าง"
is_dark_mode = "สว่าง" not in str(st.session_state.theme_mode)

# ==================== Design Tokens ====================
LIGHT = {
    "bg": "#F5F7FA", "sidebar": "#FFFFFF", "sidebar-border": "#E8EDF2",
    "surface": "#FFFFFF", "surface-alt": "#F0F4F8", "surface-raised": "#FFFFFF",
    "border": "#E2E8F0", "border-strong": "#CBD5E1", "border-focus": "#0F766E",
    "text": "#0F172A", "text-secondary": "#475569", "muted": "#64748B",
    "accent": "#0F766E", "accent-light": "#14B8A6", "accent-soft": "rgba(15,118,110,0.07)",
    "accent-text": "#0F766E", "accent-glow": "rgba(15,118,110,0.15)",
    "accent-blue": "#2563EB", "accent-gold": "#D97706",
    "primary-bg": "#0F766E", "primary-fg": "#FFFFFF", "primary-hover": "#0D635C",
    "shadow-xs": "0 1px 2px rgba(15,23,42,0.04)",
    "shadow-sm": "0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04)",
    "shadow": "0 4px 6px -1px rgba(15,23,42,0.06), 0 2px 4px -2px rgba(15,23,42,0.05)",
    "shadow-md": "0 10px 15px -3px rgba(15,23,42,0.06), 0 4px 6px -4px rgba(15,23,42,0.04)",
    "ok-bg": "#F0FDF4", "ok-bd": "#22C55E", "ok-text": "#166534",
    "info-bg": "#EFF6FF", "info-bd": "#3B82F6", "info-text": "#1E40AF",
    "warn-bg": "#FFFBEB", "warn-bd": "#F59E0B", "warn-text": "#92400E",
    "err-bg": "#FEF2F2", "err-bd": "#EF4444", "err-text": "#991B1B",
    "step-done": "#0F766E", "step-active": "#2563EB", "step-pending": "#CBD5E1",
    "step-line-done": "#0F766E", "step-line-pending": "#E2E8F0",
    "nav-active-bg": "rgba(37,99,235,0.10)", "nav-hover-bg": "rgba(15,23,42,0.03)",
    "metric-icon-bg": "rgba(15,118,110,0.08)",
    "badge-ok-bg": "#DCFCE7", "badge-ok-text": "#166534",
    "badge-wait-bg": "#FEF3C7", "badge-wait-text": "#92400E",
    "badge-err-bg": "#FEE2E2", "badge-err-text": "#991B1B",
    "scheme": "light",
}
DARK = {
    "bg": "#0B1220", "sidebar": "#111827", "sidebar-border": "#1E293B",
    "surface": "#172033", "surface-alt": "#1E293B", "surface-raised": "#1F2D40",
    "border": "#263449", "border-strong": "#334155", "border-focus": "#2DD4BF",
    "text": "#F8FAFC", "text-secondary": "#CBD5E1", "muted": "#94A3B8",
    "accent": "#2DD4BF", "accent-light": "#5EEAD4", "accent-soft": "rgba(45,212,191,0.08)",
    "accent-text": "#5EEAD4", "accent-glow": "rgba(45,212,191,0.18)",
    "accent-blue": "#60A5FA", "accent-gold": "#FBBF24",
    "primary-bg": "#14B8A6", "primary-fg": "#042F2E", "primary-hover": "#0D9488",
    "shadow-xs": "0 1px 2px rgba(0,0,0,0.2)",
    "shadow-sm": "0 1px 3px rgba(0,0,0,0.25), 0 1px 2px rgba(0,0,0,0.2)",
    "shadow": "0 4px 6px -1px rgba(0,0,0,0.25), 0 2px 4px -2px rgba(0,0,0,0.2)",
    "shadow-md": "0 10px 15px -3px rgba(0,0,0,0.3), 0 4px 6px -4px rgba(0,0,0,0.2)",
    "ok-bg": "#052E16", "ok-bd": "#22C55E", "ok-text": "#86EFAC",
    "info-bg": "#0C1E3A", "info-bd": "#3B82F6", "info-text": "#93C5FD",
    "warn-bg": "#2D1F04", "warn-bd": "#F59E0B", "warn-text": "#FCD34D",
    "err-bg": "#2D0F0F", "err-bd": "#EF4444", "err-text": "#FCA5A5",
    "step-done": "#14B8A6", "step-active": "#60A5FA", "step-pending": "#334155",
    "step-line-done": "#14B8A6", "step-line-pending": "#263449",
    "nav-active-bg": "rgba(96,165,250,0.12)", "nav-hover-bg": "rgba(248,250,252,0.03)",
    "metric-icon-bg": "rgba(45,212,191,0.10)",
    "badge-ok-bg": "rgba(34,197,94,0.15)", "badge-ok-text": "#86EFAC",
    "badge-wait-bg": "rgba(245,158,11,0.15)", "badge-wait-text": "#FCD34D",
    "badge-err-bg": "rgba(239,68,68,0.15)", "badge-err-text": "#FCA5A5",
    "scheme": "dark",
}
theme_colors = DARK if is_dark_mode else LIGHT
css_vars = ":root{" + "".join(f"--{k}:{v};" for k, v in theme_colors.items()) + "}"

try:
    native_dark = str(st.context.theme.type) == "dark"
except Exception:
    native_dark = None
grid_filter = (
    "filter: invert(0.92) hue-rotate(180deg);"
    if native_dark is not None and native_dark != is_dark_mode
    else ""
)

# ==================== Modern CSS Design System ====================
STATIC_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+Thai:wght@300;400;500;600;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap');

/* ===== BASE ===== */
html, body, [class*="css"], button, input, textarea, select, option, label, p,
span:not(.material-symbols-rounded):not(.material-symbols-outlined):not(.material-icons):not([data-testid="stIconMaterial"]),
div, h1, h2, h3, h4, h5, h6 {
    font-family: 'Noto Sans Thai', 'IBM Plex Sans Thai', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
/* FIX #1: Ensure Material Symbols icon font renders properly */
.material-symbols-rounded, .material-symbols-outlined, .material-icons,
[data-testid="stIconMaterial"] {
    font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
    font-size: 20px !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    font-style: normal; font-weight: normal; line-height: 1;
    letter-spacing: normal; text-transform: none; white-space: nowrap;
    word-wrap: normal; direction: ltr;
    font-feature-settings: 'liga';
    -webkit-font-feature-settings: 'liga';
}
:root { color-scheme: var(--scheme); }
html, body, .stApp, [data-testid="stApp"], [data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background: var(--bg) !important; color: var(--text) !important;
}
/* FIX #4 & #7: Prevent horizontal page overflow */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
.block-container {
    overflow-x: hidden !important;
}
.block-container { max-width: 1520px; padding: 4.5rem 2rem 4rem 2rem; }

/* ===== HIDE STREAMLIT CHROME ===== */
[data-testid="stToolbar"] button[kind="icon"], [data-testid="stMainMenu"],
[data-testid="stMainMenuPopover"], [data-testid="stAppDeployButton"],
#MainMenu, .stDeployButton, [data-testid="manage-app-button"],
[data-testid="stDecoration"] { display: none !important; visibility: hidden; }

/* ===== NATIVE HEADER ===== */
header[data-testid="stHeader"], .stAppHeader {
    background: var(--bg) !important; border-bottom: 1px solid var(--border); overflow: hidden;
}
header[data-testid="stHeader"] button {
    background: transparent !important; border: none !important; color: var(--text) !important;
}
header[data-testid="stHeader"] button * { color: var(--text) !important; }

/* ===== PROCESSING STATE INDICATOR ===== */
[data-testid="stStatusWidget"], [data-testid="stToolbarActions"] { display: none !important; }
@keyframes tdai-spin { to { transform: rotate(360deg); } }
@keyframes tdai-pulse { 0%,100% { opacity:.55; } 50% { opacity:1; } }
@keyframes tdai-sweep { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
.stApp[data-test-script-state="running"]::before {
    content: "กำลังประมวลผล…"; position: fixed; top: 10px; right: 64px; width: 172px; height: 36px;
    padding: 0 14px 0 40px; display: flex; align-items: center; border-radius: 999px;
    font-size: 0.82rem; font-weight: 600; color: var(--accent-text);
    background: var(--surface); border: 1px solid var(--border-strong); box-shadow: var(--shadow);
    z-index: 1000001; animation: tdai-pulse 1.6s ease-in-out infinite;
}
.stApp[data-test-script-state="running"]::after {
    content: ""; position: fixed; top: 19px; right: 202px; width: 16px; height: 16px; border-radius: 50%;
    border: 2.5px solid var(--accent-soft); border-top-color: var(--accent);
    animation: tdai-spin .75s linear infinite; z-index: 1000002;
}
.stApp[data-test-script-state="running"] header[data-testid="stHeader"]::after {
    content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
    animation: tdai-sweep 1.2s ease-in-out infinite;
}

/* ===== SIDEBAR ===== */
[data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child {
    background: var(--sidebar) !important; border-right: 1px solid var(--sidebar-border);
}
[data-testid="stSidebar"] *:not(svg):not(path):not(.material-symbols-rounded):not(.material-symbols-outlined):not(.material-icons):not([data-testid="stIconMaterial"]) {
    color: var(--text) !important;
}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * { color: var(--muted) !important; }
/* FIX #6: Sidebar expander icon alignment */
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    display: flex; align-items: center; gap: 4px; padding: 8px 12px;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary .material-symbols-rounded,
[data-testid="stSidebar"] [data-testid="stExpander"] summary [data-testid="stIconMaterial"] {
    font-size: 18px !important; color: var(--text) !important;
}

/* sidebar nav items */
.sidebar-nav { display: flex; flex-direction: column; gap: 2px; margin: 8px 0; }
.sidebar-nav-item {
    display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-radius: 10px;
    font-size: 0.88rem; font-weight: 500; color: var(--text-secondary); cursor: default;
    transition: background .15s ease, color .15s ease;
}
.sidebar-nav-item:hover { background: var(--nav-hover-bg); }
.sidebar-nav-item.active {
    background: var(--nav-active-bg); color: var(--accent-text); font-weight: 600;
}
.sidebar-nav-item .nav-icon { font-size: 1.05rem; width: 22px; text-align: center; }
.sidebar-divider {
    height: 1px; background: var(--border); margin: 12px 0; border: none;
}
.sidebar-status {
    display: flex; align-items: center; gap: 8px; padding: 10px 14px;
    font-size: 0.8rem; color: var(--muted);
}
.sidebar-status-dot {
    width: 8px; height: 8px; border-radius: 50%; background: var(--accent);
    box-shadow: 0 0 6px var(--accent-glow);
}

/* ===== COMPACT HEADER ===== */
.compact-header {
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;
    gap: 12px; padding: 16px 24px; margin-bottom: 8px;
    background: linear-gradient(112deg, var(--surface) 0%, color-mix(in srgb, var(--accent-blue) 10%, var(--surface)) 58%, color-mix(in srgb, var(--accent-gold) 12%, var(--surface)) 100%);
    border: 1px solid var(--border); border-left: 5px solid var(--accent-gold); border-radius: 14px;
    box-shadow: var(--shadow-sm);
}
.compact-header-left { display: flex; align-items: center; gap: 14px; }
.compact-header-logo {
    width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center;
    justify-content: center; font-size: 1.4rem;
    background: linear-gradient(145deg, var(--accent-soft), color-mix(in srgb, var(--accent-blue) 20%, var(--surface)));
    border: 1px solid var(--accent-glow); box-shadow: var(--shadow-sm);
}
.compact-header-title { font-size: 1.25rem; font-weight: 700; color: var(--text); line-height: 1.25; }
.compact-header-subtitle { font-size: 0.82rem; color: var(--muted); font-weight: 400; margin-top: 1px; }

.doc-metric-card {
    box-sizing: border-box; width: 100%; min-width: 0; min-height: 112px; height: 100%;
    padding: 16px 18px; display: flex; flex-direction: column; justify-content: flex-start; gap: 8px;
    background: linear-gradient(145deg, var(--surface), color-mix(in srgb, var(--accent-blue) 5%, var(--surface)));
    border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow-sm);
}
.doc-metric-label {
    display: flex; align-items: center; gap: 7px; min-width: 0;
    color: var(--muted); font-size: 0.84rem; font-weight: 500; line-height: 1.35;
}
.doc-metric-value {
    min-width: 0; color: var(--text); font-size: 1.16rem; font-weight: 700; line-height: 1.42;
    white-space: normal; overflow-wrap: anywhere; word-break: normal;
}
.risk-summary-card {
    box-sizing: border-box; width: 100%; min-width: 0; padding: 16px;
    display: flex; flex-direction: column; gap: 8px;
    background: linear-gradient(150deg, var(--surface), color-mix(in srgb, var(--accent-gold) 7%, var(--surface)));
    border: 1px solid var(--border); border-radius: 12px;
}
.risk-summary-label { color: var(--muted); font-size: 0.82rem; line-height: 1.35; }
.risk-summary-level { color: var(--text); font-size: 1rem; font-weight: 700; line-height: 1.4; overflow-wrap: anywhere; }
.risk-score-track { height: 7px; overflow: hidden; border-radius: 999px; background: var(--surface-alt); border: 1px solid var(--border); }
.risk-score-fill { height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--accent), var(--accent-blue), var(--accent-gold)); }
.fraud-check-row {
    display: flex; align-items: flex-start; gap: 9px; min-width: 0; padding: 9px 11px;
    margin: 6px 0; background: var(--surface-alt); border: 1px solid var(--border);
    border-radius: 9px; color: var(--text); line-height: 1.55; overflow-wrap: anywhere;
}
.fraud-check-icon { flex: 0 0 auto; }

/* ===== WORKFLOW STEPPER ===== */
.stepper-wrap {
    display: flex; align-items: center; justify-content: center; gap: 0;
    padding: 14px 20px; margin: 12px 0 20px 0;
    background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
    box-shadow: var(--shadow-xs);
}
.step-item {
    display: flex; align-items: center; gap: 10px; padding: 6px 4px; white-space: nowrap;
}
.step-circle {
    width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; font-size: 0.82rem; font-weight: 700;
    border: 2px solid var(--step-pending); color: var(--muted);
    background: transparent; transition: all .2s ease; flex-shrink: 0;
}
.step-item.done .step-circle {
    background: var(--step-done); border-color: var(--step-done); color: #FFFFFF;
}
.step-item.active .step-circle {
    border-color: var(--step-active); color: var(--step-active);
    box-shadow: 0 0 0 4px var(--accent-soft);
}
.step-label { font-size: 0.85rem; font-weight: 500; color: var(--muted); }
.step-item.done .step-label { color: var(--text-secondary); }
.step-item.active .step-label { color: var(--accent-text); font-weight: 600; }
.step-connector {
    flex: 1; min-width: 32px; max-width: 80px; height: 2px; margin: 0 4px;
    background: var(--step-line-pending); border-radius: 1px;
}
.step-connector.done { background: var(--step-line-done); }

/* ===== TYPOGRAPHY ===== */
h1, h2, h3, h4, h5, h6, [data-testid="stHeading"] *,
[data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3, [data-testid="stMarkdownContainer"] h4 {
    color: var(--text) !important;
}
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li, [data-testid="stWidgetLabel"] *, label, label * {
    color: var(--text) !important;
}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {
    color: var(--muted) !important;
}
a { color: var(--accent-text) !important; }
hr { border-color: var(--border) !important; }
h2 { font-size: 1.3rem !important; font-weight: 700 !important; letter-spacing: -0.01em; }
h3 { font-size: 1.1rem !important; font-weight: 600 !important; }

/* ===== CARDS & CONTAINERS ===== */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--surface) !important; border-color: var(--border) !important;
    border-radius: 14px !important; overflow: hidden;
}
[data-testid="stMetric"] {
    background: var(--surface) !important; border: 1px solid var(--border) !important;
    border-radius: 14px !important; padding: 18px 20px !important; box-shadow: var(--shadow-sm);
    transition: box-shadow .2s ease, border-color .2s ease;
}
[data-testid="stMetric"]:hover {
    box-shadow: var(--shadow); border-color: var(--border-strong) !important;
}
[data-testid="stMetricLabel"] *, [data-testid="stMetricLabel"] p {
    color: var(--muted) !important; font-size: 0.82rem !important; font-weight: 500 !important;
    text-transform: uppercase; letter-spacing: 0.03em;
}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] * {
    color: var(--text) !important; font-weight: 700 !important; font-size: 1.5rem !important;
}
div[data-testid="stForm"] {
    background: var(--surface) !important; border: 1px solid var(--border) !important;
    border-radius: 14px !important; padding: 20px; box-shadow: var(--shadow-xs);
}
[data-testid="stExpander"], [data-testid="stExpander"] details {
    background: var(--surface) !important; border: 1px solid var(--border) !important;
    border-radius: 12px !important;
}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary *:not(.material-symbols-rounded):not([data-testid="stIconMaterial"]) {
    background: transparent !important; color: var(--text) !important; font-weight: 500;
}
[data-testid="stExpander"] summary:hover { background: var(--accent-soft) !important; }

/* ===== INPUTS ===== */
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea, textarea, input {
    background: var(--surface-alt) !important; color: var(--text) !important;
    border-color: var(--border) !important; border-radius: 10px !important;
    -webkit-text-fill-color: var(--text) !important; caret-color: var(--text) !important;
    padding: 10px 14px !important; font-size: 0.9rem !important;
    transition: border-color .15s ease, box-shadow .15s ease;
}
[data-testid="stTextInput"] input:focus, [data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus, textarea:focus, input:focus {
    border-color: var(--border-focus) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
}
[data-testid="stTextInput"] > div > div, [data-testid="stNumberInput"] > div > div,
[data-testid="stTextArea"] > div > div,
[data-testid="stTextInput"] [data-baseweb="input"], [data-testid="stNumberInput"] [data-baseweb="input"],
[data-testid="stTextArea"] [data-baseweb="textarea"] {
    background: var(--surface-alt) !important; border-color: var(--border) !important;
    border-radius: 10px !important;
}
[data-testid="stNumberInput"] button {
    background: var(--surface-alt) !important; color: var(--text) !important;
    border-color: var(--border) !important;
}
::placeholder {
    color: var(--muted) !important; -webkit-text-fill-color: var(--muted) !important; opacity: 0.7;
}

/* ===== SELECT BOX ===== */
[data-baseweb="select"] div { background-color: transparent !important; }
[data-baseweb="select"] > div {
    background-color: var(--surface-alt) !important; border: 1px solid var(--border) !important;
    border-radius: 10px !important; min-height: 44px;
}
[data-baseweb="select"] *:not(.material-symbols-rounded), [data-baseweb="select"] input {
    color: var(--text) !important; fill: var(--text) !important;
    -webkit-text-fill-color: var(--text) !important;
}
[data-baseweb="popover"], [data-baseweb="popover"] > div, [data-baseweb="popover"] ul,
[data-baseweb="menu"], [data-testid="stSelectboxVirtualDropdown"] {
    background: var(--surface) !important; border-radius: 12px !important;
    border: 1px solid var(--border) !important; box-shadow: var(--shadow-md) !important;
}
[data-baseweb="popover"] *, [data-baseweb="menu"] * { color: var(--text) !important; }
[data-baseweb="menu"] li, [data-testid="stSelectboxVirtualDropdown"] li {
    background: transparent !important; border-radius: 8px !important; margin: 2px 4px;
}
[data-baseweb="menu"] li:hover, [data-baseweb="menu"] [aria-selected="true"],
[data-testid="stSelectboxVirtualDropdown"] li:hover {
    background: var(--accent-soft) !important;
}
[data-baseweb="tooltip"] > div, [data-testid="stTooltipContent"] {
    background: var(--surface) !important; color: var(--text) !important;
    border: 1px solid var(--border); border-radius: 10px !important;
}

/* ===== BUTTONS ===== */
.stButton > button, [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-minimal"],
[data-testid="stDownloadButton"] button, [data-testid="stBaseButton-secondaryFormSubmit"] {
    background: var(--surface) !important; color: var(--text) !important;
    border: 1px solid var(--border-strong) !important; border-radius: 10px !important;
    font-weight: 500 !important; font-size: 0.88rem !important; padding: 8px 20px !important;
    min-height: 42px; transition: all .15s ease;
}
.stButton > button:hover, [data-testid="stBaseButton-secondary"]:hover,
[data-testid="stDownloadButton"] button:hover {
    border-color: var(--accent) !important; background: var(--accent-soft) !important;
    color: var(--accent-text) !important; box-shadow: var(--shadow-sm);
}
.stButton > button *, [data-testid="stDownloadButton"] button * { color: inherit !important; }

/* Primary buttons */
.stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"],
[data-testid="stDownloadButton"] button[kind="primary"],
button[data-testid="stBaseButton-primaryFormSubmit"] {
    background: var(--primary-bg) !important; color: var(--primary-fg) !important;
    border: 1px solid var(--primary-bg) !important; border-radius: 10px !important;
    font-weight: 600 !important; box-shadow: var(--shadow-sm);
    min-height: 44px;
}
.stButton > button[kind="primary"] *, .stButton > button[data-testid="stBaseButton-primary"] *,
[data-testid="stDownloadButton"] button[kind="primary"] *,
button[data-testid="stBaseButton-primaryFormSubmit"] * {
    color: var(--primary-fg) !important;
}
.stButton > button[kind="primary"]:hover, .stButton > button[data-testid="stBaseButton-primary"]:hover,
[data-testid="stDownloadButton"] button[kind="primary"]:hover {
    background: var(--primary-hover) !important; color: var(--primary-fg) !important;
    box-shadow: var(--shadow);
}

/* ===== FILE UPLOADER ===== */
[data-testid="stFileUploader"] [data-testid^="stFile"] {
    background: var(--surface-alt) !important;
}
[data-testid="stFileUploaderDropzone"] {
    background: var(--surface-alt) !important;
    border: 2px dashed var(--border-strong) !important; border-radius: 14px !important;
    transition: border-color .2s ease, background .2s ease;
    min-height: 120px;
}
[data-testid="stFileUploaderDropzone"]:hover {
    border-color: var(--accent) !important; background: var(--accent-soft) !important;
}
[data-testid="stFileUploaderDropzone"] *:not(.material-symbols-rounded):not([data-testid="stIconMaterial"]),
[data-testid="stFileUploader"] small,
[data-testid="stFileUploader"] span:not(.material-symbols-rounded):not([data-testid="stIconMaterial"]) {
    color: var(--text) !important;
}
[data-testid="stFileUploaderDropzone"] button {
    background: var(--surface) !important; border: 1px solid var(--border-strong) !important;
    border-radius: 8px !important;
}
[data-testid="stFileUploaderFile"], [data-testid="stFileChip"] {
    background: var(--surface-alt) !important; border: 1px solid var(--border) !important;
    border-radius: 10px !important; min-width: 0 !important; max-width: 100%;
}
[data-testid="stFileUploaderFile"] *:not(.material-symbols-rounded):not([data-testid="stIconMaterial"]),
[data-testid="stFileChip"] *:not(.material-symbols-rounded):not([data-testid="stIconMaterial"]) {
    color: var(--text) !important;
}
[data-testid="stFileUploaderFile"] svg, [data-testid="stFileUploaderDeleteBtn"] svg,
[data-testid="stFileChipDeleteBtn"] svg {
    fill: var(--text) !important; color: var(--text) !important;
}
/* File chip list: wrap cleanly, long names get an ellipsis instead of being cut */
[data-testid="stFileChips"] { gap: 8px; max-height: 320px; overflow-y: auto; }
[data-testid="stFileChip"] { padding: 6px 8px !important; }
[data-testid="stFileChipName"], [data-testid="stFileName"] {
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;
}
[data-testid="stFileUploaderFileData"], [data-testid="stFileUploaderPagination"],
[data-testid="stFileUploaderPagination"] * { background: transparent !important; }
[data-testid="stFileUploader"] > section, [data-testid="stFileUploader"] section > div {
    background: transparent;
}
/* FIX #2: the old max-height on `section > div` clipped the file list; the list itself now scrolls (see stFileChips) */
[data-testid="stFileUploaderDropzone"] { height: auto !important; overflow: visible; flex-wrap: wrap; gap: 8px; }
[data-testid="stFileUploaderDropzoneInstructions"] { min-width: 0; }
/* FIX #3: "add" (Browse files) button icon renders properly in file uploader */
[data-testid="stFileUploaderDropzone"] button .material-symbols-rounded,
[data-testid="stFileUploader"] button .material-symbols-rounded,
[data-testid="stFileUploaderDropzone"] button [data-testid="stIconMaterial"],
[data-testid="stFileUploader"] button [data-testid="stIconMaterial"] {
    font-family: 'Material Symbols Rounded' !important;
    font-size: 18px !important;
}

/* ===== TABS ===== */
[data-baseweb="tabs"], [data-baseweb="tab-list"], [data-baseweb="tab-panel"] {
    background: transparent !important;
}
[data-baseweb="tab-list"]::before, [data-baseweb="tab-list"]::after { display: none !important; }
[data-baseweb="tab-list"] button { background: transparent !important; }
[data-baseweb="tab-list"] {
    gap: 4px; border-bottom: 2px solid var(--border) !important; padding-bottom: 0;
}
[data-baseweb="tab"] p, [data-baseweb="tab"] {
    color: var(--muted) !important; font-weight: 500; font-size: 0.88rem;
    padding: 10px 16px !important;
}
[data-baseweb="tab"][aria-selected="true"] p, [data-baseweb="tab"][aria-selected="true"] {
    color: var(--accent-text) !important; font-weight: 700;
}
[data-baseweb="tab-highlight"] { background-color: var(--accent) !important; height: 2.5px !important; }
[data-baseweb="tab-border"] { background-color: transparent !important; }

/* ===== ALERTS ===== */
[data-testid="stAlert"] {
    background: var(--info-bg) !important; border: 1px solid var(--info-bd) !important;
    border-left: 4px solid var(--info-bd) !important; border-radius: 12px !important;
}
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) {
    background: var(--ok-bg) !important; border-color: var(--ok-bd) !important;
}
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) {
    background: var(--warn-bg) !important; border-color: var(--warn-bd) !important;
}
[data-testid="stAlert"]:has([data-testid="stAlertContentError"]) {
    background: var(--err-bg) !important; border-color: var(--err-bd) !important;
}
[data-testid="stAlert"] *, [data-testid="stNotification"] * { color: var(--text) !important; }

/* ===== CODE / TEXT ===== */
[data-testid="stText"], [data-testid="stCode"], [data-testid="stCode"] pre, pre, code {
    background: var(--surface-alt) !important; color: var(--text) !important; border-radius: 10px;
}
[data-testid="stMarkdownContainer"] table { border-collapse: collapse; width: 100%; }
[data-testid="stMarkdownContainer"] table, [data-testid="stMarkdownContainer"] th,
[data-testid="stMarkdownContainer"] td {
    color: var(--text) !important; border-color: var(--border) !important;
}
[data-testid="stMarkdownContainer"] th {
    background: var(--surface-alt) !important; font-weight: 600; font-size: 0.85rem;
    text-transform: uppercase; letter-spacing: 0.02em;
}

/* ===== CHAT ===== */
[data-testid="stChatMessage"] {
    background: var(--surface-alt) !important; border: 1px solid var(--border) !important;
    border-radius: 14px !important; margin-bottom: 8px;
}
[data-testid="stChatMessage"] * { color: var(--text) !important; }
[data-testid="stBottom"], [data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"] { background: var(--bg) !important; }
[data-testid="stChatInput"], [data-testid="stChatInput"] > div,
[data-testid="stChatInput"] [data-baseweb="textarea"] {
    background: var(--surface-alt) !important; border-color: var(--border-strong) !important;
    border-radius: 12px !important;
}
[data-testid="stChatInput"] textarea {
    color: var(--text) !important; -webkit-text-fill-color: var(--text) !important;
}

/* ===== DATA FRAME / TABLE ===== */
/* FIX #4: Table overflow — scroll horizontally inside container, not page */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
    border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
    width: 100% !important; max-width: 100% !important;
}
[data-testid="stDataFrame"] > div, [data-testid="stDataEditor"] > div {
    max-width: 100% !important; overflow-x: auto !important;
}

/* ===== MISC ===== */
[data-testid="stRadio"] [role="radiogroup"] * { color: var(--text) !important; }
[data-testid="stSpinner"] * { color: var(--text) !important; }
[data-testid="stProgress"] p { color: var(--muted) !important; }
[data-testid="stProgressBarTrack"] {
    background-color: var(--surface-alt) !important; border: 1px solid var(--border);
    border-radius: 999px; overflow: hidden;
}
[data-testid="stProgressBarTrack"] > div {
    background: linear-gradient(90deg, var(--accent), var(--accent-light)) !important;
    border-radius: 999px;
}
[data-testid="stToggle"] p, [data-testid="stCheckbox"] p { color: var(--text) !important; }
[data-testid="stAudio"] audio { width: 100%; }

/* ===== MAIN MENU POPOVER (if visible) ===== */
[data-testid="stMainMenuPopover"], [data-testid="stMainMenuPopover"] > div,
[data-testid="stMainMenuList"] {
    background: var(--surface) !important; border: 1px solid var(--border) !important;
    border-radius: 12px !important;
}
[data-testid="stMainMenuPopover"] *, [data-testid="stMainMenuList"] * { color: var(--text) !important; }
[data-testid="stMainMenuList"] li, [data-testid="stMainMenuList"] [role="option"] {
    background: transparent !important;
}
[data-testid="stMainMenuList"] li:hover, [data-testid="stMainMenuList"] [role="option"]:hover {
    background: var(--accent-soft) !important;
}

/* ===== SECTION HEADERS ===== */
.section-header {
    display: flex; align-items: center; gap: 10px; margin-bottom: 14px;
}
.section-header-icon {
    width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center;
    justify-content: center; font-size: 1.1rem;
    background: linear-gradient(145deg, var(--accent-soft), color-mix(in srgb, var(--accent-blue) 14%, var(--surface)));
    border: 1px solid var(--accent-glow); box-shadow: var(--shadow-xs);
}
.section-header-text { font-size: 1.1rem; font-weight: 700; color: var(--text); }
.section-subtext { font-size: 0.82rem; color: var(--muted); margin-top: 2px; }

/* ===== EMPTY STATE ===== */
.empty-state {
    text-align: center; padding: 48px 24px; color: var(--muted);
}
.empty-state-icon { font-size: 3rem; margin-bottom: 12px; opacity: 0.6; }
.empty-state-title { font-size: 1.05rem; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px; }
.empty-state-desc { font-size: 0.88rem; color: var(--muted); }

/* ===== FIX #1 FALLBACK: Hide icon-text if font still fails ===== */
/* Catch-all: if Material Symbols font fails to load, hide raw text and show CSS fallback */
[data-testid="stExpander"] summary span.material-symbols-rounded,
[data-testid="stFileUploader"] span.material-symbols-rounded,
button span.material-symbols-rounded,
[data-testid="stIconMaterial"] {
    font-family: 'Material Symbols Rounded', sans-serif !important;
    overflow: hidden;
    width: 20px; height: 20px; max-width: 20px;
    display: inline-flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}
[data-testid="stIconMaterial"] { font-size: 20px !important; color: inherit; }
[data-testid="stExpander"] summary [data-testid="stIconMaterial"] { color: var(--text-secondary) !important; }

/* ===== EXTRA POLISH ===== */
/* heading anchor link icons are noise in this app */
[data-testid="stHeaderActionElements"] { display: none !important; }
/* metric values: wrap long names/values instead of cutting them with an ellipsis */
[data-testid="stMetricValue"] > div, [data-testid="stMetricValue"] {
    white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
    overflow-wrap: anywhere; line-height: 1.3;
}
/* selectbox chevron keeps the field background in both themes */
[data-baseweb="select"] [data-baseweb="icon"], [data-baseweb="select"] svg {
    background: transparent !important; color: var(--text-secondary) !important;
    fill: var(--text-secondary) !important;
}
/* sidebar navigation = real buttons that look like menu items */
.st-key-sidebar_nav { gap: 2px; margin: 8px 0; }
.st-key-sidebar_nav .stButton > button {
    justify-content: flex-start; text-align: left; border: 1px solid transparent !important;
    background: transparent !important; box-shadow: none !important; min-height: 42px;
    padding: 8px 14px !important; font-weight: 500 !important;
}
.st-key-sidebar_nav .stButton > button div { justify-content: flex-start; text-align: left; width: 100%; }
.st-key-sidebar_nav .stButton > button:hover { background: var(--nav-hover-bg) !important; border-color: transparent !important; }
.st-key-sidebar_nav .stButton > button[kind="primary"] {
    background: var(--nav-active-bg) !important; border-color: transparent !important; font-weight: 600 !important;
}
/* hidden copy of the uploader that keeps selected files alive on the other pages */
.st-key-tdai_keepalive { display: none !important; }
/* form columns wrap instead of crushing inputs on narrow widths */
[data-testid="stForm"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap; row-gap: 4px; }
[data-testid="stForm"] [data-testid="stColumn"] { min-width: 170px; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary { min-width: 0; }
.compact-header-title, .compact-header-subtitle { overflow-wrap: anywhere; }

/* ===== RESPONSIVE ===== */
@media (max-width: 768px) {
    .block-container { padding: 4rem 0.8rem 3rem 0.8rem; }
    .compact-header { padding: 12px 16px; }
    .compact-header-title { font-size: 1.1rem; }
    .stepper-wrap { padding: 10px 12px; gap: 0; flex-wrap: nowrap; overflow-x: auto; }
    .step-label { font-size: 0.75rem; }
    .step-circle { width: 28px; height: 28px; font-size: 0.75rem; }
    .step-connector { min-width: 16px; }
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] * { font-size: 1.2rem !important; }
    [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
        max-width: calc(100vw - 2rem) !important;
    }
    [data-testid="stFileUploader"] section > div {
        max-height: 200px;
    }
}
@media (max-width: 480px) {
    .compact-header-logo { display: none; }
    .step-label { display: none; }
    .compact-header-title { font-size: 0.95rem; }
    .compact-header-subtitle { font-size: 0.72rem; }
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] * { font-size: 1rem !important; }
}
"""
st.markdown("""
<style>
/* แก้ปัญหาข้อความใน Metric Card ยาวเกินไป */
[data-testid="stMetricValue"] {
    overflow: visible !important;
    white-space: normal !important;
    word-wrap: break-word !important;
    hyphens: auto !important;
}
[data-testid="stMetric"] {
    min-height: 120px !important;
}
</style>
""", unsafe_allow_html=True)
st.markdown(
    f"<style>{css_vars}{STATIC_CSS}"
    f"[data-testid='stDataFrame'], [data-testid='stDataEditor'] {{ {grid_filter} }}"
    f"</style>",
    unsafe_allow_html=True,
)

# ==================== Session State Management ====================
if "scan_result" not in st.session_state:
    st.session_state.scan_result = None
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []
if "selected_document_index" not in st.session_state:
    st.session_state.selected_document_index = 0
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "tts_audio_url" not in st.session_state:
    st.session_state.tts_audio_url = None
if "compare_results" not in st.session_state:
    st.session_state.compare_results = None
if "upload_revision" not in st.session_state:
    st.session_state.upload_revision = 0
if "last_batch_elapsed" not in st.session_state:
    st.session_state.last_batch_elapsed = None
if "batch_sources" not in st.session_state:
    st.session_state.batch_sources = {}
if "nav_page" not in st.session_state:
    st.session_state.nav_page = "docs"
if "export_history" not in st.session_state:
    st.session_state.export_history = []


# ==================== Navigation / Batch-check / Dashboard helpers ====================
NAV_PAGES = [
    ("dashboard", " Dashboard"),
    ("docs", " เอกสารของฉัน"),
    ("checks", " ผลการตรวจสอบ"),
    ("exports", " ประวัติการส่งออก"),
]
CHECK_ICONS = {"checked": "✅", "review": "⚠️", "incomplete": "❗", "error": "❌", "not_processed": "⏸️"}


def _go_page(page):
    st.session_state.nav_page = page


def _document_uploader():
    """The one uploader used by the workspace; other pages render it hidden so selected files survive navigation."""
    return st.file_uploader(
        "เลือกหรือลากวางรูปใบเสร็จ/สลิป (เลือกได้หลายภาพพร้อมกัน)",
        type=["jpg", "png", "jpeg"],
        accept_multiple_files=True,
        key=f"document_upload_{st.session_state.upload_revision}",
        help="สามารถกด Ctrl/Shift เพื่อเลือกหลายรูปพร้อมกัน หรือลากไฟล์หลายๆ รูปมาวางในกรอบนี้ได้เลยครับ",
    )


def _log_export(file_name, file_format, scope):
    st.session_state.export_history.append({
        "เวลา": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ไฟล์": file_name,
        "รูปแบบ": file_format,
        "ขอบเขต": scope,
    })


RESULT_CACHE_LIMIT = 200


def _begin_processing():
    """on_click of the process button. It runs before the script, so the button is already rendered disabled while
    working. A disabled button reports False, so the click itself is remembered in process_requested."""
    st.session_state.processing_since = time.time()
    st.session_state.process_requested = True


def _processing_active():
    started = st.session_state.get("processing_since")
    return bool(started) and time.time() - started < 900  # a stale flag can never lock the button for long


def _remember_result(file_hash, result):
    """Per-session memory of the AI reading of a file (keyed by file content, so a new image never reuses an old one)."""
    if isinstance(result, dict) and result.get("success"):
        cache = st.session_state.setdefault("result_cache", {})
        cache[file_hash] = copy.deepcopy(result)
        while len(cache) > RESULT_CACHE_LIMIT:
            cache.pop(next(iter(cache)))


def _session_memo(name, basis, builder):
    """Rebuild an expensive artefact only when its inputs changed. Stored per session (never shared between users)."""
    fingerprint = hashlib.sha1(json.dumps(basis, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()
    memo = st.session_state.setdefault("_memo", {})
    entry = memo.get(name)
    if entry and entry[0] == fingerprint:
        return entry[1]
    value = builder()
    memo[name] = (fingerprint, value)
    return value


def _summarize_timings(results):
    """Average per-stage seconds and call counts from the 'timings' that api_service attaches to each result."""
    rows = [r["timings"] for r in results if isinstance(r.get("timings"), dict) and not r["timings"].get("reused_duplicate")]
    if not rows:
        return None

    def average(key):
        values = [t[key] for t in rows if isinstance(t.get(key), (int, float))]
        return sum(values) / len(values) if values else None

    totals = [t["total_s"] for t in rows if isinstance(t.get("total_s"), (int, float))]
    return {
        "images": len(rows),
        "prepare_s": average("prepare_s"),
        "vision_s": average("vision_s"),
        "typhoon_wait_s": average("typhoon_wait_s"),
        "refine_s": average("refine_s"),
        "total_s": average("total_s"),
        "max_total_s": max(totals) if totals else None,
        "vision_calls": sum(int(t.get("vision_calls") or 0) for t in rows),
        "refine_calls": sum(1 for t in rows if t.get("refine_used")),
        "typhoon_images": sum(1 for t in rows if t.get("typhoon_status") not in (None, "no_key", "cancelled")),
    }


def _configured_known_names():
    """Names the deployer/user configured permanently: KNOWN_NAMES in .streamlit/secrets.toml (list of tables with
    role/name/account, or plain strings = payer) or the THAIDOC_KNOWN_NAMES environment variable (same as JSON).
    Deliberately not a shared file, so names can never leak between users of a hosted app."""
    raw = None
    try:
        raw = st.secrets.get("KNOWN_NAMES")
    except Exception:
        raw = None
    if raw is None and os.environ.get("THAIDOC_KNOWN_NAMES"):
        try:
            raw = json.loads(os.environ["THAIDOC_KNOWN_NAMES"])
        except ValueError:
            raw = None
    entries = []
    for item in list(raw or []):
        if isinstance(item, str):
            item = {"role": "payer", "name": item}
        try:
            item = dict(item)
        except (TypeError, ValueError):
            continue
        if item.get("name"):
            entries.append({"role": item.get("role") or "payer", "name": str(item["name"]), "account": item.get("account")})
    return entries


def _known_names():
    return _configured_known_names() + list(st.session_state.get("known_names", []))


def _learn_known_names(data):
    """Remember the names of a document the USER confirmed (never names straight from the AI)."""
    if not isinstance(data, dict) or data.get("transfer_amount") is None:
        return
    learned = st.session_state.setdefault("known_names", [])
    known = _known_names()
    for key, role in (("payer_name", "payer"), ("store_name", "receiver")):
        name = str(data.get(key) or "").strip()
        if not name or name == "ไม่ระบุ":
            continue
        existing = next((e for e in known if e.get("role") == role and api_service.name_similarity(e["name"], name) == 1.0), None)
        if existing is not None:
            if role == "payer" and data.get("payer_account") and not existing.get("account"):
                existing["account"] = data["payer_account"]  # learn the account fingerprint for a name we already know
            continue
        entry = {"role": role, "name": name}
        if role == "payer" and data.get("payer_account"):
            entry["account"] = data["payer_account"]
        learned.append(entry)


def _clear_learned_names():
    st.session_state.known_names = []


def _reapply_candidates():
    known = _known_names()
    if not known:
        return []
    found = []
    for index, result in enumerate(st.session_state.scan_results):
        if result.get("success") and not result.get("verified") and isinstance(result.get("data"), dict):
            if api_service.apply_known_names(copy.deepcopy(result["data"]), known):
                found.append(index)
    return found


def _reapply_known_names():
    known = _known_names()
    changed = 0
    for index in _reapply_candidates():
        if api_service.apply_known_names(st.session_state.scan_results[index]["data"], known):
            changed += 1
    if changed:
        st.session_state.review_revision = st.session_state.get("review_revision", 0) + 1


def _clear_export_history():
    st.session_state.export_history = []


def _open_document(index):
    """Jump to the single-document review of results[index] (same state the document picker uses)."""
    results = st.session_state.scan_results
    if 0 <= index < len(results) and results[index].get("success"):
        if st.session_state.selected_document_index != index:
            st.session_state.chat_history = []
            st.session_state.compare_results = None
            st.session_state.tts_audio_url = None
        st.session_state.selected_document_index = index
        st.session_state.pop("selected_document_picker", None)  # let the picker start from selected_document_index
        st.session_state.scan_result = results[index]
        st.session_state.nav_page = "docs"


def _confirm_checked_documents(indices):
    """User-triggered bulk confirmation, limited to documents whose automatic check found nothing to review."""
    for index in indices:
        if 0 <= index < len(st.session_state.scan_results):
            st.session_state.scan_results[index]["verified"] = True
            _learn_known_names(st.session_state.scan_results[index].get("data"))


def _document_amount(result):
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        return None
    amount = data.get("transfer_amount") if data.get("transfer_amount") is not None else data.get("total")
    try:
        return float(str(amount).replace(",", "").replace("บาท", "").strip())
    except (TypeError, ValueError):
        return None


def _fresh_check(result):
    """Stored batch check, only if the document's data has not changed since it was made."""
    check = result.get("batch_check") if isinstance(result, dict) else None
    if isinstance(check, dict) and check.get("fingerprint") == api_service.result_fingerprint(result):
        return check
    return None


def _pending_upload_names():
    files = st.session_state.get(f"document_upload_{st.session_state.upload_revision}") or []
    done = {r.get("file_name") for r in st.session_state.scan_results}
    return [f.name for f in files if f.name not in done]


def _run_batch_checks():
    results = st.session_state.scan_results
    progress = st.progress(0.0, text=f"กำลังตรวจสอบ 0/{len(results)} รายการ")

    def _on_progress(done, total):
        progress.progress(done / total, text=f"ตรวจสอบแล้ว {done}/{total} รายการ")

    checks = api_service.check_batch_results(results, progress_callback=_on_progress)
    progress.empty()
    for result, check in zip(results, checks):
        if isinstance(result, dict):
            result["batch_check"] = check


def render_batch_check_panel(prefix, compact=False):
    """'ตรวจสอบผลลัพธ์ทั้งหมด': runs api_service.check_batch_results (existing checks, no AI/API call)."""
    results = st.session_state.scan_results
    if not results:
        st.info("ยังไม่มีผลลัพธ์ให้ตรวจสอบ · อัปโหลดและประมวลผลเอกสารก่อน")
        return
    fresh = [_fresh_check(r) for r in results]
    pending = _pending_upload_names()
    never_checked = all(c is None for c in fresh)

    if st.button(
        "🔍 ตรวจสอบผลลัพธ์ทั้งหมด" if never_checked else "🔄 ตรวจสอบผลลัพธ์ทั้งหมดอีกครั้ง",
        key=f"{prefix}_run_checks", type="primary", width="stretch",
    ):
        with st.spinner("กำลังตรวจสอบผลลัพธ์ทั้งหมด..."):
            _run_batch_checks()
        st.rerun()
    _candidates = _reapply_candidates()
    if _candidates:
        st.button(
            f"✨ ใช้ชื่อที่คุณเคยยืนยันกับ {len(_candidates)} ฉบับที่ยังไม่ยืนยัน", key=f"{prefix}_reapply_names",
            on_click=_reapply_known_names, width="stretch",
            help="เทียบด้วยเลขบัญชีที่ปิดบังหรือตัวสะกดที่ตรงกัน ชื่อเดิมที่ AI อ่านจะถูกเก็บไว้ดูได้",
        )
    st.caption(
        "ตรวจจากข้อมูลที่ AI อ่านไว้แล้ว (ไม่เรียก AI ซ้ำ): ความครบถ้วนของยอด/วันที่/ผู้รับ · คำเตือนจากการเทียบ OCR · "
        "ชื่อที่อาจอ่านผิด · สมการยอดเงิน — ไม่ใช่การยืนยันธุรกรรมกับธนาคาร"
    )

    counts = {key: 0 for key in api_service.CHECK_STATUS_LABELS}
    unchecked = 0
    for check in fresh:
        if check is None:
            unchecked += 1
        else:
            counts[check["status"]] += 1
    summary = [
        ("ทั้งหมด", f"{len(results)}"),
        ("ตรวจสอบแล้ว", f"{counts['checked']}"),
        ("มีข้อควรระวัง", f"{counts['review'] + counts['incomplete']}"),
        ("ล้มเหลว", f"{counts['error']}"),
        ("ยังไม่ได้ตรวจ", f"{unchecked + counts['not_processed'] + len(pending)}"),
    ]
    per_row = 3 if compact else 5  # the compact panel sits in a narrow column
    for start in range(0, len(summary), per_row):
        row = summary[start:start + per_row]
        for column, (label, value) in zip(st.columns(per_row), row):
            column.metric(label, value)
    if pending:
        st.warning(f"มี {len(pending)} ไฟล์ที่เลือกไว้แต่ยังไม่ได้ประมวลผล: {', '.join(pending[:5])}{' …' if len(pending) > 5 else ''}")
    if never_checked:
        st.info("ยังไม่ได้ตรวจสอบ · กดปุ่มด้านบนเพื่อตรวจทุกรายการพร้อมกัน")
        return
    if unchecked:
        st.caption(f"{unchecked} รายการยังไม่ได้ตรวจหรือข้อมูลเปลี่ยนหลังตรวจ · กดตรวจอีกครั้ง (รายการที่ไม่เปลี่ยนจะใช้ผลเดิม)")
    if counts["review"] + counts["incomplete"]:
        st.caption(f"ควรตรวจทาน {counts['review']} · ข้อมูลไม่ครบ {counts['incomplete']}")

    if not compact:
        rows = []
        for index, (result, check) in enumerate(zip(results, fresh)):
            rows.append({
                "ลำดับ": index + 1,
                "ชื่อไฟล์": result.get("file_name", f"ภาพที่ {index + 1}"),
                "ผลการตรวจ": f"{CHECK_ICONS[check['status']]} {check['label']}" if check else "⏸️ ยังไม่ได้ตรวจ / ข้อมูลเปลี่ยน",
                "ระดับการตรวจ": check["level"] if check else "-",
                "ประเด็นที่พบ": "; ".join(check["issues"]) if check and check["issues"] else "-",
                "ยืนยันโดยผู้ใช้": "✅ ยืนยันแล้ว" if result.get("verified") else "⏳ ยังไม่ยืนยัน",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    problems = [(i, r, c) for i, (r, c) in enumerate(zip(results, fresh)) if c and c["status"] in ("review", "incomplete", "error")]
    if problems:
        st.markdown("**รายการที่ควรดูรายละเอียด**")
    for index, result, check in problems:
        with st.expander(f"{CHECK_ICONS[check['status']]} #{index + 1} {result.get('file_name', '')} — {check['label']}"):
            for issue in check["issues"]:
                st.markdown(f"- {issue}")
            if result.get("success") and isinstance(result.get("data"), dict):
                st.button(
                    "เปิดตรวจและแก้ไขรายการนี้", key=f"{prefix}_open_{index}",
                    on_click=_open_document, args=(index,),
                )
            else:
                st.caption("ใช้ปุ่ม “ประมวลผลซ้ำเฉพาะภาพที่ล้มเหลว” ในหน้าเอกสาร รายการที่สำเร็จแล้วจะไม่ถูกประมวลผลซ้ำ")
                st.button("ไปหน้าเอกสาร", key=f"{prefix}_goto_docs_{index}", on_click=_go_page, args=("docs",))

    eligible = [i for i, (r, c) in enumerate(zip(results, fresh)) if c and c["status"] == "checked" and not r.get("verified")]
    if eligible:
        st.markdown("**ยืนยันทุกฉบับที่ตรวจผ่าน**")
        acknowledged = st.checkbox(
            f"ฉันเทียบกับภาพต้นฉบับแล้ว และขอยืนยันข้อมูล {len(eligible)} ฉบับที่ตรวจผ่าน",
            key=f"{prefix}_confirm_ack",
        )
        st.button(
            f"✅ ยืนยัน {len(eligible)} ฉบับที่ตรวจผ่าน", key=f"{prefix}_confirm_all", disabled=not acknowledged,
            on_click=_confirm_checked_documents, args=(tuple(eligible),), width="stretch",
        )
        st.caption("เป็นการยืนยันโดยผู้ใช้ ไม่ใช่การรับรองจากธนาคาร · ฉบับที่มีข้อควรระวังจะไม่ถูกยืนยันให้")


def _section_header(icon, title, subtitle):
    st.markdown(
        f"""<div class="section-header"><div class="section-header-icon">{icon}</div><div>
        <div class="section-header-text">{html.escape(title)}</div>
        <div class="section-subtext">{html.escape(subtitle)}</div></div></div>""",
        unsafe_allow_html=True,
    )


def _empty_state(icon, title, desc):
    st.markdown(
        f"""<div class="empty-state"><div class="empty-state-icon">{icon}</div>
        <div class="empty-state-title">{html.escape(title)}</div>
        <div class="empty-state-desc">{html.escape(desc)}</div></div>""",
        unsafe_allow_html=True,
    )


def render_dashboard_page():
    _section_header("📊", "Dashboard", "ภาพรวมจากเอกสารที่ประมวลผลในเซสชันนี้")
    results = st.session_state.scan_results
    if not results:
        _empty_state("📄", "ยังไม่มีข้อมูลให้สรุป", "อัปโหลดและประมวลผลเอกสารก่อน แล้วตัวเลขสรุปจะแสดงที่นี่")
        st.button("📄 ไปหน้าอัปโหลดเอกสาร", key="dash_go_docs", on_click=_go_page, args=("docs",), type="primary")
        return

    ok = [(i, r) for i, r in enumerate(results) if r.get("success") and isinstance(r.get("data"), dict)]
    amounts = [(i, _document_amount(r)) for i, r in ok]
    total_amount = sum(a for _, a in amounts if a is not None)
    verified_count = sum(1 for _, r in ok if r.get("verified"))
    failed_count = len(results) - len(ok)
    fresh = [_fresh_check(r) for r in results]
    attention = sum(1 for c in fresh if c and c["status"] in ("review", "incomplete"))

    m1, m2, m3 = st.columns(3)
    m1.metric("📄 เอกสารทั้งหมด", f"{len(results)} ฉบับ")
    m2.metric("✅ อ่านสำเร็จ", f"{len(ok)} / {len(results)}")
    m3.metric("💰 ยอดเงินรวม", f"฿{total_amount:,.2f}")
    m4, m5, m6 = st.columns(3)
    m4.metric("🧾 ยืนยันโดยผู้ใช้แล้ว", f"{verified_count} / {len(ok)}")
    m5.metric("⚠️ ควรตรวจทาน (จากการตรวจทั้งชุด)", f"{attention}" if any(fresh) else "ยังไม่ได้ตรวจ")
    m6.metric("📥 ส่งออกในเซสชันนี้", f"{len(st.session_state.export_history)} ครั้ง")
    if ok:
        st.progress(verified_count / len(ok), text=f"ยืนยันแล้ว {verified_count}/{len(ok)} ฉบับ")
    if failed_count:
        st.warning(f"มี {failed_count} ฉบับที่ประมวลผลไม่สำเร็จ · ไปหน้าเอกสารเพื่อประมวลผลซ้ำเฉพาะที่ล้มเหลว")

    a1, a2, a3 = st.columns(3)
    a1.button("📄 เอกสารของฉัน", key="dash_to_docs", on_click=_go_page, args=("docs",), width="stretch")
    a2.button("🔍 ตรวจสอบผลลัพธ์ทั้งหมด", key="dash_to_checks", on_click=_go_page, args=("checks",), width="stretch", type="primary")
    a3.button("📥 ประวัติการส่งออก", key="dash_to_exports", on_click=_go_page, args=("exports",), width="stretch")

    st.markdown("##### 🧾 รายการเอกสาร")
    rows = []
    for index, result in enumerate(results):
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        check = fresh[index]
        rows.append({
            "ลำดับ": index + 1,
            "ชื่อไฟล์": result.get("file_name", f"ภาพที่ {index + 1}"),
            "ร้านค้า / ผู้รับ": data.get("store_name") or "-",
            "วันที่": data.get("date") or "-",
            "ยอดเงิน (บาท)": _document_amount(result),
            "ผลตรวจทั้งชุด": f"{CHECK_ICONS[check['status']]} {check['label']}" if check else "-",
            "สถานะ": "❌ ล้มเหลว" if not result.get("success") else ("✅ ยืนยันแล้ว" if result.get("verified") else "⏳ รอตรวจทาน"),
        })
    st.dataframe(
        pd.DataFrame(rows), width="stretch", hide_index=True,
        column_config={"ยอดเงิน (บาท)": st.column_config.NumberColumn(format="%.2f")},
    )

    portfolio = api_service.analyze_batch_portfolio(results)
    if portfolio:
        st.markdown("##### 🏷️ ยอดตามหมวดหมู่ค่าใช้จ่าย")
        category_frame = pd.DataFrame(
            [{"หมวดหมู่": name, "ยอดรวม (บาท)": total} for name, total in portfolio["category_totals"]]
        ).set_index("หมวดหมู่")
        st.bar_chart(category_frame)
        if portfolio["duplicates"]:
            st.error(f"ตรวจพบความเสี่ยงเอกสารซ้ำ {len(portfolio['duplicates'])} รายการ · ดูรายละเอียดที่แท็บ วิเคราะห์ AI ในหน้าเอกสาร")


def render_checks_page():
    _section_header("🔍", "ผลการตรวจสอบ", "ตรวจผลลัพธ์ทั้งชุดพร้อมกัน และเปิดดูเฉพาะรายการที่มีปัญหา")
    render_batch_check_panel("pg", compact=False)


def render_exports_page():
    _section_header("📥", "ประวัติการส่งออก", "รายการไฟล์ที่ดาวน์โหลดในเซสชันนี้")
    history = st.session_state.export_history
    if not history:
        _empty_state("📥", "ยังไม่มีการส่งออก", "เมื่อดาวน์โหลด CSV / JSON / Excel จากหน้าเอกสาร รายการจะแสดงที่นี่")
    else:
        e1, e2 = st.columns(2)
        e1.metric("ส่งออกทั้งหมด", f"{len(history)} ครั้ง")
        e2.metric("ล่าสุด", history[-1]["เวลา"])
        st.dataframe(pd.DataFrame(history[::-1]), width="stretch", hide_index=True)
        st.button("🗑️ ล้างประวัติ", key="exports_clear", on_click=_clear_export_history)
    st.caption("ประวัติเก็บเฉพาะในเซสชันนี้ (ไม่มีฐานข้อมูล) · รีเฟรชหรือปิดหน้าเว็บแล้วรายการจะหายไป")
    st.button("📄 ไปหน้าเอกสารเพื่อส่งออก", key="exports_go_docs", on_click=_go_page, args=("docs",), type="primary")

# ==================== Sidebar ====================
with st.sidebar:
    st.markdown("""
    <div style="padding: 6px 0 4px 0;">
        <div style="display:flex; align-items:center; gap:12px; margin-bottom:2px;">
            <div style="width:38px; height:38px; border-radius:10px; display:flex; align-items:center;
                        justify-content:center; font-size:1.3rem; background:var(--accent-soft);
                        border:1px solid var(--accent-glow);">📑</div>
            <div>
                <div style="font-size:1.15rem; font-weight:700; color:var(--text); line-height:1.2;">ThaiDocAI</div>
                <div style="font-size:0.75rem; color:var(--muted); font-weight:400;">AI Document Workspace</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

    # Navigation (real buttons; state in st.session_state.nav_page, so results/uploads survive page changes)
    with st.container(key="sidebar_nav"):
        for _page_id, _page_label in NAV_PAGES:
            st.button(
                _page_label,
                key=f"nav_{_page_id}",
                on_click=_go_page,
                args=(_page_id,),
                type="primary" if st.session_state.nav_page == _page_id else "secondary",
                width="stretch",
            )

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

    # Model info
    selected_model_name = api_service.PRIMARY_MODEL_NAME
    selected_model_id = api_service.PRIMARY_MODEL_ID

    # Voice / Settings
    voice_gender = st.session_state.get("voice_selection", "หญิง (Female)")
    with st.expander("⚙️ การตั้งค่า", expanded=False):
        voice_gender = st.radio(
            "เสียงอ่านผล",
            ["หญิง (Female)", "ชาย (Male)"],
            index=0,
            key="voice_selection",
        )
        st.caption(f"โมเดล: {selected_model_name}")
        _known_now = _known_names()
        st.markdown("**ชื่อที่ยืนยันแล้ว**")
        if _known_now:
            for _entry in _known_now:
                st.caption(
                    f"• {'ผู้จ่าย' if _entry.get('role') == 'payer' else 'ผู้รับ'}: {_entry['name']}"
                    + (f" · บัญชี {_entry['account']}" if _entry.get("account") else "")
                )
            if st.session_state.get("known_names"):
                st.button("🗑️ ล้างชื่อที่เรียนรู้ในเซสชันนี้", key="clear_known_names", on_click=_clear_learned_names)
        st.caption(
            "ระบบจำชื่อจากเอกสารที่คุณกดยืนยัน (เฉพาะเซสชันนี้) เพื่อช่วยแก้ชื่อที่ AI อ่านเพี้ยน · "
            "ตั้งถาวรได้ด้วย KNOWN_NAMES ใน .streamlit/secrets.toml"
        )
    voice_mode = "female" if "หญิง" in voice_gender else "male"

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

    if st.button("🔄 เริ่มเอกสารใหม่ทั้งหมด", width="stretch"):
        st.session_state.scan_result = None
        st.session_state.scan_results = []
        st.session_state.selected_document_index = 0
        st.session_state.chat_history = []
        st.session_state.tts_audio_url = None
        st.session_state.compare_results = None
        st.session_state.last_batch_elapsed = None
        st.session_state.batch_sources = {}
        st.session_state.review_revision = st.session_state.get("review_revision", 0) + 1
        st.session_state.upload_revision += 1
        st.rerun()

    # Status indicator at bottom
    st.markdown("""
    <div class="sidebar-status">
        <div class="sidebar-status-dot"></div>
        ระบบพร้อมใช้งาน
    </div>
    """, unsafe_allow_html=True)

# ==================== Compact Header ====================
col_header, col_theme = st.columns([5, 1], vertical_alignment="center")

with col_header:
    st.markdown("""
    <div class="compact-header">
        <div class="compact-header-left">
            <div class="compact-header-logo">📑</div>
            <div>
                <div class="compact-header-title">ThaiDocAI · ตรวจเอกสารและยอดชำระอัจฉริยะ</div>
                <div class="compact-header-subtitle">อัปโหลดเอกสาร ตรวจสอบข้อมูล และส่งออกผลลัพธ์ได้ในที่เดียว</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col_theme:
    dark_on = st.toggle("🌙 โหมดมืด", value=is_dark_mode, key="theme_toggle")
    new_mode = "🌙 กลางคืน" if dark_on else "☀️ สว่าง"
    if new_mode != st.session_state.theme_mode:
        st.session_state.theme_mode = new_mode
        st.rerun()

# ==================== Page routing ====================
if st.session_state.nav_page in ("dashboard", "checks", "exports"):
    {"dashboard": render_dashboard_page, "checks": render_checks_page, "exports": render_exports_page}[
        st.session_state.nav_page
    ]()
    # Keep the (hidden) uploader alive so files selected but not yet processed are not lost when changing page.
    with st.container(key="tdai_keepalive"):
        _document_uploader()
    st.stop()

# ==================== Workflow Stepper ====================
# Determine current step from existing session state (UI-only logic)
_has_results = len(st.session_state.scan_results) > 0
_successful_results = [r for r in st.session_state.scan_results if r.get("success")]
_all_verified = _has_results and len(_successful_results) > 0 and all(
    r.get("verified") for r in _successful_results
)

if not _has_results:
    _current_step = 1
elif not _all_verified:
    _current_step = 2
else:
    _current_step = 3

_steps = [
    ("1", "อัปโหลดเอกสาร"),
    ("2", "ตรวจสอบผล"),
    ("3", "ยืนยันและส่งออก"),
]

stepper_html = '<div class="stepper-wrap">'
for i, (num, label) in enumerate(_steps):
    step_idx = i + 1
    cls = "done" if step_idx < _current_step else ("active" if step_idx == _current_step else "")
    circle_content = "✓" if step_idx < _current_step else num
    stepper_html += f'<div class="step-item {cls}"><div class="step-circle">{circle_content}</div><div class="step-label">{label}</div></div>'
    if i < len(_steps) - 1:
        line_cls = "done" if step_idx < _current_step else ""
        stepper_html += f'<div class="step-connector {line_cls}"></div>'
stepper_html += '</div>'
st.markdown(stepper_html, unsafe_allow_html=True)

# ==================== Main Workspace ====================
col_upload, col_display = st.columns([1, 1.35], gap="large")

# ==================== Upload Section ====================
with col_upload:
    st.markdown("""
    <div class="section-header">
        <div class="section-header-icon">☁️</div>
        <div>
            <div class="section-header-text">อัปโหลดเอกสาร</div>
            <div class="section-subtext">รองรับ JPG และ PNG · เลือกได้หลายไฟล์พร้อมกัน</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    uploaded_files = _document_uploader()
    _process_requested = st.session_state.pop("process_requested", False)

    if uploaded_files:
        st.success(f"📋 เลือกเอกสารแล้ว {len(uploaded_files)} ภาพ · พร้อมประมวลผล")
        with st.expander("🖼️ ดูตัวอย่างภาพที่เลือก", expanded=len(uploaded_files) <= 3):
            preview_columns = st.columns(min(3, len(uploaded_files)))
            for file_index, uploaded_file in enumerate(uploaded_files):
                with preview_columns[file_index % len(preview_columns)]:
                    st.image(uploaded_file, caption=uploaded_file.name, width="stretch")

        # Files that were already read in this session are reused (no AI call, user edits kept) unless forced.
        _known_hashes = set(st.session_state.get("result_cache", {}))
        for _i, _src in st.session_state.get("batch_sources", {}).items():
            if _i < len(st.session_state.scan_results) and st.session_state.scan_results[_i].get("success"):
                _known_hashes.add(api_service.document_hash(_src[1]))
        _already_read = sum(1 for f in uploaded_files if api_service.document_hash(f.getvalue()) in _known_hashes)
        if _already_read:
            st.info(f"พบ {_already_read} ภาพที่เคยอ่านแล้ว · จะใช้ผลเดิม (ไม่เรียก AI ซ้ำ และไม่ทับข้อมูลที่คุณแก้ไว้)")
            st.checkbox("อ่านใหม่ทั้งหมด (เรียก AI ใหม่แม้เป็นภาพเดิม)", key="force_reprocess")

        _scan_label = f"🚀 เริ่มประมวลผล {len(uploaded_files)} ภาพพร้อมกัน"
        _scan_slot = st.empty()
        with _scan_slot:
            btn_scan = st.button(
                _scan_label, key="scan_btn", type="primary", width="stretch",
                disabled=_processing_active(), on_click=_begin_processing,
            )

        if btn_scan or _process_requested:
            try:
                with st.spinner(f"⚡ กำลังประมวลผล {len(uploaded_files)} ภาพพร้อมกันด้วย AI..."):
                    st.session_state.scan_result = None
                    batch_inputs = []
                    for uploaded_file in uploaded_files:
                        uploaded_file.seek(0)
                        batch_inputs.append((
                            uploaded_file.name,
                            uploaded_file.read(),
                            uploaded_file.type or "image/jpeg",
                        ))
                    input_hashes = [api_service.document_hash(item[1]) for item in batch_inputs]

                    # Reuse results that already exist for identical file content (current results first: they may
                    # hold the user's edits / verification; then the per-session cache of original AI readings).
                    reused = {}
                    if not st.session_state.get("force_reprocess"):
                        current = {}
                        for src_index, src in st.session_state.get("batch_sources", {}).items():
                            if src_index < len(st.session_state.scan_results) and st.session_state.scan_results[src_index].get("success"):
                                current.setdefault(api_service.document_hash(src[1]), st.session_state.scan_results[src_index])
                        cache = st.session_state.get("result_cache", {})
                        for position, file_hash in enumerate(input_hashes):
                            source = current.get(file_hash) or cache.get(file_hash)
                            if source is not None:
                                reused[position] = copy.deepcopy(source)
                    pending = [position for position in range(len(batch_inputs)) if position not in reused]

                    st.session_state.batch_sources = {i: item for i, item in enumerate(batch_inputs)}
                    progress_bar = st.progress(0.0, text=f"เสร็จแล้ว 0/{len(pending)} ภาพ")

                    def _on_detail(done, running, failed, total):
                        queued = max(0, total - done - running)
                        progress_bar.progress(
                            done / total if total else 1.0,
                            text=f"เสร็จ {done}/{total} · กำลังอ่าน {running} · รอคิว {queued} · ล้มเหลว {failed}",
                        )

                    live_slot = st.empty()
                    live_rows = []

                    def _on_result(j, result):
                        _remember_result(input_hashes[pending[j]], result)
                        data_now = result.get("data") if isinstance(result.get("data"), dict) else {}
                        live_rows.append({
                            "ไฟล์": result.get("file_name", ""),
                            "สถานะ": (
                                "✅ อ่านแล้ว · OCR สำรอง"
                                if result.get("success") and result.get("fallback_used")
                                else "✅ อ่านแล้ว" if result.get("success") else "❌ ล้มเหลว"
                            ),
                            "ผู้จ่ายเงิน": data_now.get("payer_name") or "-",
                            "ผู้รับ / ร้านค้า": data_now.get("store_name") or "-",
                            "ยอดเงิน": _document_amount(result),
                        })
                        live_slot.dataframe(pd.DataFrame(live_rows), width="stretch", hide_index=True)

                    batch_started = time.perf_counter()
                    new_results = []
                    if pending:
                        new_results = api_service.extract_documents_batch(
                            [batch_inputs[position] for position in pending],
                            max_workers=6,
                            detail_callback=_on_detail,
                            result_callback=_on_result,
                        )
                    progress_bar.empty()
                    live_slot.empty()
                    _known_for_batch = _known_names()
                    for _fresh in new_results:
                        if _fresh.get("success"):
                            api_service.apply_known_names(_fresh["data"], _known_for_batch)
                    batch_elapsed = time.perf_counter() - batch_started
                    batch_results = [None] * len(batch_inputs)
                    for position, result in reused.items():
                        result["file_name"] = batch_inputs[position][0]
                        result.setdefault("sentiment_result", None)
                        result.setdefault("verified", False)
                        batch_results[position] = result
                    for position, result in zip(pending, new_results):
                        result["sentiment_result"] = None
                        result["verified"] = False
                        batch_results[position] = result
                    st.session_state.scan_results = batch_results
                    st.session_state.last_batch_elapsed = batch_elapsed
                    st.session_state.last_batch_timings = _summarize_timings(new_results)
                    st.session_state.last_batch_reused = len(reused)
                    successful_indices = [i for i, result in enumerate(batch_results) if result.get("success")]
                    st.session_state.selected_document_index = successful_indices[0] if successful_indices else 0
                    st.session_state.scan_result = batch_results[st.session_state.selected_document_index] if successful_indices else None
                    st.session_state.review_revision = st.session_state.get("review_revision", 0) + 1
                    st.session_state.chat_history = []
                    st.session_state.compare_results = None

                    avg_time = batch_elapsed / max(1, len(batch_results))
                    st.success(
                        f"⚡ ประมวลผลเสร็จใน {batch_elapsed:.2f} วินาที "
                        f"(เฉลี่ย {avg_time:.2f} วินาที/ภาพ) · "
                        f"สำเร็จ {len(successful_indices)}/{len(batch_results)} ภาพ"
                        + (f" · ใช้ผลเดิม {len(reused)} ภาพ (ไม่เรียก AI ซ้ำ)" if reused else "")
                    )
                    failed_results = [result for result in batch_results if not result.get("success")]
                    for failed in failed_results:
                        st.warning(f"{failed.get('file_name', 'เอกสาร')}: {failed.get('error', 'ประมวลผลไม่สำเร็จ')}")
                        if failed.get("raw_content"):
                            with st.expander(f"ดูคำตอบดิบจากโมเดล · {failed.get('file_name', '')}"):
                                st.text(failed.get("raw_content"))

            finally:
                st.session_state.processing_since = None
                # The button above was drawn disabled for this run; swap in a usable one right away.
                _scan_slot.button(
                    _scan_label, key="scan_btn_done", type="primary", width="stretch", on_click=_begin_processing,
                )

    # ---- Retry failed images (works across reruns) ----
    _sources = st.session_state.get("batch_sources", {})
    _failed_idx = [
        i for i, r in enumerate(st.session_state.scan_results)
        if not r.get("success") and i in _sources
    ]
    _retryable_idx = [i for i in _failed_idx if st.session_state.scan_results[i].get("retryable", True)]
    _permanent_failed_idx = [i for i in _failed_idx if i not in _retryable_idx]
    _notice = st.session_state.pop("retry_notice", None)
    if _notice:
        st.info(_notice)
    if _failed_idx:
        st.error(f"❌ ประมวลผลไม่สำเร็จ {len(_failed_idx)} ภาพ")
        with st.expander("ดูรายการที่ล้มเหลวและสาเหตุ", expanded=False):
            for i in _failed_idx:
                r = st.session_state.scan_results[i]
                attempts = r.get("attempts")
                attempt_text = f" · ลองอัตโนมัติ {attempts} ครั้ง" if attempts else ""
                st.caption(f"#{i + 1} {r.get('file_name', '')}: {r.get('error', 'ประมวลผลไม่สำเร็จ')}{attempt_text}")
                if r.get("fallback_error"):
                    st.caption(f"สกัดซ้ำจากข้อความ OCR ไม่สำเร็จ: {r['fallback_error']}")
                elif r.get("ocr_fallback_status"):
                    st.caption(f"สถานะ Typhoon OCR สำรอง: {r['ocr_fallback_status']}")
        if _permanent_failed_idx:
            st.warning(f"มี {len(_permanent_failed_idx)} รายการที่ลองซ้ำไม่ได้ เช่น API key/สิทธิ์ HTTP 401/403 · แก้คีย์ใน secrets แล้วเริ่มแอปใหม่ก่อน")
        if _retryable_idx and st.button(
            f"🔁 ลองใหม่เฉพาะ {len(_retryable_idx)} ภาพที่ลองซ้ำได้",
            type="primary",
            width="stretch",
            key="retry_failed_btn",
        ):
            retry_inputs = [_sources[i] for i in _retryable_idx]
            retry_bar = st.progress(0.0, text=f"เสร็จแล้ว 0/{len(retry_inputs)} ภาพ")

            def _on_retry_progress(done, total):
                retry_bar.progress(done / total, text=f"เสร็จแล้ว {done}/{total} ภาพ")

            try:
                with st.spinner(f"ลองส่งคำขอใหม่ทันทีสำหรับ {len(retry_inputs)} ภาพ..."):
                    retry_results = api_service.extract_documents_batch(
                        retry_inputs, max_workers=2, progress_callback=_on_retry_progress, rescue=True
                    )
            except Exception as error:
                retry_results = [
                    {"success": False, "error": str(error), "retryable": True, "file_name": item[0]}
                    for item in retry_inputs
                ]
            finally:
                retry_bar.empty()
            for _item, _res in zip(retry_inputs, retry_results):
                _remember_result(api_service.document_hash(_item[1]), _res)
            recovered = sum(1 for r in retry_results if r.get("success"))
            st.session_state.retry_notice = (
                f"ประมวลผลซ้ำแล้ว: สำเร็จ {recovered}/{len(retry_results)} ภาพ"
                + ("" if recovered == len(retry_results) else " · ที่เหลือดูสาเหตุได้ในรายการที่ล้มเหลวด้านล่าง")
            )
            for i, new_result in zip(_retryable_idx, retry_results):
                new_result["sentiment_result"] = None
                new_result["verified"] = False
                st.session_state.scan_results[i] = new_result
            current = st.session_state.selected_document_index
            if not st.session_state.scan_results[current].get("success"):
                first_ok = next((i for i, r in enumerate(st.session_state.scan_results) if r.get("success")), None)
                if first_ok is not None:
                    st.session_state.selected_document_index = first_ok
            if st.session_state.scan_results:
                st.session_state.scan_result = st.session_state.scan_results[st.session_state.selected_document_index]
            st.session_state.review_revision = st.session_state.get("review_revision", 0) + 1
            st.session_state.chat_history = []
            st.rerun()

# ==================== Results / Display Section ====================
with col_display:
    st.markdown("""
    <div class="section-header">
        <div class="section-header-icon">📊</div>
        <div>
            <div class="section-header-text">ตรวจทานและจัดการผลลัพธ์</div>
            <div class="section-subtext">ตรวจสอบ แก้ไข และส่งออกข้อมูลที่ AI อ่านได้</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    all_results = st.session_state.scan_results
    successful_documents = [
        index for index, result in enumerate(all_results)
        if result.get("success")
    ]

    # ==================== Batch Overview Section ====================
    if all_results:
        with st.container(border=True):
            st.markdown("**🔍 ตรวจสอบผลลัพธ์ทั้งหมด**")
            render_batch_check_panel("ws", compact=True)
            if any(_fresh_check(r) for r in all_results):
                st.button("เปิดหน้า ผลการตรวจสอบ (รายละเอียดทั้งตาราง)", key="ws_go_checks", on_click=_go_page, args=("checks",))
        with st.expander("📊 สรุปภาพรวมชุดเอกสารทั้งหมด (Batch Summary & Export)", expanded=len(all_results) > 1):
            # Calculate Grand Total across all documents
            total_sum = 0.0
            for r in all_results:
                if r.get("success") and isinstance(r.get("data"), dict):
                    d = r["data"]
                    amt = d.get("transfer_amount") if d.get("transfer_amount") is not None else d.get("total")
                    if amt is not None:
                        try:
                            total_sum += float(str(amt).replace(",", "").replace("บาท", "").strip())
                        except (ValueError, TypeError):
                            pass

            _timing = st.session_state.get("last_batch_timings")
            if _timing or st.session_state.get("last_batch_reused"):
                with st.expander("⏱️ เวลาและจำนวนการเรียก AI ของชุดล่าสุด", expanded=False):
                    if _timing:
                        def _sec(value):
                            return "-" if value is None else f"{value:.2f}"
                        st.dataframe(pd.DataFrame([
                            {"ขั้นตอน": "เตรียมภาพ", "เฉลี่ยต่อภาพ (วินาที)": _sec(_timing["prepare_s"])},
                            {"ขั้นตอน": "โมเดลภาพอ่านเอกสาร (รวมทุกรอบ)", "เฉลี่ยต่อภาพ (วินาที)": _sec(_timing["vision_s"])},
                            {"ขั้นตอน": "รอ Typhoon OCR (หลังโมเดลภาพเสร็จ)", "เฉลี่ยต่อภาพ (วินาที)": _sec(_timing["typhoon_wait_s"])},
                            {"ขั้นตอน": "อ่านชื่อรอบสอง (เฉพาะที่จำเป็น)", "เฉลี่ยต่อภาพ (วินาที)": _sec(_timing["refine_s"])},
                            {"ขั้นตอน": "รวมต่อภาพ (เฉลี่ย)", "เฉลี่ยต่อภาพ (วินาที)": _sec(_timing["total_s"])},
                            {"ขั้นตอน": "รวมต่อภาพ (ช้าสุด)", "เฉลี่ยต่อภาพ (วินาที)": _sec(_timing["max_total_s"])},
                        ]), width="stretch", hide_index=True)
                        st.caption(
                            f"ประมวลผลจริง {_timing['images']} ภาพ · เรียกโมเดลภาพ {_timing['vision_calls']} ครั้ง · "
                            f"อ่านชื่อรอบสอง {_timing['refine_calls']} ครั้ง · ใช้ผล Typhoon {_timing['typhoon_images']} ภาพ"
                        )
                    st.caption(
                        f"ใช้ผลเดิม/ภาพซ้ำ {st.session_state.get('last_batch_reused', 0)} ภาพ (ไม่เรียก AI) · "
                        "แต่ละขั้นนับเวลาแยกกัน และ Typhoon ทำงานขนานกับโมเดลภาพ จึงรวมกันไม่เท่ากับเวลารวม · "
                        "ตัวเลขนี้วัดจากการใช้งานจริงของชุดล่าสุดเท่านั้น"
                    )
            b_m1, b_m2, b_m3 = st.columns(3)
            b_m1.metric("📄 จำนวนที่สแกน", f"{len(all_results)} ภาพ")
            b_m2.metric("✅ สำเร็จ", f"{len(successful_documents)} / {len(all_results)} ภาพ")
            b_m3.metric("💰 ยอดเงินรวมทุกใบเสร็จ", f"฿{total_sum:,.2f}")

            # Build batch overview table
            batch_table_data = []
            export_rows = []
            for idx, r in enumerate(all_results):
                fname = r.get("file_name", f"ภาพที่ {idx + 1}")
                if r.get("success") and isinstance(r.get("data"), dict):
                    d = r["data"]
                    doc_type = d.get("document_type") or ("สลิปโอนเงิน" if d.get("transfer_amount") is not None else "ใบเสร็จรับเงิน")
                    store = d.get("store_name") or "ไม่ระบุ"
                    payer = d.get("payer_name") or ("-" if d.get("transfer_amount") is None else "ไม่ระบุ")
                    if api_service.name_looks_unreliable(d.get("store_name")) and d.get("transfer_amount") is not None:
                        store += " ⚠️"
                    if api_service.name_looks_unreliable(d.get("payer_name")) and d.get("transfer_amount") is not None:
                        payer += " ⚠️"
                    dt = d.get("date") or "ไม่ระบุ"
                    amt = d.get("transfer_amount") if d.get("transfer_amount") is not None else d.get("total")
                    amt_str = f"{float(amt):,.2f}" if amt is not None else "อ่านยอดไม่ได้"
                    v_str = "✅ ยืนยันแล้ว" if r.get("verified") else "⏳ รอตรวจทาน"
                    name_source = d.get("name_source") or "-"
                    notes = "; ".join(d.get("check_warnings") or []) or "-"
                    if r.get("fallback_used"):
                        name_source = f"OCR สำรอง ({r['fallback_used']}) · {name_source}"
                        notes = "ข้อมูลกู้จากข้อความ OCR สำรอง กรุณาตรวจเทียบกับภาพต้นฉบับ" + (f"; {notes}" if notes != "-" else "")
                    batch_table_data.append({
                        "ลำดับ": idx + 1,
                        "ชื่อไฟล์": fname,
                        "ประเภท": doc_type,
                        "ร้านค้า / ผู้รับ": store,
                        "ผู้จ่ายเงิน / ผู้โอน": payer,
                        "วันที่": dt,
                        "ยอดเงิน (บาท)": amt_str,
                        "แหล่งชื่อ": name_source,
                        "ตรวจสอบ": notes,
                        "สถานะ": v_str,
                    })
                    try:
                        date_cell = datetime.date.fromisoformat(dt)
                    except (TypeError, ValueError):
                        date_cell = dt
                    export_rows.append({
                        "ลำดับ": idx + 1,
                        "ชื่อไฟล์": fname,
                        "ประเภท": doc_type,
                        "ร้านค้า / ผู้รับ": store,
                        "ผู้จ่ายเงิน / ผู้โอน": payer,
                        "วันที่": date_cell,
                        "ยอดเงิน (บาท)": float(amt) if amt is not None else None,
                        "แหล่งชื่อ": name_source,
                        "ตรวจสอบ": notes,
                        "สถานะ": v_str,
                    })
                else:
                    batch_table_data.append({
                        "ลำดับ": idx + 1,
                        "ชื่อไฟล์": fname,
                        "ประเภท": "-",
                        "ร้านค้า / ผู้รับ": "-",
                        "ผู้จ่ายเงิน / ผู้โอน": "-",
                        "วันที่": "-",
                        "ยอดเงิน (บาท)": "-",
                        "แหล่งชื่อ": "-",
                        "ตรวจสอบ": r.get("error") or "-",
                        "สถานะ": "❌ ล้มเหลว",
                    })
                    export_rows.append(dict(batch_table_data[-1]))

            batch_df = pd.DataFrame(batch_table_data)
            st.dataframe(batch_df, width="stretch", hide_index=True)

            # Export buttons
            if successful_documents:
                st.markdown("##### 📥 ส่งออกข้อมูล")
                exp_col1, exp_col2, exp_col3 = st.columns(3)
                combined_csv_bytes = batch_df.to_csv(index=False).encode("utf-8-sig")
                exp_col1.download_button(
                    "📥 ตารางสรุป (CSV)",
                    data=combined_csv_bytes,
                    file_name="batch_documents_summary.csv",
                    on_click=_log_export, args=("batch_documents_summary.csv", "CSV", "ทั้งชุด"),
                    mime="text/csv",
                    width="stretch",
                )
                exp_col3.download_button(
                    "📥 ตารางสรุป (Excel)",
                    data=_session_memo("batch_xlsx", export_rows, lambda: build_batch_xlsx(export_rows)),
                    file_name="batch_documents_summary.xlsx",
                    on_click=_log_export, args=("batch_documents_summary.xlsx", "Excel", "ทั้งชุด"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                )
                combined_json = [r.get("data") for r in all_results if r.get("success")]
                exp_col2.download_button(
                    "📥 ข้อมูลรวม (JSON)",
                    data=json.dumps(combined_json, ensure_ascii=False, indent=2).encode("utf-8"),
                    file_name="batch_documents_data.json",
                    on_click=_log_export, args=("batch_documents_data.json", "JSON", "ทั้งชุด"),
                    mime="application/json",
                    width="stretch",
                )

    # ==================== Document Picker ====================
    if len(successful_documents) > 1:
        st.markdown("##### 🔎 เลือกเอกสารเพื่อตรวจทานและแก้ไขรายฉบับ")
        selected_index = st.selectbox(
            "เลือกเอกสารที่ต้องการตรวจทาน",
            successful_documents,
            index=(
                successful_documents.index(st.session_state.selected_document_index)
                if st.session_state.selected_document_index in successful_documents
                else 0
            ),
            format_func=lambda index: f"🧾 #{index + 1}: {all_results[index].get('file_name', f'เอกสาร {index + 1}')} — {'✅ ยืนยันแล้ว' if all_results[index].get('verified') else '⏳ รอตรวจ'}",
            key="selected_document_picker",
            label_visibility="collapsed",
        )
        if selected_index != st.session_state.selected_document_index:
            st.session_state.chat_history = []
            st.session_state.compare_results = None
            st.session_state.tts_audio_url = None
        st.session_state.selected_document_index = selected_index
        st.session_state.scan_result = all_results[selected_index]

    # ==================== Empty State ====================
    if not st.session_state.scan_result:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-state-icon">📄</div>
            <div class="empty-state-title">ยังไม่มีเอกสาร</div>
            <div class="empty-state-desc">อัปโหลดรูปภาพและกด <strong>เริ่มประมวลผล</strong> เพื่อเริ่มตรวจสอบ</div>
        </div>
        """, unsafe_allow_html=True)

    # ==================== Document Detail (Tabs) ====================
    else:
        res = st.session_state.scan_result
        doc_data = res.get("data")
        raw_content = res.get("raw_content", "")

        tab1, tab2, tab3, tab4 = st.tabs([
            "📄 ตรวจ / ส่งออก",
            "🧠 วิเคราะห์ AI",
            "💬 ถาม-ตอบ",
            "⚙️ ตรวจยอด"
        ])

        # ==================== Tab 1: Review & Export ====================
        with tab1:
            if doc_data and isinstance(doc_data, dict):
                is_transfer_doc = (
                    doc_data.get("transfer_amount") is not None
                    or "สลิป" in str(doc_data.get("document_type", ""))
                    or "โอน" in str(doc_data.get("document_type", ""))
                )
                review_revision = st.session_state.get("review_revision", 0)

                # Status badge
                if res.get("verified"):
                    st.success("✅ ยืนยันข้อมูลฉบับนี้แล้ว · พร้อมส่งออก")
                else:
                    st.warning("⏳ รอตรวจทาน: เทียบยอดและรายละเอียดกับภาพก่อนยืนยัน")

                st.markdown("#### ✏️ ตรวจและแก้ข้อมูลที่อ่านได้")
                st.caption("แก้ช่องที่ไม่ตรงกับภาพได้ก่อนบันทึก · การยืนยันนี้เป็นการตรวจโดยผู้ใช้ ไม่ใช่การรับรองจากธนาคาร")

                review_key = f"{review_revision}_{st.session_state.selected_document_index}"
                with st.form(f"review_document_{review_key}"):
                    identity_cols = st.columns([1.2, 0.9, 1.4])
                    reviewed_store = identity_cols[0].text_input(
                        "ผู้รับเงิน (สลิป) / ร้านค้า (ใบเสร็จ)",
                        value=str(doc_data.get("store_name") or ""),
                    )
                    reviewed_date = identity_cols[1].text_input(
                        "วันที่ในเอกสาร",
                        value=str(doc_data.get("date") or ""),
                    )
                    reviewed_reference = identity_cols[2].text_input(
                        "เลขที่ / เลขอ้างอิง",
                        value=str(doc_data.get("receipt_no") or ""),
                    )

                    edited_items = None
                    reviewed_payer = None
                    if is_transfer_doc:
                        payer_cols = st.columns([1.5, 1.5])
                        reviewed_payer = payer_cols[0].text_input(
                            "ผู้จ่ายเงิน / ผู้โอน",
                            value=str(doc_data.get("payer_name") or ""),
                        )
                        amount_cols = st.columns(3)
                        reviewed_transfer = amount_cols[0].text_input(
                            "ยอดโอนถึงผู้รับ (บาท)",
                            value=str(doc_data.get("transfer_amount") if doc_data.get("transfer_amount") is not None else doc_data.get("total") or ""),
                        )
                        reviewed_fee = amount_cols[1].text_input(
                            "ค่าธรรมเนียม (บาท)", value=str(doc_data.get("fee") if doc_data.get("fee") is not None else "")
                        )
                        reviewed_debit = amount_cols[2].text_input(
                            "ยอดหักบัญชีรวม (บาท)", value=str(doc_data.get("debited_total") or "")
                        )
                    else:
                        amount_cols = st.columns(3)
                        reviewed_total = amount_cols[0].text_input(
                            "ยอดสุทธิที่ชำระ (บาท)", value=str(doc_data.get("total") if doc_data.get("total") is not None else "")
                        )
                        reviewed_subtotal = amount_cols[1].text_input(
                            "ยอดก่อนภาษี (บาท)", value=str(doc_data.get("subtotal") if doc_data.get("subtotal") is not None else "")
                        )
                        reviewed_vat = amount_cols[2].text_input(
                            "VAT (บาท)", value=str(doc_data.get("vat") if doc_data.get("vat") is not None else "")
                        )
                        adjustment_cols = st.columns(3)
                        reviewed_discount = adjustment_cols[0].text_input(
                            "ส่วนลด (บาท)", value=str(doc_data.get("discount") if doc_data.get("discount") is not None else "")
                        )
                        reviewed_shipping = adjustment_cols[1].text_input(
                            "ค่าจัดส่ง (บาท)", value=str(doc_data.get("shipping") if doc_data.get("shipping") is not None else "")
                        )
                        reviewed_service = adjustment_cols[2].text_input(
                            "ค่าบริการ (บาท)", value=str(doc_data.get("service_charge") if doc_data.get("service_charge") is not None else "")
                        )

                        item_rows = [
                            {
                                "name": item.get("name", ""),
                                "quantity": item.get("quantity", 1),
                                "unit_price": item.get("unit_price", item.get("price")),
                                "line_total": item.get("line_total"),
                            }
                            for item in (doc_data.get("items") or [])
                        ]
                        st.markdown("##### 🛒 รายการสินค้า / บริการ")
                        edited_items = st.data_editor(
                            pd.DataFrame(item_rows, columns=["name", "quantity", "unit_price", "line_total"]),
                            column_config={
                                "name": st.column_config.TextColumn("รายการ", required=True),
                                "quantity": st.column_config.NumberColumn("จำนวน", min_value=0.0, step=1.0),
                                "unit_price": st.column_config.NumberColumn("ราคาต่อหน่วย (บาท)", min_value=0.0, format="%.2f"),
                                "line_total": st.column_config.NumberColumn("รวมรายการ (บาท)", min_value=0.0, format="%.2f"),
                            },
                            num_rows="dynamic",
                            hide_index=True,
                            width="stretch",
                            key=f"review_items_{review_key}",
                        )

                    confirmed = st.form_submit_button("✅ บันทึกการตรวจทานและยืนยัน", type="primary", width="stretch")

                if confirmed:
                    try:
                        reviewed_data = dict(doc_data)
                        reviewed_data["store_name"] = reviewed_store.strip() or "ไม่ระบุ"
                        reviewed_data["date"] = reviewed_date.strip() or "ไม่ระบุ"
                        normalized_date = api_service.parse_date(reviewed_data["date"])
                        if normalized_date:
                            reviewed_data["date"] = normalized_date
                        reviewed_data["check_warnings"] = []  # the user has now checked these against the image
                        reviewed_data["receipt_no"] = reviewed_reference.strip() or "ไม่ระบุ"
                        if is_transfer_doc:
                            transfer_value = parse_optional_amount(reviewed_transfer)
                            if transfer_value is None:
                                raise ValueError("กรุณาระบุยอดโอนที่อ่านจากภาพ")
                            reviewed_data["transfer_amount"] = transfer_value
                            reviewed_data["total"] = transfer_value
                            reviewed_data["fee"] = parse_optional_amount(reviewed_fee)
                            reviewed_data["debited_total"] = parse_optional_amount(reviewed_debit)
                            reviewed_data["payer_name"] = (reviewed_payer or "").strip() or None
                        else:
                            for field, value in (
                                ("total", reviewed_total),
                                ("subtotal", reviewed_subtotal),
                                ("vat", reviewed_vat),
                                ("discount", reviewed_discount),
                                ("shipping", reviewed_shipping),
                                ("service_charge", reviewed_service),
                            ):
                                reviewed_data[field] = parse_optional_amount(value)
                            if reviewed_data["total"] is None:
                                raise ValueError("กรุณาระบุยอดสุทธิที่อ่านจากภาพ")
                            reviewed_data["items"] = [
                                {
                                    "name": str(row["name"]).strip(),
                                    "quantity": (
                                        parse_optional_amount(row["quantity"])
                                        if parse_optional_amount(row["quantity"]) is not None
                                        else 1
                                    ),
                                    "unit_price": parse_optional_amount(row["unit_price"]),
                                    "line_total": parse_optional_amount(row["line_total"]),
                                }
                                for _, row in edited_items.iterrows()
                                if str(row["name"]).strip()
                            ]
                        reviewed_data["ocr_text"] = api_service.summarize_document_data(reviewed_data)
                        res["data"] = reviewed_data
                        res["verified"] = True
                        _learn_known_names(reviewed_data)
                        st.session_state.scan_result = res
                        if st.session_state.scan_results:
                            st.session_state.scan_results[st.session_state.selected_document_index] = res
                        st.session_state.chat_history = []
                        st.success("บันทึกและยืนยันข้อมูลแล้ว")
                        st.rerun()
                    except (TypeError, ValueError) as error:
                        st.error(f"บันทึกไม่ได้: {error}")

                # ---- Metric Cards ----
                m1, m2, m3 = st.columns([1.5, 0.9, 0.9], gap="small")
                with m1:
                    render_metric_card("ร้านค้า / แหล่งที่มา", doc_data.get("store_name") or "ไม่ระบุ", "🏢")
                with m2:
                    render_metric_card("วันที่", doc_data.get("date") or "ไม่ระบุ", "📅")
                transfer_amount = doc_data.get("transfer_amount")
                total_value = transfer_amount if transfer_amount is not None else doc_data.get("total")
                total_display = (
                    f"{float(total_value):,.2f} บาท"
                    if total_value is not None and total_value != ""
                    else "อ่านยอดไม่ได้"
                )
                amount_label = "💸 ยอดโอน" if transfer_amount is not None else "💰 ยอดสุทธิ (Total)"
                with m3:
                    render_metric_card(amount_label, total_display, "💸" if transfer_amount is not None else "💰")
                for check_warning in doc_data.get("check_warnings") or []:
                    st.warning(check_warning)
                if not res.get("verified") and is_transfer_doc:
                    _grade_text = {"exact": "ตรงกับ OCR", "near": "ใกล้เคียง OCR", "absent": "ไม่พบใน OCR", "unknown": "เทียบกับ OCR ไม่ได้", "known": "ตรงกับชื่อที่เคยยืนยัน"}
                    _checks = doc_data.get("name_check") or {}
                    st.caption(
                        "เทียบชื่อกับ OCR ต้นฉบับ · ผู้จ่าย: " + _grade_text.get(_checks.get("payer_name"), "ยังไม่ได้เทียบ (ไม่มีข้อความ OCR)")
                        + " · ผู้รับ: " + _grade_text.get(_checks.get("store_name"), "ยังไม่ได้เทียบ (ไม่มีข้อความ OCR)")
                    )
                    for _field, _label in (("payer_name", "ผู้จ่ายเงิน"), ("store_name", "ผู้รับเงิน/ร้านค้า")):
                        _alt = (doc_data.get("name_model_reading") or {}).get(_field)
                        if _alt:
                            st.caption(f"โมเดลภาพอ่าน{_label}ได้: {_alt}")
                if transfer_amount is not None:
                    fee_value = doc_data.get("fee")
                    debit_value = doc_data.get("debited_total")
                    payer_display = doc_data.get("payer_name") or "อ่านไม่ได้"
                    fee_display = f"{float(fee_value):,.2f} บาท" if fee_value is not None else "อ่านไม่ได้"
                    debit_display = f"{float(debit_value):,.2f} บาท" if debit_value is not None else "อ่านไม่ได้"
                    st.caption(f"ผู้จ่ายเงิน/ผู้โอน: {payer_display} | ค่าธรรมเนียม: {fee_display} | ยอดหักบัญชีรวม: {debit_display}")
                    suspect_names = api_service.unreliable_name_fields(doc_data)
                    if suspect_names:
                        st.warning(
                            f"ชื่อ{' และ '.join(suspect_names)}มีอักษรอังกฤษปนกับไทย โมเดลอาจอ่านผิด "
                            "กรุณาเทียบกับภาพและแก้ในฟอร์มตรวจทานก่อนยืนยัน"
                        )

                review_audit = api_service.audit_financials(doc_data)
                if review_audit["status"] == "passed":
                    st.success(f"ตรวจสมการยอดแล้ว · {review_audit['msg']}")
                elif review_audit["status"] == "warning":
                    st.warning(f"พบยอดที่ควรตรวจ · {review_audit['msg']}")
                else:
                    st.info(f"สถานะตรวจยอด · {review_audit['msg']}")

                st.markdown("##### 🛒 รายการสินค้าและบริการที่ตรวจพบ")
                items = doc_data.get("items") or []
                if items:
                    export_rows = []
                    for item in items:
                        raw_quantity = parse_optional_amount(item.get("quantity"))
                        quantity = raw_quantity if raw_quantity is not None else 1
                        unit_price = parse_optional_amount(item.get("unit_price", item.get("price")))
                        line_total = parse_optional_amount(item.get("line_total"))
                        if line_total is None and unit_price is not None:
                            line_total = quantity * unit_price
                        export_rows.append({
                            "รายการ": item.get("name", ""),
                            "จำนวน": quantity,
                            "ราคาต่อหน่วย (บาท)": unit_price,
                            "รวมรายการ (บาท)": line_total,
                        })
                    df = pd.DataFrame(export_rows)
                    st.dataframe(df, width="stretch", hide_index=True)
                else:
                    st.info("เอกสารนี้เป็นสลิปหรือไม่มีรายการสินค้าแยกบรรทัด สามารถส่งออกข้อมูลยอดเงินเป็น JSON ได้")

                # ---- Export per document ----
                st.markdown("##### 📥 ส่งออกข้อมูล")
                if res.get("verified"):
                    export_cols = st.columns(2)
                    json_str = json.dumps(doc_data, ensure_ascii=False, indent=2)
                    export_cols[0].download_button(
                        label="ดาวน์โหลดเอกสารที่ยืนยันแล้ว (JSON)",
                        data=json_str.encode("utf-8"),
                        file_name=f"document_{doc_data.get('receipt_no') or 'verified'}.json",
                        on_click=_log_export,
                        args=(f"document_{doc_data.get('receipt_no') or 'verified'}.json", "JSON", "รายเอกสาร"),
                        mime="application/json",
                        width="stretch",
                    )
                    if items:
                        export_cols[1].download_button(
                            label="ดาวน์โหลดรายการเพื่อนำเข้าบัญชี (CSV)",
                            data=df.to_csv(index=False).encode("utf-8-sig"),
                            file_name=f"items_{doc_data.get('receipt_no') or 'verified'}.csv",
                            on_click=_log_export,
                            args=(f"items_{doc_data.get('receipt_no') or 'verified'}.csv", "CSV", "รายเอกสาร"),
                            mime="text/csv",
                            width="stretch",
                        )
                else:
                    st.caption("ยืนยันการตรวจทานก่อนดาวน์โหลด เพื่อแยกข้อมูลที่ AI อ่านออกจากข้อมูลที่ตรวจแล้ว")

                # ---- Document summary text ----
                if doc_data.get("ocr_text"):
                    st.markdown("##### 📝 สรุปสาระสำคัญของเอกสาร")
                    st.info(doc_data.get("ocr_text"))
                if raw_content:
                    with st.expander("ตรวจข้อความ OCR ต้นฉบับและเทียบยอดกับภาพ"):
                        st.text(raw_content)
                        st.caption("ผล OCR และการสกัดข้อมูลอาจคลาดเคลื่อน โปรดเทียบยอดสุทธิ/ยอดโอนกับภาพต้นฉบับก่อนนำไปใช้งาน")
            else:
                st.markdown("##### 📝 ข้อความที่อ่านได้จากเอกสาร:")
                st.info(raw_content)

        # ==================== Tab 2: AI Business Intelligence ====================
        with tab2:
            st.markdown("#### 🧠 วิเคราะห์ข้อมูลธุรกิจและภาษีอัจฉริยะ")
            st.caption("จัดผังบัญชี ตรวจสอบเกณฑ์ภาษีสรรพากร และตรวจจับความเสี่ยงทุจริตในบิล")

            bi_res = api_service.analyze_document_business_intelligence(doc_data, raw_content)
            cat_info = bi_res["expense_category"]
            tax_info = bi_res["tax_compliance"]
            fraud_info = bi_res["fraud_anomaly"]
            exec_info = bi_res["executive_insights"]

            # Row 1: Category & Tax Compliance
            c_cat, c_tax = st.columns(2)
            with c_cat:
                with st.container(border=True):
                    st.markdown("##### 🏷️ จัดหมวดหมู่ค่าใช้จ่าย & ผังบัญชี")
                    st.markdown(f"**หมวดหมู่:** `{cat_info['name']}`")
                    st.markdown(f"**รหัสบัญชีแนะนำ:** <span style='font-size:1.2rem; font-weight:700; color:var(--accent-text);'>{cat_info['code']}</span>", unsafe_allow_html=True)
                    st.caption(f"ความมั่นใจ: {cat_info['confidence']} · {cat_info['reason']}")
                    st.text_area(
                        "Journal Entry Narration:",
                        value=cat_info['narration'],
                        height=68,
                        help="สามารถคัดลอกข้อความนี้ไปลงสมุดรายวันทั่วไปในโปรแกรมบัญชีได้ทันที"
                    )

            with c_tax:
                with st.container(border=True):
                    st.markdown("##### 📋 การประเมินสิทธิ์ภาษี & การเบิกจ่าย")
                    st.markdown(f"**ประเภทเอกสาร:** {tax_info['doc_type']}")
                    st.markdown(f"**เลขประจำตัวผู้เสียภาษี 13 หลัก:** `{tax_info['tax_id']}`")
                    st.markdown(f"**สิทธิ์เคลมภาษีซื้อ (VAT):** {tax_info['claimable']}")
                    st.markdown(f"**สถานะการเบิกจ่าย:** **{tax_info['status']}**")
                    st.caption(tax_info['notes'])

            # Row 2: Fraud Risk & Anomaly Detection
            with st.container(border=True):
                st.markdown("##### 🛡️ ตรวจจับความผิดปกติและความเสี่ยงทุจริต")
                risk_score = max(0, min(100, int(fraud_info.get("score", 0) or 0)))
                r_col1, r_col2 = st.columns([1, 2], gap="medium")
                with r_col1:
                    st.markdown(
                        f"""<div class="risk-summary-card">
                            <div class="risk-summary-label">ระดับความเสี่ยง</div>
                            <div class="risk-summary-level">{html.escape(str(fraud_info.get('level', 'ไม่ทราบ')))}</div>
                            <div class="risk-summary-label">คะแนนความเสี่ยง · {risk_score}/100</div>
                            <div class="risk-score-track"><div class="risk-score-fill" style="width:{risk_score}%"></div></div>
                        </div>""",
                        unsafe_allow_html=True,
                    )
                with r_col2:
                    st.markdown("**ผลการตรวจสอบ (Audit Checklist):**")
                    for chk in fraud_info["checks"]:
                        icon, _, description = str(chk).partition(" ")
                        st.markdown(
                            f'<div class="fraud-check-row"><span class="fraud-check-icon">{html.escape(icon)}</span>'
                            f'<span>{html.escape(description or chk)}</span></div>',
                            unsafe_allow_html=True,
                        )

            # Row 3: Executive Summary
            with st.container(border=True):
                st.markdown("##### 💡 บทสรุปสำหรับผู้บริหาร")
                st.info(exec_info["summary"])
                for rec in exec_info["recommendations"]:
                    st.markdown(rec)

            # Multi-document Portfolio Overview
            if len(successful_documents) > 1:
                st.divider()
                st.markdown("#### 📊 ภาพรวมชุดเอกสารทั้งหมด (Batch Portfolio)")
                batch_portfolio = api_service.analyze_batch_portfolio(all_results)
                if batch_portfolio:
                    bp1, bp2, bp3 = st.columns(3)
                    bp1.metric("💰 ยอดใช้จ่ายรวม", f"{batch_portfolio['total_spending']:,.2f} บาท")
                    bp2.metric("🧾 ยอดภาษีซื้อรวม (VAT)", f"{batch_portfolio['total_vat']:,.2f} บาท")
                    bp3.metric("✅ ภาษีซื้อที่เคลมได้", f"{batch_portfolio['claimable_vat']:,.2f} บาท")

                    if batch_portfolio["duplicates"]:
                        st.error(f"🚨 **ตรวจพบความเสี่ยงเอกสารซ้ำซ้อน {len(batch_portfolio['duplicates'])} รายการ!**")
                        for dup in batch_portfolio["duplicates"]:
                            st.warning(f"**{dup['type']}:** {dup['detail']}")
                    else:
                        st.success("✅ ไม่พบเอกสารซ้ำซ้อนหรือยอดซ้ำในชุดเอกสารนี้")

                    st.markdown("**สัดส่วนค่าใช้จ่ายตามหมวดหมู่:**")
                    cat_rows = []
                    for c_name, c_tot in batch_portfolio["category_totals"]:
                        pct = (c_tot / batch_portfolio["total_spending"] * 100) if batch_portfolio["total_spending"] > 0 else 0
                        cat_rows.append({
                            "หมวดหมู่ค่าใช้จ่าย": c_name,
                            "จำนวนเอกสาร": batch_portfolio["category_counts"].get(c_name, 0),
                            "ยอดรวม (บาท)": f"{c_tot:,.2f}",
                            "สัดส่วน (%)": f"{pct:.1f}%"
                        })
                    st.dataframe(pd.DataFrame(cat_rows), width="stretch", hide_index=True)

        # ==================== Tab 3: Document Q&A Chat ====================
        with tab3:
            st.markdown("#### 💬 ถามข้อมูลจากเอกสาร (Smart Q&A)")
            ok_results = [r for r in all_results if r.get("success")]
            scope_all = False
            if len(ok_results) > 1:
                scope_choice = st.radio(
                    "ขอบเขตการถาม",
                    ["📚 ทั้งชุดทุกฉบับ", "📄 เฉพาะฉบับที่เลือก"],
                    horizontal=True,
                    key="qa_scope",
                )
                scope_all = scope_choice.startswith("📚")
                if st.session_state.get("_qa_scope_prev") != scope_choice:
                    st.session_state._qa_scope_prev = scope_choice
                    st.session_state.chat_history = []
            if scope_all:
                st.caption(f"AI จะตอบจากข้อมูล {len(ok_results)} ฉบับพร้อมกัน · ยอดรวมและสถิติคำนวณโดยระบบ ไม่ใช่ให้ AI บวกเอง")
                context_to_send = api_service.format_batch_context_for_qa(all_results)
            else:
                st.caption(f"ใช้โมเดล {selected_model_name} · ตอบจากข้อมูลจริงในเอกสารที่เลือก")
                context_to_send = api_service.format_document_context_for_qa(doc_data, raw_content)

            def submit_question(q_text):
                st.session_state.chat_history.append({"role": "user", "content": q_text})
                with st.spinner("🤖 AI กำลังค้นหาคำตอบจากเอกสาร..."):
                    ans_obj = api_service.ask_document_qa(
                        context_to_send, q_text, selected_model_id,
                        max_tokens=1200 if scope_all else 800,
                        timeout=60 if scope_all else 35,
                    )
                    reply = ans_obj.get("answer") if ans_obj.get("success") else f"❌ {ans_obj.get('error')}"
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": reply,
                        "time": ans_obj.get("elapsed_time"),
                    })
                st.rerun()

            is_slip = bool(doc_data and doc_data.get("transfer_amount") is not None)
            if scope_all:
                quick_questions = [
                    ("💰 ยอดรวมทั้งหมด", "สรุปยอดรวมทั้งหมดของทุกเอกสาร จำนวนฉบับ และค่าเฉลี่ยต่อฉบับ"),
                    ("🏆 สูงสุด / ต่ำสุด", "เอกสารฉบับไหนมียอดสูงที่สุดและต่ำที่สุด ระบุชื่อไฟล์ ผู้รับ และวันที่"),
                    ("👥 ยอดแยกตามผู้รับ", "สรุปยอดรวมแยกตามผู้รับเงินหรือร้านค้า เรียงจากมากไปน้อย"),
                    ("📅 ยอดแยกตามวัน", "สรุปยอดรวมแยกตามวันที่ และบอกวันที่มียอดสูงที่สุด"),
                ]
            elif is_slip:
                quick_questions = [
                    ("💸 ยอดโอนและค่าธรรมเนียม", "สรุปยอดเงินโอน ค่าธรรมเนียม และยอดหักบัญชีทั้งหมดของสลิปนี้"),
                    ("👤 ผู้โอนและผู้รับ", "ใครเป็นผู้โอนเงิน และโอนเงินไปยังใคร?"),
                    ("🧾 วันที่และเลขอ้างอิง", "ทำรายการเมื่อวันที่และเวลาใด และมีรหัสอ้างอิงหรือเลขที่ทำรายการอะไรบ้าง?"),
                    ("🏷️ หมวดบัญชีและสิทธิ์เบิก", "รายการนี้ควรลงบัญชีหมวดไหน และใช้เบิกบริษัทได้หรือไม่?"),
                ]
            else:
                quick_questions = [
                    ("📦 รายการสินค้าและราคา", "ในเอกสารนี้มีรายการสินค้าหรือบริการอะไรบ้าง แต่ละรายการราคาเท่าไหร่?"),
                    ("💰 ยอดเงินและ VAT", "สรุปยอดรวม ยอดก่อนภาษี ภาษีมูลค่าเพิ่ม (VAT) และส่วนลดของเอกสารนี้"),
                    ("🏆 สินค้าแพงสุด/ถูกสุด", "สินค้าชิ้นไหนราคาสูงที่สุด และชิ้นไหนราคาต่ำที่สุด คิดเป็นกี่บาท?"),
                    ("🏢 ร้านค้าและผู้ขาย", "เอกสารนี้ออกจากร้านค้าใด มีเลขที่ใบเสร็จ หรือข้อมูลที่อยู่/สาขาอะไรบ้าง?"),
                ]

            st.markdown("**💡 คำถามด่วน**")
            quick_cols = st.columns(len(quick_questions))
            for q_col, (q_label, q_text) in zip(quick_cols, quick_questions):
                if q_col.button(q_label, width="stretch", key=f"qa_quick_{int(scope_all)}_{q_label}"):
                    submit_question(q_text)

            st.divider()

            chat_box = st.container(height=380)
            with chat_box:
                if len(st.session_state.chat_history) == 0:
                    st.markdown("""
                    <div class="empty-state" style="padding:32px 16px;">
                        <div class="empty-state-icon">💬</div>
                        <div class="empty-state-title">ยังไม่มีบทสนทนา</div>
                        <div class="empty-state-desc">กดคำถามด่วนด้านบนหรือพิมพ์คำถามได้เลย</div>
                    </div>
                    """, unsafe_allow_html=True)
                for msg in st.session_state.chat_history:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])
                        if "time" in msg and msg["time"]:
                            st.caption(f"⏱️ ตอบโดย AI ใน {msg['time']} วินาที")

            user_query = st.chat_input(
                "พิมพ์คำถามเกี่ยวกับทุกสลิป เช่น 'ใครได้รับเงินมากที่สุด?'" if scope_all
                else "พิมพ์คำถามเกี่ยวกับเอกสาร เช่น 'ซื้ออะไรไปบ้าง?' หรือ 'คิดเป็นเงินกี่บาท?'"
            )
            if user_query:
                submit_question(user_query)

        # ==================== Tab 4: Audit & Accessibility ====================
        with tab4:
            st.markdown("#### ⚙️ ตรวจสอบสมการยอดเงิน (Financial Audit)")
            st.caption("ระบบตรวจเฉพาะสมการที่มีตัวเลขครบ หากข้อมูลบางส่วนอ่านไม่ได้จะแจ้งว่าต้องตรวจเพิ่ม")

            audit = api_service.audit_financials(doc_data)
            if audit["status"] == "passed":
                st.success(audit["msg"])
            elif audit["status"] == "warning":
                st.warning(audit["msg"])
            else:
                st.info(audit["msg"])

            st.divider()
            st.markdown("#### 🎧 สังเคราะห์เสียงอ่านสรุปเอกสาร (Thai TTS)")
            st.caption(f"ระดับเสียง: {voice_gender}")
            if st.button("สร้างเสียงอ่านสรุปผลภาษาไทย", disabled=not api_service.AIFORTHAI_APIKEY):
                tail = "ค่ะ" if voice_mode == "female" else "ครับ"
                store_txt = doc_data.get("store_name", "เอกสาร") if doc_data else "เอกสาร"
                financial_summary = api_service.summarize_document_data(doc_data or {})
                text_to_speak = f"เอกสารจาก {store_txt} {financial_summary}{tail}"
                st.session_state.tts_audio_url = api_service.call_vaja_tts(text_to_speak, mode=voice_mode)
                st.rerun()
            if st.session_state.tts_audio_url:
                st.audio(st.session_state.tts_audio_url)
            elif not api_service.AIFORTHAI_APIKEY:
                st.caption("ต้องตั้งค่า AI For Thai API key เพื่อใช้เสียงอ่าน")
            else:
                st.caption("ยังไม่ได้กดสร้างเสียงอ่านผล")

            st.divider()
            st.markdown("#### 📊 วิเคราะห์โทนข้อความเอกสาร (Sentiment Analysis)")
            sentiment_res = res.get("sentiment_result")
            if st.button("วิเคราะห์โทนข้อความด้วย SSense", key="run_sentiment", disabled=not api_service.AIFORTHAI_APIKEY):
                sample_text = (doc_data.get("ocr_text", "") if doc_data else raw_content)[:120]
                res["sentiment_result"] = api_service.call_ssense(sample_text)
                st.session_state.scan_result = res
                st.rerun()

            if sentiment_res and "sentiment" in sentiment_res:
                s_info = sentiment_res["sentiment"]
                pol = s_info.get("polarity", "neutral")
                score = s_info.get("score", "0")
                badge_map = {
                    "positive": "🟢 โทนบวก (Positive / น่าเชื่อถือและพึงพอใจ)",
                    "negative": "🔴 โทนลบ (Negative / ร้องเรียนหรือมีข้อผิดพลาด)",
                    "neutral": "⚪ โทนกลาง (Neutral / เอกสารทางการหรือข้อเท็จจริง)"
                }
                st.write(f"**ผลประเมินโทน:** {badge_map.get(pol, pol)}")
                st.write(f"**ระดับความเชื่อมั่น:** {score}%")
            else:
                if not api_service.AIFORTHAI_APIKEY:
                    st.caption("ยังไม่ได้ตั้งค่า AI For Thai API key")
                else:
                    st.caption("ยังไม่ได้เรียกใช้เครื่องมือนี้")