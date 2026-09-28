import base64
import datetime as _dt
import io
import json
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import requests
import soundfile as sf


from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Persistent HTTP session with connection pooling for sub-3-second API latency
_http_session = requests.Session()
_retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=_retries)
_http_session.mount("https://", _adapter)
_http_session.mount("http://", _adapter)


def _read_streamlit_secret(name):
    try:
        import streamlit as st

        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return ""


def _load_api_key(name):
    return os.getenv(name, "").strip() or _read_streamlit_secret(name)


AIFORTHAI_APIKEY = _load_api_key("AIFORTHAI_APIKEY")
THAILLM_APIKEY = _load_api_key("THAILLM_APIKEY")
TYPHOON_OCR_APIKEY = _load_api_key("TYPHOON_OCR_API_KEY")
TYPHOON_OCR_URL = "https://api.opentyphoon.ai/v1/chat/completions"

AVAILABLE_MODELS = {
    "OpenThaiGPT 8B": "OpenThaiGPT-ThaiLLM-8B-Instruct-v7.2",
    "Typhoon-S 8B": "Typhoon-S-ThaiLLM-8B-Instruct",
    "Pathumma (Reasoning 8B)": "Pathumma-ThaiLLM-qwen3-8b-think-3.0.0",
}
PRIMARY_MODEL_NAME = "Typhoon-S 8B"
PRIMARY_MODEL_ID = AVAILABLE_MODELS[PRIMARY_MODEL_NAME]


def clean_llm_response(text):
    if not text:
        return ""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>")[-1]
    if "Final Output Construction:" in cleaned:
        cleaned = cleaned.split("Final Output Construction:")[-1]
    return cleaned.strip()


def parse_json_object(text):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            value, _ = decoder.raw_decode(cleaned[match.start():])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return None


def is_ocr_meta_response(text):
    lowered = (text or "").lower()
    meta_phrases = (
        "the user wants me",
        "analyze the image",
        "let's look closer",
        "let me re-examine",
        "i'll focus on text",
        "looking at the image again",
    )
    return any(phrase in lowered for phrase in meta_phrases)


def summarize_document_data(data):
    transfer_amount = data.get("transfer_amount")
    if transfer_amount is not None:
        payer = str(data.get("payer_name") or "").strip()
        receiver = str(data.get("store_name") or "").strip()
        if payer and receiver:
            summary = f"โอนเงินจาก {payer} ถึง {receiver} "
        elif receiver:
            summary = f"โอนเงินถึง {receiver} "
        elif payer:
            summary = f"โอนเงินจาก {payer} "
        else:
            summary = ""
        summary += f"ยอดโอน {float(transfer_amount):,.2f} บาท"
        fee = data.get("fee")
        debited_total = data.get("debited_total")
        if fee is not None:
            summary += f" ค่าธรรมเนียม {float(fee):,.2f} บาท"
        if debited_total is not None:
            summary += f" ยอดหักบัญชีรวม {float(debited_total):,.2f} บาท"
        return summary

    total = data.get("total")
    if total is None:
        return "ไม่สามารถสกัดยอดเงินจากเอกสารได้ กรุณาตรวจข้อความ OCR และภาพต้นฉบับ"
    return f"ยอดสุทธิที่ต้องชำระ {float(total):,.2f} บาท"


def optimize_image_for_ocr(image_bytes, max_dim=1500, quality=92):
    """
    Optimizes and downscales images in-memory to guarantee sub-3-second OCR processing.
    Downscales large phone camera images (3-10MB) to a resolution that keeps small text
    (e.g. names, item names) legible, while still greatly reducing network upload
    payload and Vision model inference latency.
    """
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / float(max(w, h))
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, "image/jpeg"


