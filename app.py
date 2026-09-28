# pyrefly: ignore [missing-import]
import streamlit as st
# pyrefly: ignore [missing-import]
from PIL import Image
import pandas as pd
import json
import html
import time
import api_service


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
    st.session_state.theme_mode = "🌙 กลางคืน"
is_dark_mode = "สว่าง" not in str(st.session_state.theme_mode)

theme_colors = {
    "main_bg": "#111815" if is_dark_mode else "#F8FAF8",
    "main_text": "#E6ECE7" if is_dark_mode else "#142820",
    "sidebar_bg": "#18221E" if is_dark_mode else "#EDF3EE",
    "surface": "#202C27" if is_dark_mode else "#FFFFFF",
    "surface_alt": "#26342E" if is_dark_mode else "#F2F7F4",
    "border": "#3A4941" if is_dark_mode else "#D1DDD5",
    "muted": "#B8C4BD" if is_dark_mode else "#52665C",
    "header_bg": (
        "linear-gradient(135deg, #16241E 0%, #1F3229 100%)"
        if is_dark_mode
        else "linear-gradient(135deg, #FFFFFF 0%, #EEF6F1 100%)"
    ),
    "header_border": "#D8A447" if is_dark_mode else "#245647",
    "header_box_border": "#2D3E35" if is_dark_mode else "#C8D7CE",
    "header_title": "#F7F5EE" if is_dark_mode else "#112F24",
    "header_subtext": "#D0DED5" if is_dark_mode else "#3B574C",
    "workflow_bg": "rgba(216, 164, 71, 0.12)" if is_dark_mode else "rgba(36, 86, 71, 0.08)",
    "workflow_color": "#F4D9A1" if is_dark_mode else "#194A3B",
    "workflow_border": "rgba(216, 164, 71, 0.28)" if is_dark_mode else "rgba(36, 86, 71, 0.22)",
}

