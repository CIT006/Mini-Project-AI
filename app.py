# pyrefly: ignore [missing-import]
import streamlit as st
# pyrefly: ignore [missing-import]
from PIL import Image
import pandas as pd
import datetime
import io
import json
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


# ==================== ตั้งค่าหน้าเว็บ Streamlit ====================
st.set_page_config(
    page_title="ระบบวิเคราะห์เอกสารและใบเสร็จอัจฉริยะ (ThaiDocAI)",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded"
)

if "theme_mode" not in st.session_state:
    st.session_state.theme_mode = "☀️ สว่าง"
is_dark_mode = "สว่าง" not in str(st.session_state.theme_mode)

LIGHT = {
    "bg": "#F3F6F9", "sidebar": "#FFFFFF", "surface": "#FFFFFF", "surface-alt": "#EEF2F6",
    "border": "#D9E1E8", "border-strong": "#B7C4D0", "text": "#142033", "muted": "#566579",
    "accent": "#0F766E", "accent-soft": "rgba(15,118,110,0.10)", "accent-text": "#0F766E",
    "primary-bg": "#0F766E", "primary-fg": "#FFFFFF",
    "hero": "linear-gradient(120deg, #0F766E 0%, #0E5F66 55%, #1E4E79 100%)",
    "shadow": "0 1px 3px rgba(20,32,51,0.08), 0 4px 14px rgba(20,32,51,0.05)",
    "ok-bg": "#E6F6EF", "ok-bd": "#2F9E6F", "info-bg": "#E8F1FB", "info-bd": "#3B82C4",
    "warn-bg": "#FFF4DE", "warn-bd": "#D9922B", "err-bg": "#FDECEC", "err-bd": "#D14B4B",
    "scheme": "light",
}
DARK = {
    "bg": "#0C1218", "sidebar": "#101820", "surface": "#141D27", "surface-alt": "#1B2633",
    "border": "#263443", "border-strong": "#3A4B5D", "text": "#E7EDF3", "muted": "#9BAABA",
    "accent": "#2DD4BF", "accent-soft": "rgba(45,212,191,0.12)", "accent-text": "#5EEAD4",
    "primary-bg": "#14B8A6", "primary-fg": "#04201D",
    "hero": "linear-gradient(120deg, #0B3B3A 0%, #0F3550 60%, #1B2E55 100%)",
    "shadow": "0 1px 3px rgba(0,0,0,0.4), 0 6px 20px rgba(0,0,0,0.25)",
    "ok-bg": "#12302A", "ok-bd": "#2FB985", "info-bg": "#122B40", "info-bd": "#4B9BE0",
    "warn-bg": "#3A2C12", "warn-bd": "#E0A53B", "err-bg": "#3C1A1D", "err-bd": "#E16A6A",
    "scheme": "dark",
}
theme_colors = DARK if is_dark_mode else LIGHT
css_vars = ":root{" + "".join(f"--{k}:{v};" for k, v in theme_colors.items()) + "}"

# Streamlit draws dataframe/data_editor on a canvas that CSS colours cannot reach. If Streamlit's
# own theme differs from the mode chosen here, invert the canvas so it matches.
try:
    native_dark = str(st.context.theme.type) == "dark"
except Exception:
    native_dark = None
grid_filter = (
    "filter: invert(0.92) hue-rotate(180deg);"
    if native_dark is not None and native_dark != is_dark_mode
    else ""
)

STATIC_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"], button, input, textarea { font-family: 'IBM Plex Sans Thai', sans-serif; }
:root { color-scheme: var(--scheme); }
html, body, .stApp, [data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background: var(--bg) !important; color: var(--text) !important;
}

.block-container { max-width: 1480px; padding-top: 2.2rem; padding-bottom: 4rem; }

/* ---- ซ่อนจุดสามจุด (Main Menu) และปุ่ม Deploy มุมขวาบน ---- */
[data-testid="stToolbar"] button[kind="icon"],
[data-testid="stMainMenu"],
[data-testid="stMainMenuPopover"],
[data-testid="stAppDeployButton"],
#MainMenu {
    display: none !important;
    visibility: hidden
}

/* ---- native header / toolbar ---- */
header[data-testid="stHeader"], .stAppHeader { background: var(--bg) !important; }
header[data-testid="stHeader"] { overflow: hidden; }
header[data-testid="stHeader"] button { background: transparent !important; border: none !important; }
header[data-testid="stHeader"] button, header[data-testid="stHeader"] button * { color: var(--text) !important; }