def _extract_document_intelligence_once(optimized_mime, image_data, url, headers, output_schema, payload):
    started = time.perf_counter()
    try:
        response = _http_session.post(url, headers=headers, json=payload, timeout=40)
        elapsed = round(time.perf_counter() - started, 2)
        if response.status_code != 200:
            result = {"success": False, "error": f"Vision API HTTP {response.status_code}", "elapsed_time": elapsed}
            # Auth/permission errors won't change on retry.
            result["retryable"] = response.status_code not in (401, 403)
            return result

        answer = clean_llm_response(response.json()["choices"][0]["message"]["content"])
        finish_reason = response.json()["choices"][0].get("finish_reason")
        extracted = parse_json_object(answer)

        # Some model responses skip the {"raw_ocr":..., "data": {...}} wrapper and
        # return the receipt fields directly at the top level. Accept that shape too
        # instead of treating it as a schema failure.
        if isinstance(extracted, dict) and not isinstance(extracted.get("data"), dict):
            data_field_names = set(output_schema["data"].keys())
            if data_field_names & extracted.keys():
                extracted = {"raw_ocr": extracted.get("raw_ocr", ""), "data": extracted}

        if not extracted or not isinstance(extracted.get("data"), dict):
            error_msg = "โมเดลอ่านภาพแล้ว แต่คืนข้อมูลไม่ครบตาม schema จึงไม่แสดงยอดที่คาดเดา"
            if finish_reason == "length":
                error_msg += " (คำตอบถูกตัดก่อนจบ ลองใหม่อีกครั้งหรือใช้ภาพที่มีรายการน้อยลง)"
            return {
                "success": False,
                "error": error_msg,
                "raw_content": answer,
                "elapsed_time": elapsed,
                "retryable": True,
            }

        raw_ocr = str(extracted.get("raw_ocr") or "").strip()
        if is_ocr_meta_response(raw_ocr):
            return {
                "success": False,
                "error": "Vision model ตอบคำอธิบายแทนข้อความ OCR จึงหยุดการคำนวณเพื่อป้องกันยอดเงินผิด",
                "raw_content": raw_ocr,
                "elapsed_time": elapsed,
                "retryable": True,
            }

        data = extracted["data"]
        data["items"] = data.get("items") or []
        data["ocr_text"] = summarize_document_data(data)
        return {
            "success": True,
            "data": data,
            "raw_content": raw_ocr,
            "elapsed_time": elapsed,
        }
    except Exception as error:
        return {
            "success": False,
            "error": str(error),
            "elapsed_time": round(time.perf_counter() - started, 2),
            "retryable": True,
        }


_THAI_CHAR_RE = re.compile(r"[\u0E00-\u0E7F]")
_LATIN_CHAR_RE = re.compile(r"[A-Za-z]")
NAME_FIELD_LABELS = {"store_name": "ผู้รับเงิน", "payer_name": "ผู้จ่ายเงิน"}


_MONTH_ROWS = [
    ("ม.ค.", "มกราคม", "jan"), ("ก.พ.", "กุมภาพันธ์", "feb"), ("มี.ค.", "มีนาคม", "mar"),
    ("เม.ย.", "เมษายน", "apr"), ("พ.ค.", "พฤษภาคม", "may"), ("มิ.ย.", "มิถุนายน", "jun"),
    ("ก.ค.", "กรกฎาคม", "jul"), ("ส.ค.", "สิงหาคม", "aug"), ("ก.ย.", "กันยายน", "sep"),
    ("ต.ค.", "ตุลาคม", "oct"), ("พ.ย.", "พฤศจิกายน", "nov"), ("ธ.ค.", "ธันวาคม", "dec"),
]
_MONTH_LOOKUP = {}
for _number, (_abbr, _full, _eng) in enumerate(_MONTH_ROWS, start=1):
    for _key in (_abbr.replace(".", ""), _full, _eng):
        _MONTH_LOOKUP[_key] = _number
_TEXT_DATE_RE = re.compile(r"(\d{1,2})[\s/.\-]*([\u0E00-\u0E7F.]+|[A-Za-z]{3,9}\.?)[\s/.\-]*(\d{4}|\d{2})(?!\d)")
_NUMERIC_DATE_RE = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)")
_ISO_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\b")


def _resolve_year(year_text):
    year = int(year_text)
    if len(year_text) == 4:
        return year - 543 if year > 2400 else year
    # Two digits: could be Buddhist Era (25yy) or Gregorian (20yy). Pick the one nearest today.
    today_year = _dt.date.today().year
    return min((2000 + year, 1957 + year), key=lambda candidate: abs(candidate - today_year))