# Styling for a document-review workbench with full dark/light mode responsiveness
st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"] {{ font-family: 'IBM Plex Sans Thai', sans-serif; }}
    .block-container {{ max-width: 1440px; padding-top: 1.2rem; }}
    
    /* Streamlit native header bug fix for Light Mode */
    header[data-testid="stHeader"], .stAppHeader {{
        background-color: {theme_colors['main_bg']} !important;
        color: {theme_colors['main_text']} !important;
    }}
    header[data-testid="stHeader"] button, 
    header[data-testid="stHeader"] svg,
    [data-testid="stSidebarCollapseButton"] button {{
        color: {theme_colors['main_text']} !important;
        fill: {theme_colors['main_text']} !important;
    }}
    [data-testid="stDecoration"] {{
        background-image: linear-gradient(90deg, #245647, {theme_colors['header_border']}) !important;
    }}
    [data-testid="stToolbar"] {{
        color: {theme_colors['main_text']} !important;
    }}
    
    .stApp {{ background: {theme_colors['main_bg']} !important; color: {theme_colors['main_text']} !important; }}
    [data-testid="stSidebar"] > div:first-child {{ background: {theme_colors['sidebar_bg']} !important; }}
    [data-testid="stWidgetLabel"] p, [data-testid="stMarkdownContainer"], label {{ color: {theme_colors['main_text']} !important; }}
    [data-testid="stCaptionContainer"] {{ color: {theme_colors['muted']} !important; }}
    [data-testid="stMetric"] {{ 
        background: {theme_colors['surface']} !important; 
        color: {theme_colors['main_text']} !important; 
        padding: 12px 14px !important; 
        border-radius: 8px !important; 
        border: 1px solid {theme_colors['border']} !important;
    }}
    [data-testid="stMetricLabel"] p {{ color: {theme_colors['muted']} !important; font-size: 0.88rem !important; }}
    [data-testid="stMetricValue"] {{ color: {theme_colors['main_text']} !important; font-weight: 700 !important; }}
    
    div[data-testid="stForm"] {{ background: {theme_colors['surface']}; border: 1px solid {theme_colors['border']}; border-radius: 10px; padding: 16px; }}
    [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input {{ 
        background: {theme_colors['surface_alt']} !important; 
        color: {theme_colors['main_text']} !important; 
        border-color: {theme_colors['border']} !important; 
    }}
    [data-testid="stDataFrame"] {{ border-color: {theme_colors['border']}; border-radius: 8px; overflow: hidden; }}
    [data-testid="stRadio"] label {{ color: {theme_colors['main_text']} !important; }}
    [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-minimal"], .stButton > button {{
        background: {theme_colors['surface_alt']} !important; 
        color: {theme_colors['main_text']} !important;
        border: 1px solid {theme_colors['border']} !important;
        border-radius: 6px !important;
    }}
    [data-testid="stBaseButton-primary"] {{ 
        background: #245647 !important; 
        color: #FFFFFF !important; 
        border: 1px solid #1c4538 !important; 
        font-weight: 600 !important;
    }}
    [data-testid="stFileUploaderDropzone"] {{ 
        background: {theme_colors['surface']} !important; 
        border: 2px dashed {theme_colors['border']} !important; 
        border-radius: 10px !important;
    }}
    [data-testid="stFileUploaderDropzone"] *, [data-testid="stFileUploaderDropzone"] p {{ color: {theme_colors['main_text']} !important; }}
    [data-testid="stExpander"] {{ 
        background: {theme_colors['surface']} !important; 
        border: 1px solid {theme_colors['border']} !important; 
        border-radius: 8px !important;
    }}
    /* Selectbox styling for full dark/light consistency */
    div[data-baseweb="select"] > div {{ 
        background-color: {theme_colors['surface_alt']} !important; 
        color: {theme_colors['main_text']} !important; 
        border: 1px solid {theme_colors['border']} !important; 
        border-radius: 8px !important;
    }}
    div[data-baseweb="select"] * {{ 
        color: {theme_colors['main_text']} !important; 
        fill: {theme_colors['main_text']} !important; 
    }}
    div[data-baseweb="popover"], div[data-baseweb="menu"], ul[data-testid="stSelectboxVirtualDropdown"] {{ 
        background-color: {theme_colors['surface']} !important; 
        border: 1px solid {theme_colors['border']} !important; 
        border-radius: 8px !important; 
    }}
    div[data-baseweb="menu"] li, ul[data-testid="stSelectboxVirtualDropdown"] li {{ 
        color: {theme_colors['main_text']} !important; 
        background-color: transparent !important; 
    }}
    div[data-baseweb="menu"] li:hover, ul[data-testid="stSelectboxVirtualDropdown"] li:hover {{ 
        background-color: {theme_colors['surface_alt']} !important; 
    }}
    [data-testid="stVerticalBlockBorderWrapper"] {{ 
        border-color: {theme_colors['border']} !important; 
        background-color: {theme_colors['surface']} !important; 
        border-radius: 10px !important; 
    }}
    
    /* Top Header Bar styling */
    .main-header {{ 
        background: {theme_colors['header_bg']}; 
        padding: 18px 22px; 
        border-radius: 10px; 
        color: {theme_colors['header_title']}; 
        border: 1px solid {theme_colors['header_box_border']}; 
        border-left: 6px solid {theme_colors['header_border']}; 
        box-shadow: {'0 4px 20px rgba(0,0,0,0.22)' if is_dark_mode else '0 2px 12px rgba(36,86,71,0.06)'}; 
        margin-bottom: 12px; 
    }}
    .main-header h1 {{ 
        color: {theme_colors['header_title']} !important; 
        font-size: 1.55rem; 
        font-weight: 700; 
        margin: 0 0 6px 0; 
    }}
    .main-header p {{ 
        color: {theme_colors['header_subtext']} !important; 
        font-size: 0.95rem; 
        margin: 0; 
    }}
    .workflow-hint {{ 
        display: flex; 
        flex-wrap: wrap; 
        gap: 8px 12px; 
        margin-top: 12px; 
    }}
    .workflow-badge-step {{ 
        display: inline-flex; 
        align-items: center; 
        padding: 3px 10px; 
        border-radius: 16px; 
        font-size: 0.82rem; 
        font-weight: 600; 
        background: {theme_colors['workflow_bg']}; 
        color: {theme_colors['workflow_color']}; 
        border: 1px solid {theme_colors['workflow_border']}; 
    }}
    .batch-summary-box {{ 
        background: {theme_colors['surface']}; 
        border: 1px solid {theme_colors['border']}; 
        border-radius: 10px; 
        padding: 16px; 
        margin-bottom: 18px; 
    }}
    .benchmark-box {{ 
        background-color: {theme_colors['surface']}; 
        border: 1px solid {theme_colors['border']}; 
        border-radius: 8px; 
        padding: 14px; 
        height: 380px; 
        overflow-y: auto; 
        font-size: 0.95rem; 
        line-height: 1.6; 
    }}
    .benchmark-header {{ 
        font-weight: 700; 
        color: {theme_colors['main_text']}; 
        font-size: 1.05rem; 
        margin-bottom: 6px; 
    }}
    .benchmark-badge {{ 
        display: inline-block; 
        background: {theme_colors['surface_alt']}; 
        color: {theme_colors['main_text']}; 
        padding: 2px 8px; 
        border-radius: 12px; 
        font-size: 0.8rem; 
        font-weight: 600; 
        margin-bottom: 8px; 
    }}
    @media (max-width: 700px) {{ 
        .main-header {{ padding: 14px; }}
        .main-header h1 {{ font-size: 1.3rem; }}
    }}
</style>
""", unsafe_allow_html=True)

# Top Bar: Main Title on Left + Dropdown for Theme Selection on Right
col_top_header, col_top_theme = st.columns([3.8, 1.2], vertical_alignment="center")

with col_top_header:
    st.markdown("""
    <div class="main-header">
        <h1>📑 ThaiDocAI · ตรวจเอกสารและยอดชำระอัจฉริยะ</h1>
        <p>อ่านใบเสร็จและสลิป ตรวจทานตัวเลข ตรวจสมการยอด และส่งออกข้อมูลสำหรับทำบัญชี (รองรับประมวลผลเป็นชุด)</p>
        <div class="workflow-hint">
            <span class="workflow-badge-step">1 · อัปโหลดภาพ (เดี่ยว / หลายภาพ)</span>
            <span class="workflow-badge-step">2 · ตรวจและแก้ข้อมูล</span>
            <span class="workflow-badge-step">3 · ยืนยันและส่งออกชุดข้อมูล</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col_top_theme:
    with st.container(border=True):
        st.markdown("**🎨 โหมดธีมหน้าจอ (Theme)**")
        theme_choices = ["🌙 กลางคืน", "☀️ สว่าง"]
        active_idx = 0 if "กลางคืน" in st.session_state.theme_mode else 1
        selected_theme = st.selectbox(
            "ธีมหน้าจอ",
            theme_choices,
            index=active_idx,
            key="top_bar_theme_selector",
            label_visibility="collapsed",
            help="สลับระหว่างโหมดมืด (Dark Mode) และโหมดสว่าง (Light Mode)",
        )
        if selected_theme != st.session_state.theme_mode:
            st.session_state.theme_mode = selected_theme
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
        st.session_state.review_revision = st.session_state.get("review_revision", 0) + 1
        st.session_state.upload_revision += 1
        st.rerun()

# ==================== Main Workspace แบ่ง 2 ส่วน ====================
col_upload, col_display = st.columns([1, 1.25], gap="large")

with col_upload:
    st.subheader("1 · เพิ่มเอกสาร")
    st.caption("📁 **ระบบรองรับการอัปโหลดหลายภาพพร้อมกัน (Batch Multi-Upload)** · รองรับ JPG/PNG")
    st.caption("⚡ **ประมวลผลความเร็วสูง (< 3 วินาที/ภาพ)**: ระบบจะย่อขนาดและส่งประมวลผลแบบขนานอัตโนมัติ")
    st.caption("ความเป็นส่วนตัว: ภาพจะถูกส่งไปประมวลผลผ่าน ThaiLLM API · แอปไม่เก็บประวัติถาวร ให้ดาวน์โหลด JSON/CSV หลังยืนยัน")

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
            with st.spinner(f"⚡ กำลังประมวลผล {len(uploaded_files)} ภาพพร้อมกันด้วย AI ความเร็วสูง (< 3 วิ/ภาพ)..."):
                st.session_state.scan_result = None
                batch_inputs = []
                for uploaded_file in uploaded_files:
                    uploaded_file.seek(0)
                    batch_inputs.append((
                        uploaded_file.name,
                        uploaded_file.read(),
                        uploaded_file.type or "image/jpeg",
                    ))

                batch_started = time.perf_counter()
                batch_results = api_service.extract_documents_batch(batch_inputs, max_workers=5)
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
                    batch_table_data.append({
                        "ลำดับ": idx + 1,
                        "ชื่อไฟล์": fname,
                        "ประเภท": doc_type,
                        "ร้านค้า / ผู้รับ": store,
                        "ผู้จ่ายเงิน / ผู้โอน": payer,
                        "วันที่": dt,
                        "ยอดเงิน (บาท)": amt_str,
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
                        "สถานะ": "❌ ล้มเหลว",
                    })

            batch_df = pd.DataFrame(batch_table_data)
            st.dataframe(batch_df, width="stretch", hide_index=True)

            # Consolidated Export Buttons for Batch
            if successful_documents:
                exp_col1, exp_col2 = st.columns(2)
                combined_csv_bytes = batch_df.to_csv(index=False).encode("utf-8-sig")
                exp_col1.download_button(
                    "📥 ดาวน์โหลดตารางสรุปทุกเอกสาร (CSV)",
                    data=combined_csv_bytes,
                    file_name="batch_documents_summary.csv",
                    mime="text/csv",
                    width="stretch",
                )
                combined_json = [r.get("data") for r in all_results if r.get("success")]
                exp_col2.download_button(
                    "📥 ดาวน์โหลดข้อมูลรวมทุกเอกสาร (JSON)",
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
            "ตรวจเอกสารและส่งออก",
            "ตรวจยอด",
            "ถามเอกสาร",
            "เครื่องมือเพิ่มเติม"
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
                
            with st.expander("ตัวเลือกเสริม · ฟังเสียงอ่านผล"):
                st.caption(f"เสียง: {voice_gender}")
                if st.button("สร้างเสียงอ่านสรุป", disabled=not api_service.AIFORTHAI_APIKEY):
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
                    st.caption("ยังไม่ได้สร้างเสียงอ่านผล")

        # ------------------ Tab 2: ตรวจสอบความถูกต้องทางการเงิน (Audit) ------------------
        with tab2:
            st.markdown("#### ตรวจความสอดคล้องของยอด")
            st.caption("ระบบตรวจเฉพาะสมการที่มีตัวเลขครบ หากข้อมูลบางส่วนอ่านไม่ได้จะแจ้งว่าต้องตรวจเพิ่ม")
            
            audit = api_service.audit_financials(doc_data)
            if audit["status"] == "passed":
                st.success(audit["msg"])
            elif audit["status"] == "warning":
                st.warning(audit["msg"])
            else:
                st.info(audit["msg"])
                
            # Optional sentiment analysis is run only on request.
            st.markdown("---")
            st.markdown("#### เครื่องมือเสริม: วิเคราะห์โทนข้อความ")
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

        # ------------------ Tab 3: ถาม-ตอบอัจฉริยะ (Chat Q&A) ------------------
        with tab3:
            st.markdown("#### ถามข้อมูลจากเอกสาร")
            st.caption(f"ใช้โมเดล {selected_model_name} · คำตอบเป็นข้อมูลช่วยตรวจทาน โปรดเทียบกับเอกสารต้นฉบับ")
            
            st.markdown("**💡 คำถามด่วน:**")
            qc1, qc2, qc3 = st.columns(3)
            
            context_to_send = json.dumps(doc_data, ensure_ascii=False) if doc_data else raw_content
            
            def submit_question(q_text):
                st.session_state.chat_history.append({"role": "user", "content": q_text})
                with st.spinner("🤖 AI กำลังค้นหาข้อมูลจากเอกสาร..."):
                    ans_obj = api_service.ask_document_qa(context_to_send, q_text, selected_model_id)
                    reply = ans_obj.get("answer") if ans_obj.get("success") else f"❌ {ans_obj.get('error')}"
                    st.session_state.chat_history.append({
                        "role": "assistant", 
                        "content": reply, 
                        "time": ans_obj.get("elapsed_time")
                    })
                st.rerun()

            if qc1.button("💰 สรุปยอดเงินและ VAT", width="stretch"):
                submit_question("สรุปยอดรวม ยอดก่อนภาษี และภาษีมูลค่าเพิ่ม (VAT) ของเอกสารนี้")
            if qc2.button("🧾 เลขที่และวันที่เอกสาร", width="stretch"):
                submit_question("เอกสารนี้ออกวันที่เท่าไหร่ มีเลขที่ใบเสร็จหรือเลขอ้างอิงอะไรบ้าง?")
            if qc3.button("📦 สินค้าราคาสูงสุด", width="stretch"):
                submit_question("ในรายการสินค้าทั้งหมด สินค้าชิ้นไหนราคาสูงที่สุด และคิดเป็นกี่บาท?")

            st.divider()
            
            # หน้าต่างแชต
            chat_box = st.container(height=350)
            with chat_box:
                if len(st.session_state.chat_history) == 0:
                    st.caption("ยังไม่มีบทสนทนา สามารถกดคำถามด่วนด้านบนหรือพิมพ์ถามด้านล่างได้เลยครับ")
                for msg in st.session_state.chat_history:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])
                        if "time" in msg and msg["time"]:
                            st.caption(f"⏱️ ประมวลผลใน {msg['time']} วินาที")

            user_query = st.chat_input("พิมพ์คำถามเกี่ยวกับเอกสาร เช่น 'มีส่วนลดหรือไม่?'")
            if user_query:
                submit_question(user_query)

        # ------------------ Tab 4: เปรียบเทียบโมเดล AI (Benchmarking พร้อม Scrollbox) ------------------
        with tab4:
            st.markdown("#### เปรียบเทียบโมเดลสำหรับการทดลอง")
            st.caption("เครื่องมือวิจัยเสริม: ส่งคำถามเดียวกันไปยัง 3 โมเดลและเปรียบเทียบคำตอบ/เวลา อาจใช้โควตา API เพิ่ม")
            
            test_question = st.text_input(
                "คำถามทดสอบเปรียบเทียบ:",
                value="สรุปสาระสำคัญของเอกสารนี้ พร้อมระบุยอดเงินที่ต้องชำระเป็นภาษาไทย"
            )

            if st.button("⚡ กดรันเปรียบเทียบ 3 โมเดลพร้อมกัน", type="secondary", width="stretch"):
                with st.spinner("กำลังส่งคำถามไปยัง OpenThaiGPT, Typhoon และ Pathumma..."):
                    context_bench = json.dumps(doc_data, ensure_ascii=False) if doc_data else raw_content
                    cmp_res = api_service.compare_models(context_bench, test_question)
                    st.session_state.compare_results = cmp_res
                    st.success("✅ ประมวลผลเปรียบเทียบเสร็จสิ้น!")

            if st.session_state.compare_results:
                cmp = st.session_state.compare_results
                b_cols = st.columns(3)
                
                idx = 0
                for model_label, res_data in cmp.items():
                    with b_cols[idx]:
                        st.markdown(f'<div class="benchmark-header">🤖 {model_label}</div>', unsafe_allow_html=True)
                        if res_data.get("success"):
                            st.markdown(f'<span class="benchmark-badge">⏱️ ความเร็ว: {res_data.get("elapsed_time")} วินาที</span>', unsafe_allow_html=True)
                            ans_html = html.escape(res_data.get("answer", "")).replace("\n", "<br>")
                            st.markdown(f'<div class="benchmark-box">{ans_html}</div>', unsafe_allow_html=True)
                        else:
                            st.error(f"เกิดข้อผิดพลาด: {res_data.get('error')}")
                    idx += 1