/* ---- hide Streamlit's running-man + Stop button, use our own animation ---- */
[data-testid="stStatusWidget"], [data-testid="stToolbarActions"] { display: none !important; }
@keyframes tdai-spin { to { transform: rotate(360deg); } }
@keyframes tdai-sweep { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
@keyframes tdai-pulse { 0%, 100% { opacity: .55; } 50% { opacity: 1; } }
.stApp[data-test-script-state="running"]::before {
    content: "AI กำลังประมวลผล"; position: fixed; top: 10px; right: 64px; width: 176px; height: 34px; box-sizing: border-box;
    padding: 0 14px 0 40px; display: flex; align-items: center; border-radius: 999px; font-size: 0.85rem; font-weight: 600;
    color: var(--accent-text); background: var(--surface); border: 1px solid var(--border-strong); box-shadow: var(--shadow);
    z-index: 1000001; animation: tdai-pulse 1.6s ease-in-out infinite; }
.stApp[data-test-script-state="running"]::after {
    content: ""; position: fixed; top: 18px; right: 206px; width: 16px; height: 16px; border-radius: 50%;
    border: 3px solid var(--accent-soft); border-top-color: var(--accent); animation: tdai-spin .8s linear infinite; z-index: 1000002; }
.stApp[data-test-script-state="running"] header[data-testid="stHeader"]::after {
    content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 3px;
    background: linear-gradient(90deg, transparent, var(--accent), transparent); animation: tdai-sweep 1.2s ease-in-out infinite; }

/* ---- main menu (three dots) ---- */
[data-testid="stMainMenuPopover"], [data-testid="stMainMenuPopover"] > div, [data-testid="stMainMenuList"] {
    background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; }
[data-testid="stMainMenuPopover"] *, [data-testid="stMainMenuList"] * { color: var(--text) !important; }
[data-testid="stMainMenuList"] li, [data-testid="stMainMenuList"] [role="option"] { background: transparent !important; }
[data-testid="stMainMenuList"] li:hover, [data-testid="stMainMenuList"] [role="option"]:hover { background: var(--accent-soft) !important; }
[data-testid="stDecoration"] { display: none !important; }
.stDeployButton, [data-testid="stAppDeployButton"], [data-testid="manage-app-button"] { display: none !important; }

/* ---- typography ---- */
h1, h2, h3, h4, h5, h6, [data-testid="stHeading"] *, [data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3, [data-testid="stMarkdownContainer"] h4 { color: var(--text) !important; }
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
[data-testid="stWidgetLabel"] *, label, label * { color: var(--text) !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * { color: var(--muted) !important; }
a { color: var(--accent-text) !important; }
hr { border-color: var(--border) !important; }
h2 { font-size: 1.35rem !important; font-weight: 700 !important; }

/* ---- sidebar ---- */
[data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child { background: var(--sidebar) !important; border-right: 1px solid var(--border); }
[data-testid="stSidebar"] *:not(svg):not(path) { color: var(--text) !important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * { color: var(--muted) !important; }

/* ---- hero ---- */
.hero { background: var(--hero); border-radius: 16px; padding: 22px 26px; box-shadow: var(--shadow); }
.hero h1 { color: #FFFFFF !important; font-size: 1.6rem; font-weight: 700; margin: 0 0 6px 0; padding: 0; }
.hero p { color: rgba(255,255,255,0.88) !important; font-size: 0.97rem; margin: 0 0 14px 0; }
.hero-steps { display: flex; flex-wrap: wrap; gap: 8px; }
.hero-step { display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 999px;
    font-size: 0.82rem; font-weight: 600; background: rgba(255,255,255,0.16); color: #FFFFFF;
    border: 1px solid rgba(255,255,255,0.28); }

/* ---- cards / containers ---- */
[data-testid="stVerticalBlockBorderWrapper"] { background: var(--surface) !important; border-color: var(--border) !important; border-radius: 14px !important; }
[data-testid="stMetric"] { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; padding: 12px 14px !important; box-shadow: var(--shadow); }
[data-testid="stMetricLabel"] *, [data-testid="stMetricLabel"] p { color: var(--muted) !important; font-size: 0.86rem !important; }
[data-testid="stMetricValue"], [data-testid="stMetricValue"] * { color: var(--text) !important; font-weight: 700 !important; }
div[data-testid="stForm"] { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 14px !important; padding: 16px; }
[data-testid="stExpander"], [data-testid="stExpander"] details { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * { background: transparent !important; color: var(--text) !important; }
[data-testid="stExpander"] summary:hover { background: var(--accent-soft) !important; }

/* ---- inputs ---- */
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input, [data-testid="stTextArea"] textarea, textarea, input {
    background: var(--surface-alt) !important; color: var(--text) !important; border-color: var(--border) !important;
    -webkit-text-fill-color: var(--text) !important; caret-color: var(--text) !important; }
[data-testid="stTextInput"] > div > div, [data-testid="stNumberInput"] > div > div, [data-testid="stTextArea"] > div > div,
[data-testid="stTextInput"] [data-baseweb="input"], [data-testid="stNumberInput"] [data-baseweb="input"],
[data-testid="stTextArea"] [data-baseweb="textarea"] { background: var(--surface-alt) !important; border-color: var(--border) !important; border-radius: 8px !important; }
[data-testid="stNumberInput"] button { background: var(--surface-alt) !important; color: var(--text) !important; border-color: var(--border) !important; }
::placeholder { color: var(--muted) !important; -webkit-text-fill-color: var(--muted) !important; opacity: 0.85; }

/* ---- select box (document picker) ---- */
[data-baseweb="select"] div { background-color: transparent !important; }
[data-baseweb="select"] > div { background-color: var(--surface-alt) !important; border: 1px solid var(--border) !important; border-radius: 10px !important; }
[data-baseweb="select"] *, [data-baseweb="select"] input { color: var(--text) !important; fill: var(--text) !important; -webkit-text-fill-color: var(--text) !important; }
[data-baseweb="popover"], [data-baseweb="popover"] > div, [data-baseweb="popover"] ul, [data-baseweb="menu"], [data-testid="stSelectboxVirtualDropdown"] {
    background: var(--surface) !important; border-radius: 10px !important; }
[data-baseweb="popover"] *, [data-baseweb="menu"] * { color: var(--text) !important; }
[data-baseweb="menu"] li, [data-testid="stSelectboxVirtualDropdown"] li { background: transparent !important; }
[data-baseweb="menu"] li:hover, [data-baseweb="menu"] [aria-selected="true"], [data-testid="stSelectboxVirtualDropdown"] li:hover { background: var(--accent-soft) !important; }
[data-baseweb="tooltip"] > div, [data-testid="stTooltipContent"] { background: var(--surface) !important; color: var(--text) !important; border: 1px solid var(--border); }

/* ---- buttons ---- */
.stButton > button, [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-minimal"],
[data-testid="stDownloadButton"] button, [data-testid="stBaseButton-secondaryFormSubmit"] {
    background: var(--surface) !important; color: var(--text) !important; border: 1px solid var(--border-strong) !important;
    border-radius: 10px !important; font-weight: 500 !important; transition: all .15s ease; }
.stButton > button:hover, [data-testid="stBaseButton-secondary"]:hover, [data-testid="stDownloadButton"] button:hover {
    border-color: var(--accent) !important; background: var(--accent-soft) !important; color: var(--accent-text) !important; }
.stButton > button *, [data-testid="stDownloadButton"] button * { color: inherit !important; }
.stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"],
[data-testid="stDownloadButton"] button[kind="primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
    background: var(--primary-bg) !important; color: var(--primary-fg) !important; border: 1px solid var(--primary-bg) !important;
    border-radius: 10px !important; font-weight: 600 !important; box-shadow: var(--shadow); }
.stButton > button[kind="primary"] *, .stButton > button[data-testid="stBaseButton-primary"] *,
[data-testid="stDownloadButton"] button[kind="primary"] *, button[data-testid="stBaseButton-primaryFormSubmit"] * { color: var(--primary-fg) !important; }
.stButton > button[kind="primary"]:hover, .stButton > button[data-testid="stBaseButton-primary"]:hover,
[data-testid="stDownloadButton"] button[kind="primary"]:hover {
    background: var(--primary-bg) !important; color: var(--primary-fg) !important; filter: brightness(1.1); }

/* ---- file uploader ---- */
[data-testid="stFileUploader"] [data-testid^="stFile"] { background: var(--surface-alt) !important; }
[data-testid="stFileUploaderDropzone"] { background: var(--surface-alt) !important; border: 2px dashed var(--border-strong) !important; border-radius: 14px !important; }
[data-testid="stFileUploaderDropzone"] *, [data-testid="stFileUploader"] small, [data-testid="stFileUploader"] span { color: var(--text) !important; }
[data-testid="stFileUploaderDropzone"] button { background: var(--surface) !important; border: 1px solid var(--border-strong) !important; border-radius: 8px !important; }
[data-testid="stFileUploaderFile"], [data-testid="stFileChip"] { background: var(--surface-alt) !important; border: 1px solid var(--border) !important; border-radius: 10px !important; }
[data-testid="stFileUploaderFile"] *, [data-testid="stFileChip"] * { color: var(--text) !important; }
[data-testid="stFileUploaderFile"] svg, [data-testid="stFileUploaderDeleteBtn"] svg { fill: var(--text) !important; color: var(--text) !important; }
[data-testid="stFileUploaderFileData"], [data-testid="stFileUploaderPagination"], [data-testid="stFileUploaderPagination"] * { background: transparent !important; }
[data-testid="stFileUploader"] > section, [data-testid="stFileUploader"] section > div { background: transparent; }

/* ---- tabs ---- */
[data-baseweb="tabs"], [data-baseweb="tab-list"], [data-baseweb="tab-panel"] { background: transparent !important; }
[data-baseweb="tab-list"]::before, [data-baseweb="tab-list"]::after { display: none !important; }
[data-baseweb="tab-list"] button { background: transparent !important; }
[data-baseweb="tab"] p, [data-baseweb="tab"] { color: var(--muted) !important; font-weight: 500; }
[data-baseweb="tab"][aria-selected="true"] p, [data-baseweb="tab"][aria-selected="true"] { color: var(--accent-text) !important; font-weight: 700; }
[data-baseweb="tab-highlight"] { background-color: var(--accent) !important; }
[data-baseweb="tab-border"] { background-color: var(--border) !important; }

/* ---- alerts ---- */
[data-testid="stAlert"] { background: var(--info-bg) !important; border: 1px solid var(--info-bd) !important; border-left: 5px solid var(--info-bd) !important; border-radius: 12px !important; }
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) { background: var(--ok-bg) !important; border-color: var(--ok-bd) !important; }
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) { background: var(--warn-bg) !important; border-color: var(--warn-bd) !important; }
[data-testid="stAlert"]:has([data-testid="stAlertContentError"]) { background: var(--err-bg) !important; border-color: var(--err-bd) !important; }
[data-testid="stAlert"] *, [data-testid="stNotification"] * { color: var(--text) !important; }

/* ---- code / text ---- */
[data-testid="stText"], [data-testid="stCode"], [data-testid="stCode"] pre, pre, code { background: var(--surface-alt) !important; color: var(--text) !important; border-radius: 8px; }
[data-testid="stMarkdownContainer"] table, [data-testid="stMarkdownContainer"] th, [data-testid="stMarkdownContainer"] td { color: var(--text) !important; border-color: var(--border) !important; }
[data-testid="stMarkdownContainer"] th { background: var(--surface-alt) !important; }

/* ---- chat ---- */
[data-testid="stChatMessage"] { background: var(--surface-alt) !important; border: 1px solid var(--border) !important; border-radius: 14px !important; }
[data-testid="stChatMessage"] * { color: var(--text) !important; }
[data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] { background: var(--bg) !important; }
[data-testid="stChatInput"], [data-testid="stChatInput"] > div, [data-testid="stChatInput"] [data-baseweb="textarea"] { background: var(--surface-alt) !important; border-color: var(--border-strong) !important; border-radius: 12px !important; }
[data-testid="stChatInput"] textarea { color: var(--text) !important; -webkit-text-fill-color: var(--text) !important; }

/* ---- misc ---- */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
[data-testid="stRadio"] [role="radiogroup"] * { color: var(--text) !important; }
[data-testid="stSpinner"] * { color: var(--text) !important; }
[data-testid="stProgress"] p { color: var(--muted) !important; }
[data-testid="stProgressBarTrack"] { background-color: var(--surface-alt) !important; border: 1px solid var(--border); }
[data-testid="stProgressBarTrack"] > div { background-color: var(--accent) !important; }
[data-testid="stToggle"] p, [data-testid="stCheckbox"] p { color: var(--text) !important; }
[data-testid="stAudio"] audio { width: 100%; }

@media (max-width: 700px) { .hero { padding: 16px; } .hero h1 { font-size: 1.25rem; } }
"""

st.markdown(f"<style>{css_vars}{STATIC_CSS}[data-testid='stDataFrame'], [data-testid='stDataEditor'] {{ {grid_filter} }}</style>", unsafe_allow_html=True)

# ---- top bar: title + theme switch ----
col_top_header, col_top_theme = st.columns([4.2, 1], vertical_alignment="center")

with col_top_header:
    st.markdown("""
    <div class="hero">
        <h1>📑 ThaiDocAI · ตรวจเอกสารและยอดชำระอัจฉริยะ</h1>
        <p>อ่านใบเสร็จและสลิป ตรวจทานตัวเลข ถาม-ตอบทั้งชุด และส่งออกข้อมูลสำหรับทำบัญชี</p>
        <div class="hero-steps">
            <span class="hero-step">① อัปโหลดภาพ</span>
            <span class="hero-step">② ตรวจและแก้ข้อมูล</span>
            <span class="hero-step">③ ยืนยันและส่งออก</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col_top_theme:
    with st.container(border=True):
        dark_on = st.toggle("🌙 โหมดมืด", value=is_dark_mode, key="theme_toggle")
        new_mode = "🌙 กลางคืน" if dark_on else "☀️ สว่าง"
        if new_mode != st.session_state.theme_mode:
            st.session_state.theme_mode = new_mode
            st.rerun()

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

# ==================== Sidebar เมนูด้านข้าง ====================
with st.sidebar:
    st.title("ThaiDocAI")
    st.caption("พื้นที่ทำงานเอกสารอัจฉริยะ")
    selected_model_name = api_service.PRIMARY_MODEL_NAME
    selected_model_id = api_service.PRIMARY_MODEL_ID
    voice_gender = st.session_state.get("voice_selection", "หญิง (Female)")
    with st.expander("การตั้งค่าเพิ่มเติม", expanded=False):
        voice_gender = st.radio(
            "เสียงอ่านผล",
            ["หญิง (Female)", "ชาย (Male)"],
            index=0,
            key="voice_selection",
        )
    voice_mode = "female" if "หญิง" in voice_gender else "male"

    if st.button("เริ่มเอกสารใหม่ทั้งหมด", width="stretch"):
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

# ==================== Main Workspace แบ่ง 2 ส่วน ====================
col_upload, col_display = st.columns([1, 1.25], gap="large")

with col_upload:
    st.subheader("1 · เพิ่มเอกสาร")
    st.caption("📁 อัปโหลดได้หลายภาพพร้อมกัน (JPG/PNG) · ประมวลผลแบบขนาน · ภาพถูกส่งไปประมวลผลผ่าน ThaiLLM API และแอปไม่เก็บประวัติถาวร")

    uploaded_files = st.file_uploader(
        "เลือกหรือลากวางรูปใบเสร็จ/สลิป (เลือกได้หลายภาพพร้อมกัน)",
        type=["jpg", "png", "jpeg"],
        accept_multiple_files=True,
        key=f"document_upload_{st.session_state.upload_revision}",
        help="สามารถกด Ctrl/Shift เพื่อเลือกหลายรูปพร้อมกัน หรือลากไฟล์หลายๆ รูปมาวางในกรอบนี้ได้เลยครับ",
    )
    
    if uploaded_files:
        st.success(f"📋 เลือกเอกสารแล้ว {len(uploaded_files)} ภาพ · พร้อมประมวลผลแบบขนาน")
        with st.expander("ดูตัวอย่างภาพที่เลือกทั้งหมด", expanded=len(uploaded_files) <= 3):
            preview_columns = st.columns(min(3, len(uploaded_files)))
            for file_index, uploaded_file in enumerate(uploaded_files):
                with preview_columns[file_index % len(preview_columns)]:
                    st.image(uploaded_file, caption=uploaded_file.name, width="stretch")
        
        btn_scan = st.button(
            f"🚀 เริ่มประมวลผล {len(uploaded_files)} ภาพพร้อมกัน (ความเร็วสูง)",
            type="primary",
            width="stretch",
        )
        
        if btn_scan:
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

                st.session_state.batch_sources = {i: item for i, item in enumerate(batch_inputs)}
                progress_bar = st.progress(0.0, text=f"เสร็จแล้ว 0/{len(batch_inputs)} ภาพ")

                def _on_progress(done, total):
                    progress_bar.progress(done / total, text=f"เสร็จแล้ว {done}/{total} ภาพ")

                batch_started = time.perf_counter()
                batch_results = api_service.extract_documents_batch(
                    batch_inputs, max_workers=6, progress_callback=_on_progress
                )
                progress_bar.empty()
                batch_elapsed = time.perf_counter() - batch_started
                for result in batch_results:
                    result["sentiment_result"] = None
                    result["verified"] = False
                st.session_state.scan_results = batch_results
                st.session_state.last_batch_elapsed = batch_elapsed
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
                )
                failed_results = [result for result in batch_results if not result.get("success")]
                for failed in failed_results:
                    st.warning(f"{failed.get('file_name', 'เอกสาร')}: {failed.get('error', 'ประมวลผลไม่สำเร็จ')}")
                    if failed.get("raw_content"):
                        with st.expander(f"ดูคำตอบดิบจากโมเดล · {failed.get('file_name', '')}"):
                            st.text(failed.get("raw_content"))

    # ---- retry only the images that failed (works across reruns) ----
    _sources = st.session_state.get("batch_sources", {})
    _failed_idx = [
        i for i, r in enumerate(st.session_state.scan_results)
        if not r.get("success") and i in _sources
    ]
    _notice = st.session_state.pop("retry_notice", None)
    if _notice:
        st.info(_notice)
    if _failed_idx:
        st.error(f"❌ ประมวลผลไม่สำเร็จ {len(_failed_idx)} ภาพ")
        with st.expander("ดูรายการที่ล้มเหลวและสาเหตุ", expanded=False):
            for i in _failed_idx:
                r = st.session_state.scan_results[i]
                st.caption(f"#{i + 1} {r.get('file_name', '')}: {r.get('error', 'ประมวลผลไม่สำเร็จ')}")
        if st.button(
            f"🔁 ประมวลผลซ้ำเฉพาะ {len(_failed_idx)} ภาพที่ล้มเหลว",
            type="primary",
            width="stretch",
            key="retry_failed_btn",
        ):
            retry_inputs = [_sources[i] for i in _failed_idx]
            retry_bar = st.progress(0.0, text=f"เสร็จแล้ว 0/{len(retry_inputs)} ภาพ")

            def _on_retry_progress(done, total):
                retry_bar.progress(done / total, text=f"เสร็จแล้ว {done}/{total} ภาพ")

            with st.spinner(f"กำลังประมวลผลซ้ำ {len(retry_inputs)} ภาพ..."):
                retry_results = api_service.extract_documents_batch(
                    retry_inputs, max_workers=2, progress_callback=_on_retry_progress, rescue=True
                )
            retry_bar.empty()
            recovered = sum(1 for r in retry_results if r.get("success"))
            st.session_state.retry_notice = (
                f"ประมวลผลซ้ำแล้ว: สำเร็จ {recovered}/{len(retry_results)} ภาพ"
                + ("" if recovered == len(retry_results) else " · ที่เหลือดูสาเหตุได้ในรายการที่ล้มเหลวด้านล่าง")
            )
            for i, new_result in zip(_failed_idx, retry_results):
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

with col_display:
    st.subheader("2 · ตรวจทานและจัดการผลลัพธ์")

    all_results = st.session_state.scan_results
    successful_documents = [
        index for index, result in enumerate(all_results)
        if result.get("success")
    ]

    # Batch Overview Section if results exist
    if all_results:
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

            b_m1, b_m2, b_m3 = st.columns(3)
            b_m1.metric("📄 จำนวนที่สแกน", f"{len(all_results)} ภาพ")
            b_m2.metric("✅ สำเร็จ", f"{len(successful_documents)} / {len(all_results)} ภาพ")
            b_m3.metric("💰 ยอดเงินรวมทุกใบเสร็จ", f"{total_sum:,.2f} บาท")

            # Build batch overview table
            batch_table_data = []
            export_rows = []  # same table with real numbers/dates for the .xlsx export
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

            # Consolidated Export Buttons for Batch
            if successful_documents:
                exp_col1, exp_col2, exp_col3 = st.columns(3)
                combined_csv_bytes = batch_df.to_csv(index=False).encode("utf-8-sig")
                exp_col1.download_button(
                    "📥 ตารางสรุป (CSV)",
                    data=combined_csv_bytes,
                    file_name="batch_documents_summary.csv",
                    mime="text/csv",
                    width="stretch",
                )
                exp_col3.download_button(
                    "📥 ตารางสรุป (Excel)",
                    data=build_batch_xlsx(export_rows),
                    file_name="batch_documents_summary.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                )
                combined_json = [r.get("data") for r in all_results if r.get("success")]
                exp_col2.download_button(
                    "📥 ข้อมูลรวม (JSON)",
                    data=json.dumps(combined_json, ensure_ascii=False, indent=2).encode("utf-8"),
                    file_name="batch_documents_data.json",
                    mime="application/json",
                    width="stretch",
                )

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
            format_func=lambda index: f"📄 #{index + 1}: {all_results[index].get('file_name', f'เอกสาร {index + 1}')} - {'✅ ยืนยันแล้ว' if all_results[index].get('verified') else '⏳ รอตรวจ'}",
            key="selected_document_picker",
            label_visibility="collapsed",
        )
        if selected_index != st.session_state.selected_document_index:
            st.session_state.chat_history = []
            st.session_state.compare_results = None
            st.session_state.tts_audio_url = None
        st.session_state.selected_document_index = selected_index
        st.session_state.scan_result = all_results[selected_index]
    
    if not st.session_state.scan_result:
        st.info("👈 กรุณาอัปโหลดรูปภาพและกด **'เริ่มประมวลผล'** เพื่อดูผลลัพธ์")
    else:
        res = st.session_state.scan_result
        doc_data = res.get("data")
        raw_content = res.get("raw_content", "")
        
        # แท็บแสดงผล 4 รูปแบบ
        tab1, tab2, tab3, tab4 = st.tabs([
            "📄 ตรวจ/ส่งออก",
            "🧠 วิเคราะห์ AI",
            "💬 ถาม-ตอบ",
            "⚙️ ตรวจยอด"
        ])
        
        # ------------------ Tab 1: ตารางและ Metric ------------------
        with tab1:
            if doc_data and isinstance(doc_data, dict):
                is_transfer_doc = (
                    doc_data.get("transfer_amount") is not None
                    or "สลิป" in str(doc_data.get("document_type", ""))
                    or "โอน" in str(doc_data.get("document_type", ""))
                )
                review_revision = st.session_state.get("review_revision", 0)
                if res.get("verified"):
                    st.success("ยืนยันข้อมูลฉบับนี้แล้ว · พร้อมส่งออก")
                else:
                    st.warning("รอตรวจทาน: เทียบยอดและรายละเอียดกับภาพก่อนยืนยัน")

                st.markdown("#### ตรวจและแก้ข้อมูลที่อ่านได้")
                st.caption("แก้ช่องที่ไม่ตรงกับภาพได้ก่อนบันทึก การยืนยันนี้เป็นการตรวจโดยผู้ใช้ ไม่ใช่การรับรองจากธนาคาร")
                # Include the document index so each document in a batch gets its own
                # widget state; otherwise switching documents without a fresh scan
                # reuses the same key and shows stale edits from another document.
                review_key = f"{review_revision}_{st.session_state.selected_document_index}"
                with st.form(f"review_document_{review_key}"):
                    identity_cols = st.columns([1.5, 1, 1])
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
                        st.markdown("##### รายการสินค้า/บริการ")
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

                    confirmed = st.form_submit_button("บันทึกการตรวจทานและยืนยัน", type="primary", width="stretch")

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
                        st.session_state.scan_result = res
                        if st.session_state.scan_results:
                            st.session_state.scan_results[st.session_state.selected_document_index] = res
                        st.session_state.chat_history = []
                        st.success("บันทึกและยืนยันข้อมูลแล้ว")
                        st.rerun()
                    except (TypeError, ValueError) as error:
                        st.error(f"บันทึกไม่ได้: {error}")

                # แถบแสดง Metric Card
                m1, m2, m3 = st.columns(3)
                m1.metric("🏢 ร้านค้า / แหล่งที่มา", doc_data.get("store_name") or "ไม่ระบุ")
                m2.metric("📅 วันที่", doc_data.get("date") or "ไม่ระบุ")
                transfer_amount = doc_data.get("transfer_amount")
                total_value = transfer_amount if transfer_amount is not None else doc_data.get("total")
                total_display = (
                    f"{float(total_value):,.2f} บาท"
                    if total_value is not None and total_value != ""
                    else "อ่านยอดไม่ได้"
                )
                amount_label = "💸 ยอดโอน" if transfer_amount is not None else "💰 ยอดสุทธิ (Total)"
                m3.metric(amount_label, total_display)
                for check_warning in doc_data.get("check_warnings") or []:
                    st.warning(check_warning)
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

                st.markdown("##### ส่งออกข้อมูล")
                if res.get("verified"):
                    export_cols = st.columns(2)
                    json_str = json.dumps(doc_data, ensure_ascii=False, indent=2)
                    export_cols[0].download_button(
                        label="ดาวน์โหลดเอกสารที่ยืนยันแล้ว (JSON)",
                        data=json_str.encode("utf-8"),
                        file_name=f"document_{doc_data.get('receipt_no') or 'verified'}.json",
                        mime="application/json",
                        width="stretch",
                    )
                    if items:
                        export_cols[1].download_button(
                            label="ดาวน์โหลดรายการเพื่อนำเข้าบัญชี (CSV)",
                            data=df.to_csv(index=False).encode("utf-8-sig"),
                            file_name=f"items_{doc_data.get('receipt_no') or 'verified'}.csv",
                            mime="text/csv",
                            width="stretch",
                        )
                else:
                    st.caption("ยืนยันการตรวจทานก่อนดาวน์โหลด เพื่อแยกข้อมูลที่ AI อ่านออกจากข้อมูลที่ตรวจแล้ว")
                
                # แสดงข้อความสรุปภาษาไทย
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
                
        # ------------------ Tab 2: วิเคราะห์ธุรกิจ & ภาษี AI (AI Business, Tax & Risk Analytics) ------------------
        with tab2:
            st.markdown("#### 🧠 วิเคราะห์ข้อมูลธุรกิจและภาษีอัจฉริยะ (AI Business & Tax Intelligence)")
            st.caption("ระบบวิเคราะห์อัตโนมัติ: จัดผังบัญชี ตรวจสอบเกณฑ์ภาษีสรรพากร และตรวจจับความเสี่ยงทุจริตในบิล")
            
            bi_res = api_service.analyze_document_business_intelligence(doc_data, raw_content)
            cat_info = bi_res["expense_category"]
            tax_info = bi_res["tax_compliance"]
            fraud_info = bi_res["fraud_anomaly"]
            exec_info = bi_res["executive_insights"]

            # Row 1: Category & Tax Compliance
            c_cat, c_tax = st.columns(2)
            with c_cat:
                with st.container(border=True):
                    st.markdown("##### 🏷️ จัดหมวดหมู่ค่าใช้จ่าย & ผังบัญชี (Account Code)")
                    st.markdown(f"**หมวดหมู่:** `{cat_info['name']}`")
                    st.markdown(f"**รหัสบัญชีแนะนำ:** <span style='font-size:1.2rem; font-weight:700; color:#D8A447;'>{cat_info['code']}</span>", unsafe_allow_html=True)
                    st.caption(f"ระดับความมั่นใจ: {cat_info['confidence']} · {cat_info['reason']}")
                    st.text_area(
                        "ข้อความบันทึกสมุดรายวัน (Journal Entry Narration):",
                        value=cat_info['narration'],
                        height=68,
                        help="สามารถคัดลอกข้อความนี้ไปลงสมุดรายวันทั่วไปในโปรแกรมบัญชีได้ทันที"
                    )

            with c_tax:
                with st.container(border=True):
                    st.markdown("##### 📋 การประเมินสิทธิ์ภาษี & การเบิกจ่าย (Tax Compliance)")
                    st.markdown(f"**ประเภทเอกสาร:** {tax_info['doc_type']}")
                    st.markdown(f"**เลขประจำตัวผู้เสียภาษี 13 หลัก:** `{tax_info['tax_id']}`")
                    st.markdown(f"**สิทธิ์เคลมภาษีซื้อ (VAT):** {tax_info['claimable']}")
                    st.markdown(f"**สถานะการเบิกจ่าย:** **{tax_info['status']}**")
                    st.caption(tax_info['notes'])

            # Row 2: Fraud Risk & Anomaly Detection
            with st.container(border=True):
                st.markdown("##### 🛡️ ระบบตรวจจับความผิดปกติและความเสี่ยงทุจริต (Fraud & Anomaly Detection)")
                r_col1, r_col2 = st.columns([1, 2.5])
                with r_col1:
                    st.metric("ระดับความเสี่ยง (Risk Level)", fraud_info["level"], delta=f"Risk Score: {fraud_info['score']}/100", delta_color="inverse" if fraud_info['score'] > 20 else "normal")
                with r_col2:
                    st.markdown("**ผลการตรวจสอบความเสี่ยง (Audit Checklist):**")
                    for chk in fraud_info["checks"]:
                        st.markdown(f"- {chk}")

            # Row 3: Executive Summary & Cost-Saving Tips
            with st.container(border=True):
                st.markdown("##### 💡 บทสรุปสำหรับผู้บริหารและคำแนะนำ (Executive Insights)")
                st.info(exec_info["summary"])
                for rec in exec_info["recommendations"]:
                    st.markdown(rec)

            # Multi-document Portfolio Overview (If batch mode)
            if len(successful_documents) > 1:
                st.markdown("---")
                st.markdown("#### 📊 ภาพรวมชุดเอกสารทั้งหมด (Batch Portfolio Analytics)")
                batch_portfolio = api_service.analyze_batch_portfolio(all_results)
                if batch_portfolio:
                    bp1, bp2, bp3 = st.columns(3)
                    bp1.metric("💰 ยอดใช้จ่ายรวมทั้งชุด", f"{batch_portfolio['total_spending']:,.2f} บาท")
                    bp2.metric("🧾 ยอดภาษีซื้อรวม (VAT)", f"{batch_portfolio['total_vat']:,.2f} บาท")
                    bp3.metric("✅ ภาษีซื้อที่เคลมได้", f"{batch_portfolio['claimable_vat']:,.2f} บาท")

                    # Duplicates Warning
                    if batch_portfolio["duplicates"]:
                        st.error(f"🚨 **ตรวจพบความเสี่ยงเอกสารซ้ำซ้อนในชุด {len(batch_portfolio['duplicates'])} รายการ!**")
                        for dup in batch_portfolio["duplicates"]:
                            st.warning(f"**{dup['type']}:** {dup['detail']}")
                    else:
                        st.success("✅ ไม่พบเอกสารซ้ำซ้อนหรือยอดซ้ำในชุดเอกสารนี้")

                    # Category Breakdown table
                    st.markdown("**สัดส่วนค่าใช้จ่ายตามหมวดหมู่ในชุดนี้:**")
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

        # ------------------ Tab 3: ถาม-ตอบอัจฉริยะ (Chat Q&A) ------------------
        with tab3:
            st.markdown("#### ถามข้อมูลจากเอกสาร (Smart Document Q&A)")
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
                    st.caption("ยังไม่มีบทสนทนา กดคำถามด่วนด้านบนหรือพิมพ์คำถามได้เลยครับ")
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

        # ------------------ Tab 4: ตรวจสอบยอด & ตัวช่วยเสริม (Audit & Accessibility) ------------------
        with tab4:
            st.markdown("#### ตรวจสอบความสอดคล้องของสมการยอดเงิน (Financial Audit)")
            st.caption("ระบบตรวจเฉพาะสมการที่มีตัวเลขครบ หากข้อมูลบางส่วนอ่านไม่ได้จะแจ้งว่าต้องตรวจเพิ่ม")
            
            audit = api_service.audit_financials(doc_data)
            if audit["status"] == "passed":
                st.success(audit["msg"])
            elif audit["status"] == "warning":
                st.warning(audit["msg"])
            else:
                st.info(audit["msg"])
                
            st.divider()
            st.markdown("#### 🎧 สังเคราะห์เสียงอ่านสรุปเอกสาร (Vaja Text-to-Speech)")
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
            st.markdown("#### 📊 วิเคราะห์โทนข้อความเอกสาร (SSense Sentiment Analysis)")
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