def parse_date(text):
    """Parse a Thai/English slip or receipt date into 'YYYY-MM-DD' (Gregorian), or None.

    Understands BE/CE years, 2-digit years, Thai month names/abbreviations and
    dd/mm/yyyy. A bare day number (e.g. '26') is NOT a complete date -> None.
    """
    text = str(text or "")
    try:
        iso = _ISO_DATE_RE.match(text)
        if iso:
            return _dt.date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).isoformat()
        for match in _NUMERIC_DATE_RE.finditer(text):
            day, month, year_text = match.groups()
            return _dt.date(_resolve_year(year_text), int(month), int(day)).isoformat()
        for match in _TEXT_DATE_RE.finditer(text):
            day, month_text, year_text = match.groups()
            month = _MONTH_LOOKUP.get(month_text.replace(".", "").strip().lower())
            if month:
                return _dt.date(_resolve_year(year_text), month, int(day)).isoformat()
    except ValueError:
        return None
    return None


def normalize_document_date(data):
    """Store the date as ISO (keeping the original text in date_raw); flag unreadable dates."""
    warnings = data.setdefault("check_warnings", [])
    raw = data.get("date")
    if raw in (None, ""):
        return
    iso = parse_date(raw)
    if iso:
        data["date_raw"] = str(raw)
        data["date"] = iso
    else:
        warnings.append(f"อ่านวันที่ได้ไม่ครบหรือรูปแบบไม่รู้จัก ('{raw}') กรุณาตรวจกับภาพ")


def _ocr_lines(text):
    lines = [_clean_ocr_line(line) for line in str(text or "").splitlines()]
    return [line for line in lines if line]


def _amount_from_ocr_text(text):
    """Amount printed after the 'จำนวนเงิน' label on a slip, or None."""
    lines = _ocr_lines(text)
    for index, line in enumerate(lines):
        if "จำนวนเงิน" not in line:
            continue
        for candidate in lines[index:index + 3]:
            if "ค่าธรรมเนียม" in candidate:
                break
            match = re.search(r"\d[\d,]*\.\d{2}", candidate)
            if match:
                return float(match.group(0).replace(",", ""))
    return None


def _date_from_ocr_text(text):
    lines = _ocr_lines(text)
    for index, line in enumerate(lines):
        if "วันที่" in line:
            found = parse_date(" ".join(lines[index:index + 2]))
            if found:
                return found
    return parse_date(" ".join(lines))


def apply_ocr_crosscheck(data, text):
    """Compare the vision model's amount/date with Typhoon OCR's reading of the same slip.

    The amount is never overwritten (only flagged). A date that disagrees, or that the
    vision model only read partially, is replaced by Typhoon's complete date, with a flag.
    """
    warnings = data.setdefault("check_warnings", [])
    typhoon_amount = _amount_from_ocr_text(text)
    vision_amount = data.get("transfer_amount")
    if typhoon_amount is not None and vision_amount is not None:
        try:
            if abs(float(vision_amount) - typhoon_amount) >= 0.005:
                warnings.append(
                    f"ยอดโอนไม่ตรงกัน: โมเดลภาพอ่านได้ {float(vision_amount):,.2f} แต่ Typhoon OCR อ่านได้ "
                    f"{typhoon_amount:,.2f} กรุณาตรวจกับภาพ"
                )
        except (TypeError, ValueError):
            pass
    typhoon_date = _date_from_ocr_text(text)
    if typhoon_date:
        current = parse_date(data.get("date"))
        if current != typhoon_date:
            if data.get("date") not in (None, ""):
                if current:
                    warnings.append(
                        f"วันที่ไม่ตรงกัน: โมเดลภาพอ่านได้ {current} แต่ Typhoon OCR อ่านได้ {typhoon_date} "
                        "(ใช้ค่าของ Typhoon) กรุณาตรวจกับภาพ"
                    )
                # a partial/unparseable date already produced its own warning; replace it
                data["check_warnings"] = [w for w in warnings if not w.startswith("อ่านวันที่ได้ไม่ครบ")]
                data.setdefault("date_raw", str(data.get("date")))
            data["date"] = typhoon_date


_ALLOWED_MASK_CHARS = set("•●○·＊")


def _has_odd_characters(text):
    """Characters that never belong in a Thai/ASCII name (e.g. 'ᵒ'), so likely OCR garbage."""
    return any(
        ord(char) > 127
        and not (0x0E00 <= ord(char) <= 0x0E7F)
        and not char.isspace()
        and char not in _ALLOWED_MASK_CHARS
        for char in str(text or "")
    )


def name_looks_unreliable(name):
    """A Thai name that also contains Latin letters (e.g. 'ไชยynaพิน') usually means the
    vision model could not read the glyphs and guessed. '*' masking is not Latin."""
    text = str(name or "")
    return bool((_THAI_CHAR_RE.search(text) and _LATIN_CHAR_RE.search(text)) or _has_odd_characters(text))


def unreliable_name_fields(data):
    """Labels of transfer-slip name fields that should be double-checked by the user."""
    if not isinstance(data, dict) or data.get("transfer_amount") is None:
        return []
    return [label for key, label in NAME_FIELD_LABELS.items() if name_looks_unreliable(data.get(key))]


# Typhoon OCR allows 2 requests/second and 20 requests/minute. Stay under both so a
# large batch waits for a free slot instead of getting HTTP 429 and silently losing names.
TYPHOON_MAX_PER_MINUTE = 18
TYPHOON_MIN_INTERVAL = 0.5
_typhoon_lock = threading.Lock()
_typhoon_calls = deque()


def _typhoon_wait_for_slot():
    while True:
        with _typhoon_lock:
            now = time.monotonic()
            while _typhoon_calls and now - _typhoon_calls[0] >= 60:
                _typhoon_calls.popleft()
            wait = 0.0
            if len(_typhoon_calls) >= TYPHOON_MAX_PER_MINUTE:
                wait = 60 - (now - _typhoon_calls[0])
            elif _typhoon_calls and now - _typhoon_calls[-1] < TYPHOON_MIN_INTERVAL:
                wait = TYPHOON_MIN_INTERVAL - (now - _typhoon_calls[-1])
            if wait <= 0:
                _typhoon_calls.append(now)
                return
        time.sleep(wait)


def _typhoon_ocr_request(image_bytes):
    """Read the whole image with Typhoon OCR (Thai-specialised). Returns (text, status).

    status: 'ok', 'no_key', 'rate_limited', 'http_error' or 'error'.
    Request shape follows the official typhoon-ocr client (OpenAI-compatible API).
    """
    if not TYPHOON_OCR_APIKEY:
        return None, "no_key"
    optimized_bytes, optimized_mime = optimize_image_for_ocr(image_bytes, max_dim=1800)
    image_data = base64.b64encode(optimized_bytes).decode("utf-8")
    prompt = (
        "Extract all text from the image.\n\nInstructions:\n- Only return the clean Markdown.\n"
        "- Do not include any explanation or extra text.\n- You must include all information on the page."
    )
    payload = {
        "model": "typhoon-ocr",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{optimized_mime};base64,{image_data}"}},
                ],
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.1,
        "top_p": 0.6,
        "repetition_penalty": 1.1,
    }
    headers = {"Authorization": f"Bearer {TYPHOON_OCR_APIKEY}", "Content-Type": "application/json"}
    status = "error"
    for attempt in range(3):
        _typhoon_wait_for_slot()
        try:
            response = _http_session.post(TYPHOON_OCR_URL, headers=headers, json=payload, timeout=60)
            if response.status_code == 429:
                status = "rate_limited"
                try:
                    delay = min(float(response.headers.get("Retry-After", 5)), 30)
                except (TypeError, ValueError):
                    delay = 5
                time.sleep(delay)
                continue
            if response.status_code != 200:
                return None, "http_error"
            text = response.json()["choices"][0]["message"]["content"]
            if isinstance(text, str) and text.strip():
                return text, "ok"
            return None, "error"
        except Exception:
            return None, "error"
    return None, status


def typhoon_ocr_text(image_bytes):
    """Typhoon OCR Markdown text for the image, or None when unavailable."""
    return _typhoon_ocr_request(image_bytes)[0]


_TYPHOON_STATUS_TEXT = {
    "no_key": "ไม่มีคีย์ Typhoon",
    "rate_limited": "Typhoon ติดโควตา",
    "http_error": "Typhoon ตอบ error",
    "error": "Typhoon เรียกไม่สำเร็จ",
}


def _clean_ocr_line(line):
    line = re.sub(r"<[^>]+>", " ", line)  # drop HTML tags from table output
    line = re.sub(r"^[\s#>|\-]+", "", line)  # markdown prefixes; '*' is kept (masked names)
    return re.sub(r"[\s|]+$", "", line).strip()


def names_from_ocr_text(text):
    """Pick sender/receiver names from OCR text by their 'จาก' / 'ไปยัง' labels.

    Copies the text verbatim (no LLM rewriting). Returns {"payer_name", "store_name"}
    for whichever labels were found, or {} if the layout has no such labels.
    """
    lines = [_clean_ocr_line(line) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    found = {}
    for label, key in (("จาก", "payer_name"), ("ไปยัง", "store_name")):
        for index, line in enumerate(lines):
            if line == label:
                candidate = lines[index + 1] if index + 1 < len(lines) else ""
            elif line.startswith(label + " "):
                candidate = line[len(label):].strip()
            else:
                continue
            if candidate and candidate not in ("จาก", "ไปยัง"):
                found[key] = candidate
                break
    return found


def _refine_person_names(optimized_mime, image_data, url, headers):
    """Second, narrow pass that reads only the sender/receiver names on a transfer slip.

    A single-purpose prompt gives the vision model less to juggle than the full
    18-field schema. Returns {"payer_name": str, "store_name": str} with only the
    names that were read, or {} on any failure so the first-pass values are kept.
    """
    prompt = (
        '/no_think อ่านเฉพาะชื่อบุคคลบนสลิปโอนเงินนี้ ตอบ JSON เท่านั้น: '
        '{"payer_name": null, "receiver_name": null}. '
        "payer_name คือชื่อใต้คำว่า 'จาก'; receiver_name คือชื่อใต้คำว่า 'ไปยัง'. "
        "ถอดอักษรไทยตามภาพทีละตัวอักษร รวมคำนำหน้า (นาย/นาง/นางสาว) สระ วรรณยุกต์ และการันต์ (เช่น ธุ์) "
        "ตัวที่ถูกปิดด้วย * ให้คง * ไว้ตามภาพ ห้ามแปลงอักษรไทยเป็นอักษรอังกฤษ ห้ามเดาหรือแก้ชื่อให้คุ้นเคย; อ่านไม่ได้ให้เป็น null."
    )
    payload = {
        "model": "qwen3.5-9b",
        "messages": [
            {"role": "system", "content": "คุณเป็น OCR engine ตอบ JSON เดียวเท่านั้น ห้ามอธิบาย"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{optimized_mime};base64,{image_data}"}},
                ],
            },
        ],
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": 300,
        "temperature": 0,
    }
    try:
        response = _http_session.post(url, headers=headers, json=payload, timeout=40)
        if response.status_code != 200:
            return {}
        answer = clean_llm_response(response.json()["choices"][0]["message"]["content"])
        parsed = parse_json_object(answer) or {}
    except Exception:
        return {}

    names = {}
    for source_key, target_key in (("payer_name", "payer_name"), ("receiver_name", "store_name")):
        value = parsed.get(source_key)
        if isinstance(value, str) and value.strip() and value.strip().lower() != "null":
            names[target_key] = value.strip()
    return names


def extract_document_intelligence(image_bytes, mime_type="image/jpeg", max_attempts=3):
    if not THAILLM_APIKEY:
        return {
            "success": False,
            "error": "ยังไม่ได้ตั้งค่า THAILLM_APIKEY กรุณาเพิ่มคีย์ใน .streamlit/secrets.toml หรือ environment variables แล้วเริ่มแอปใหม่",
        }

    # Pre-process image once; reused across retry attempts below.
    optimized_bytes, optimized_mime = optimize_image_for_ocr(image_bytes)
    image_data = base64.b64encode(optimized_bytes).decode("utf-8")
    url = "https://api.thaillm.or.th/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {THAILLM_APIKEY}",
        "Content-Type": "application/json",
    }
    output_schema = {
        "raw_ocr": "ข้อความทุกบรรทัดที่มองเห็นจริง",
        "data": {
            "document_type": None,
            "store_name": None,
            "payer_name": None,
            "date": None,
            "time": None,
            "receipt_no": None,
            "items": [{"name": None, "quantity": None, "unit_price": None, "line_total": None}],
            "subtotal": None,
            "discount": None,
            "shipping": None,
            "service_charge": None,
            "vat": None,
            "total": None,
            "transfer_amount": None,
            "fee": None,
            "debited_total": None,
            "notes": None,
        },
    }
    prompt = (
        "/no_think ตอบ JSON สั้นตาม schema นี้เท่านั้น: "
        f"{json.dumps(output_schema, ensure_ascii=False)} "
        "ถอดข้อความตรงตามภาพและห้ามเดาตัวเลข; ค่าที่อ่านไม่ได้ให้เป็น null. "
        "ราคาต่อหน่วยคือ unit_price และ line_total คือยอดบรรทัดหลังคูณจำนวน. "
        "subtotal คือยอดรายการก่อนส่วนลดและก่อนภาษี. "
        "สำหรับสลิปโอนให้แยกยอดที่ผู้รับได้เป็น transfer_amount, ค่าธรรมเนียมเป็น fee, "
        "ยอดหักบัญชีรวมเป็น debited_total; ห้ามรวม fee ใน transfer_amount. "
        "total ของสลิปเท่ากับ transfer_amount. ถ้าไม่มีรายการให้ items เป็น []. "
        "สำหรับสลิปโอนเงิน: store_name คือชื่อผู้รับเงิน (ฝั่ง 'ไปยัง'/'ผู้รับ') "
        "และ payer_name คือชื่อผู้โอน/ผู้จ่ายเงิน (ฝั่ง 'จาก'/'ผู้โอน') ห้ามใส่สลับกัน; "
        "สำหรับใบเสร็จร้านค้าให้ payer_name เป็น null. "
        "ชื่อบุคคล (store_name, payer_name) ให้ถอดตัวอักษรไทยทุกตัว รวมสระและวรรณยุกต์ ตามที่เห็นในภาพอย่างเคร่งครัดทีละตัวอักษร "
        "ห้ามเดาหรือแก้ตัวสะกดให้เป็นชื่อที่คุ้นเคย/พบบ่อยกว่าเด็ดขาด แม้ตัวสะกดจะดูแปลกก็ให้คงไว้ตามภาพ. "
        "อ่านวันที่ (date) ตามตัวเลขที่ปรากฏบนภาพอย่างละเอียดทีละหลัก ห้ามเดาหรือสับสนเลขที่รูปร่างคล้ายกัน "
        "(เช่น 2 กับ 6, 0 กับ 8, 1 กับ 7) และคงรูปแบบ/ปี (พ.ศ. หรือ ค.ศ.) ตามที่เห็นในภาพ."
    )
    payload = {
        "model": "qwen3.5-9b",
        "messages": [
            {
                "role": "system",
                "content": "คุณเป็น OCR และ document extraction engine ตอบ JSON เดียวตาม schema เท่านั้น ห้ามอธิบาย ห้ามเปิดเผย reasoning และห้ามคาดเดาข้อมูลที่อ่านไม่ชัด",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{optimized_mime};base64,{image_data}"}},
                ],
            },
        ],
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": 2000,
        "temperature": 0,
    }

    # A schema mismatch, truncated response, or meta-commentary reply is often a
    # one-off formatting slip from the vision model rather than a real failure, so
    # retry automatically instead of making the user click "process" again.
    last_result = None
    for attempt in range(max_attempts):
        result = _extract_document_intelligence_once(
            optimized_mime, image_data, url, headers, output_schema, payload
        )
        if result.get("success"):
            result.pop("retryable", None)
            data = result["data"]
            normalize_document_date(data)
            if data.get("transfer_amount") is not None:
                typhoon_text, typhoon_status = _typhoon_ocr_request(image_bytes)
                if typhoon_text:
                    apply_ocr_crosscheck(data, typhoon_text)
                typhoon_names = names_from_ocr_text(typhoon_text)
                if typhoon_names:
                    data.update(typhoon_names)
                    data["name_source"] = "typhoon-ocr"
                else:
                    reason = _TYPHOON_STATUS_TEXT.get(typhoon_status, "Typhoon ไม่พบป้าย จาก/ไปยัง")
                    data["name_source"] = f"qwen ({reason})"
                    for key, value in _refine_person_names(optimized_mime, image_data, url, headers).items():
                        # Don't replace a clean first-pass name with a Thai/Latin mix.
                        if name_looks_unreliable(value) and data.get(key) and not name_looks_unreliable(data.get(key)):
                            continue
                        data[key] = value
                data["ocr_text"] = summarize_document_data(data)
            if attempt > 0:
                result["attempts"] = attempt + 1
            return result
        last_result = result
        if not result.pop("retryable", False):
            break
    return last_result


def extract_documents_batch(documents, max_workers=5):
    if not documents:
        return []

    worker_count = min(max(1, max_workers), len(documents))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(extract_document_intelligence, image_bytes, mime_type)
            for _, image_bytes, mime_type in documents
        ]
        results = []
        for (file_name, _, _), future in zip(documents, futures):
            try:
                result = future.result()
            except Exception as error:
                result = {"success": False, "error": str(error)}
            result["file_name"] = file_name
            results.append(result)
    return results


def ask_document_qa(doc_context, user_question, model_id=PRIMARY_MODEL_ID):
    if not THAILLM_APIKEY:
        return {"success": False, "error": "ยังไม่ได้ตั้งค่า THAILLM_APIKEY ใน .streamlit/secrets.toml"}

    url = "https://api.thaillm.or.th/v1/chat/completions"
    headers = {"Authorization": f"Bearer {THAILLM_APIKEY}", "Content-Type": "application/json"}
    system_prompt = (
        "คุณคือ AI ผู้ช่วยตรวจเอกสารภาษาไทย ตอบสั้น ตรงประเด็น และยึดข้อมูลที่ให้เท่านั้น "
        "หากไม่มีข้อมูลในเอกสาร ให้ตอบว่า 'ไม่มีข้อมูลในเอกสาร'"
    )
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"ข้อมูลเอกสาร:\n{doc_context}\n\nคำถาม: {user_question}"},
        ],
        "max_tokens": 400,
        "temperature": 0.2,
    }
    started = time.perf_counter()
    try:
        response = _http_session.post(url, headers=headers, json=payload, timeout=30)
        elapsed = round(time.perf_counter() - started, 2)
        if response.status_code == 200:
            answer = clean_llm_response(response.json()["choices"][0]["message"]["content"])
            return {"success": True, "answer": answer, "elapsed_time": elapsed}
        return {"success": False, "error": f"HTTP {response.status_code}", "elapsed_time": elapsed}
    except Exception as error:
        return {"success": False, "error": str(error), "elapsed_time": round(time.perf_counter() - started, 2)}


def compare_models(doc_context, user_question):
    with ThreadPoolExecutor(max_workers=len(AVAILABLE_MODELS)) as executor:
        responses = executor.map(
            lambda model_id: ask_document_qa(doc_context, user_question, model_id),
            AVAILABLE_MODELS.values(),
        )
        return dict(zip(AVAILABLE_MODELS, responses))


def audit_financials(doc_data):
    if not doc_data or not isinstance(doc_data, dict):
        return {"status": "unknown", "msg": "ไม่มีข้อมูลแบบมีโครงสร้างให้ตรวจสอบ"}

    items = doc_data.get("items") or []

    def number(key):
        value = doc_data.get(key)
        if value is None or value == "":
            return None
        try:
            return float(str(value).replace(",", "").replace("บาท", "").strip())
        except (TypeError, ValueError):
            return None

    subtotal = number("subtotal")
    vat = number("vat")
    total = number("total")
    discount = number("discount") or 0.0
    shipping = number("shipping") or 0.0
    service_charge = number("service_charge") or 0.0
    transfer = number("transfer_amount")
    fee = number("fee")
    debited = number("debited_total")

    calculated_items = 0.0
    has_items = False
    for item in items:
        line_total = number_from_item(item.get("line_total"))
        if line_total is not None:
            calculated_items += line_total
            has_items = True
            continue
        unit_price = number_from_item(item.get("unit_price", item.get("price")))
        if unit_price is not None:
            quantity = number_from_item(item.get("quantity")) or 1.0
            calculated_items += unit_price * quantity
            has_items = True

    checks = []
    tolerance = 0.02
    total_reconciled = False
    if transfer is not None and fee is not None and debited is not None:
        checks.append((
            f"ยอดโอน ({transfer:,.2f} บาท) + ค่าธรรมเนียม ({fee:,.2f} บาท) เทียบกับยอดหักบัญชี ({debited:,.2f} บาท)",
            abs(transfer + fee - debited),
        ))
        total_reconciled = True
    if has_items and subtotal is not None:
        checks.append((
            f"ผลรวมรายการ ({calculated_items:,.2f} บาท) เทียบกับยอดก่อนภาษี ({subtotal:,.2f} บาท)",
            abs(calculated_items - subtotal),
        ))
    if subtotal is not None and vat is not None and total is not None:
        expected_total = subtotal + vat - discount + shipping + service_charge
        checks.append((
            f"ยอดก่อนภาษี + VAT - ส่วนลด + ค่าใช้จ่ายเพิ่มเติม ({expected_total:,.2f} บาท) เทียบกับยอดสุทธิที่ชำระ ({total:,.2f} บาท)",
            abs(expected_total - total),
        ))
        total_reconciled = True
    elif subtotal is None and has_items and vat is not None and total is not None:
        expected_total = calculated_items + vat - discount + shipping + service_charge
        checks.append((
            f"ผลรวมรายการ + VAT - ส่วนลด + ค่าใช้จ่ายเพิ่มเติม ({expected_total:,.2f} บาท) เทียบกับยอดสุทธิที่ชำระ ({total:,.2f} บาท)",
            abs(expected_total - total),
        ))
        total_reconciled = True

    if not checks:
        visible_total = transfer if transfer is not None else total
        if visible_total is not None:
            return {"status": "info", "msg": f"ℹ️ อ่านยอดได้ {visible_total:,.2f} บาท แต่ข้อมูลไม่พอสำหรับตรวจสมการ (ไม่มีรายการหรือยอดย่อยที่สมบูรณ์)", "total_in_doc": visible_total}
        return {"status": "info", "msg": "ℹ️ ข้อมูลตัวเลขไม่เพียงพอ (ไม่มีรายการหรือยอดย่อย) กรุณาตรวจยอดจากภาพต้นฉบับ"}

    differences = [diff for _, diff in checks]
    mismatches = [f"{label} (ต่างกัน {diff:,.2f} บาท)" for label, diff in checks if diff >= tolerance]
    max_diff = max(differences)
    if mismatches:
        return {
            "status": "warning",
            "msg": "⚠️ ตรวจพบยอดคลาดเคลื่อน: " + "; ".join(mismatches),
            "calculated_sum": calculated_items if has_items else None,
            "total_in_doc": transfer if transfer is not None else total,
            "diff": max_diff,
        }
    if total is not None and not total_reconciled:
        return {
            "status": "info",
            "msg": "ℹ️ ตรวจผลรวมรายการได้ แต่ยืนยันยอดสุทธิไม่ได้เพราะ VAT หรือองค์ประกอบยอดชำระอ่านไม่ครบ",
            "calculated_sum": calculated_items if has_items else None,
            "total_in_doc": total,
            "diff": max_diff,
        }
    return {
        "status": "passed",
        "msg": "✅ ผลการตรวจสอบผ่าน: " + "; ".join(label for label, _ in checks),
        "calculated_sum": calculated_items if has_items else None,
        "total_in_doc": transfer if transfer is not None else total,
        "diff": max_diff,
    }


def number_from_item(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("บาท", "").strip())
    except (TypeError, ValueError):
        return None


def call_ssense(text):
    if not AIFORTHAI_APIKEY:
        return None
    try:
        response = requests.post(
            "https://api.aiforthai.in.th/ssense",
            headers={"Apikey": AIFORTHAI_APIKEY},
            data={"text": text},
            timeout=10,
        )
        return response.json() if response.status_code == 200 else None
    except Exception:
        return None


def call_vaja_tts(text, mode="female"):
    if not AIFORTHAI_APIKEY:
        return None
    headers = {"Apikey": AIFORTHAI_APIKEY, "Content-Type": "application/json"}
    clean_text = re.sub(r"[#*`\-_|:\n]", " ", text)
    clean_text = re.sub(r"[a-zA-Z]", "", clean_text)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    if not clean_text:
        clean_text = "ประมวลผลเอกสารสำเร็จเรียบร้อยค่ะ" if mode == "female" else "ประมวลผลเอกสารสำเร็จเรียบร้อยครับ"
    try:
        response = requests.post(
            "https://api.aiforthai.in.th/vaja",
            headers=headers,
            json={"text": clean_text[:150].strip(), "mode": mode},
            timeout=12,
        )
        if response.status_code != 200:
            return None
        audio_url = response.json().get("audio_url")
        if not audio_url or mode == "female":
            return audio_url
        audio_response = requests.get(audio_url, timeout=10)
        if audio_response.status_code != 200:
            return audio_url
        audio_data, sample_rate = sf.read(io.BytesIO(audio_response.content))
        output = io.BytesIO()
        sf.write(output, audio_data, int(sample_rate * 0.82), format="WAV")
        return output.getvalue()
    except Exception:
        return None