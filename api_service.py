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
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text).strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            value, _ = decoder.raw_decode(cleaned[match.start():])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue

    # Salvage data block if outer JSON was truncated
    m = re.search(r'\"data\"\s*:\s*\{', cleaned)
    if m:
        start_idx = m.end() - 1
        depth = 0
        end_idx = -1
        in_str = False
        escape = False
        for i in range(start_idx, len(cleaned)):
            c = cleaned[i]
            if escape:
                escape = False
                continue
            if c == '\\':
                escape = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if not in_str:
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        end_idx = i + 1
                        break
        if end_idx != -1:
            try:
                data_dict = json.loads(cleaned[start_idx:end_idx])
                raw_ocr_m = re.search(r'\"raw_ocr\"\s*:\s*\"', cleaned)
                raw_ocr_text = ""
                if raw_ocr_m:
                    sub_raw = cleaned[raw_ocr_m.end():]
                    raw_ocr_text = re.sub(r"\n{3,}", "\n\n", sub_raw).strip()
                return {"data": data_dict, "raw_ocr": raw_ocr_text}
            except Exception:
                pass
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
        answer = re.sub(r"\n{3,}", "\n\n", answer)
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
        "raw_ocr": "ข้อความทุกบรรทัดที่มองเห็นจริง",
    }
    prompt = (
        "/no_think ตอบ JSON สั้นตาม schema นี้เท่านั้น: "
        f"{json.dumps(output_schema, ensure_ascii=False)} "
        "ถอดข้อความตรงตามภาพและห้ามเดาตัวเลข; ค่าที่อ่านไม่ได้ให้เป็น null. "
        "ห้ามขึ้นบรรทัดใหม่ว่างเปล่าซ้ำๆ เด็ดขาด. "
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


def format_document_context_for_qa(doc_data, raw_content=""):
    """Formats document structured fields and OCR content into clear, comprehensive Thai text."""
    lines = []
    if isinstance(doc_data, dict):
        store = doc_data.get("store_name") or "ไม่ระบุ"
        payer = doc_data.get("payer_name") or "ไม่ระบุ"
        doc_type = doc_data.get("document_type") or (
            "สลิปโอนเงิน" if doc_data.get("transfer_amount") is not None else "ใบเสร็จรับเงิน/ใบกำกับภาษี"
        )
        date = doc_data.get("date") or "ไม่ระบุ"
        time_str = doc_data.get("time") or "ไม่ระบุ"
        receipt_no = doc_data.get("receipt_no") or "ไม่ระบุ"

        lines.append(f"ประเภทเอกสาร: {doc_type}")
        lines.append(f"ชื่อร้านค้า/ผู้รับเงิน: {store}")
        if payer != "ไม่ระบุ":
            lines.append(f"ผู้จ่ายเงิน/ผู้โอน: {payer}")
        lines.append(f"วันที่: {date}")
        if time_str != "ไม่ระบุ":
            lines.append(f"เวลา: {time_str}")
        lines.append(f"เลขที่เอกสาร/อ้างอิง: {receipt_no}")

        transfer = doc_data.get("transfer_amount")
        total = doc_data.get("total")
        subtotal = doc_data.get("subtotal")
        vat = doc_data.get("vat")
        discount = doc_data.get("discount")
        fee = doc_data.get("fee")
        debited = doc_data.get("debited_total")

        if transfer is not None:
            try:
                lines.append(f"ยอดโอนเงิน: {float(transfer):,.2f} บาท")
            except (ValueError, TypeError):
                lines.append(f"ยอดโอนเงิน: {transfer} บาท")
            if fee is not None:
                try:
                    lines.append(f"ค่าธรรมเนียม: {float(fee):,.2f} บาท")
                except (ValueError, TypeError):
                    lines.append(f"ค่าธรรมเนียม: {fee} บาท")
            if debited is not None:
                try:
                    lines.append(f"ยอดหักบัญชีรวม: {float(debited):,.2f} บาท")
                except (ValueError, TypeError):
                    lines.append(f"ยอดหักบัญชีรวม: {debited} บาท")
        elif total is not None:
            try:
                lines.append(f"ยอดเงินสุทธิ (Total): {float(total):,.2f} บาท")
            except (ValueError, TypeError):
                lines.append(f"ยอดเงินสุทธิ: {total} บาท")

        if subtotal is not None:
            try:
                lines.append(f"ยอดก่อนภาษี/ยอดรวมสินค้า (Subtotal): {float(subtotal):,.2f} บาท")
            except (ValueError, TypeError):
                lines.append(f"ยอดก่อนภาษี: {subtotal} บาท")
        if vat is not None:
            try:
                lines.append(f"ภาษีมูลค่าเพิ่ม (VAT): {float(vat):,.2f} บาท")
            except (ValueError, TypeError):
                lines.append(f"ภาษีมูลค่าเพิ่ม: {vat} บาท")
        if discount is not None:
            try:
                if float(discount) > 0:
                    lines.append(f"ส่วนลด: {float(discount):,.2f} บาท")
            except (ValueError, TypeError):
                pass

        items = doc_data.get("items") or []
        if items:
            lines.append("รายการสินค้า/บริการทั้งหมด:")
            for idx, item in enumerate(items, 1):
                name = item.get("name", "ไม่ระบุ")
                qty = item.get("quantity", 1)
                unit_p = item.get("unit_price") or item.get("price")
                line_tot = item.get("line_total")
                p_text = f"ราคาชิ้นละ {float(unit_p):,.2f} บาท" if unit_p is not None else ""
                t_text = f"รวม {float(line_tot):,.2f} บาท" if line_tot is not None else ""
                lines.append(f"  {idx}. {name} | จำนวน: {qty} | {p_text} {t_text}".strip())

        notes = doc_data.get("notes")
        if notes:
            lines.append(f"หมายเหตุ: {notes}")

    structured_text = "\n".join(lines)
    full_context = ""
    if structured_text:
        full_context += f"--- ข้อมูลสรุปของเอกสาร ---\n{structured_text}\n\n"
    if raw_content and str(raw_content).strip():
        clean_raw = re.sub(r"\n{3,}", "\n\n", str(raw_content).strip())
        full_context += f"--- ข้อความเต็มที่ตรวจพบจากภาพ (OCR Raw Text) ---\n{clean_raw}"

    return full_context.strip()


def ask_document_qa(doc_context, user_question, model_id=PRIMARY_MODEL_ID):
    if not THAILLM_APIKEY:
        return {"success": False, "error": "ยังไม่ได้ตั้งค่า THAILLM_APIKEY ใน .streamlit/secrets.toml"}

    url = "https://api.thaillm.or.th/v1/chat/completions"
    headers = {"Authorization": f"Bearer {THAILLM_APIKEY}", "Content-Type": "application/json"}
    system_prompt = (
        "คุณคือ AI ผู้ช่วยอัจฉริยะด้านการวิเคราะห์เอกสาร ใบเสร็จ และสลิปการเงินภาษาไทย\n"
        "หน้าที่ของคุณคือตอบคำถามของผู้ใช้อย่างละเอียด ถูกต้อง สุภาพ และตรงประเด็น โดยใช้ข้อมูลจากสรุปเอกสารและข้อความ OCR ทั้งหมดที่ให้มา\n"
        "ความสามารถและข้อปฏิบัติ:\n"
        "1. สามารถตอบได้ทุกเรื่องที่มีในเอกสาร เช่น รายการสินค้า, ราคาแต่ละชิ้น, ชิ้นที่แพงที่สุด/ถูกที่สุด, ยอดรวม, ภาษี VAT, ส่วนลด, ชื่อร้าน, ผู้รับ, ผู้โอน, ธนาคาร, สาขา, เลขที่ใบเสร็จ, วันที่ และเวลา\n"
        "2. สามารถคำนวณ เปรียบเทียบราคา หรือรวมยอดเงินตามที่ผู้ใช้ถามได้\n"
        "3. หากถามถึงสิทธิ์การเบิกจ่าย หรือการนำไปใช้ทางภาษี ให้ช่วยวิเคราะห์ตามเกณฑ์ทั่วไปอย่างสมเหตุสมผล\n"
        "4. หากคำถามใดไม่มีข้อมูลระบุในเอกสารจริงๆ ให้แจ้งอย่างสุภาพว่าไม่พบข้อมูลส่วนนั้นในเอกสาร"
    )
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"ข้อมูลเอกสาร:\n{doc_context}\n\nคำถาม: {user_question}"},
        ],
        "max_tokens": 800,
        "temperature": 0.2,
    }
    started = time.perf_counter()
    try:
        response = _http_session.post(url, headers=headers, json=payload, timeout=35)
        elapsed = round(time.perf_counter() - started, 2)
        if response.status_code == 200:
            answer = clean_llm_response(response.json()["choices"][0]["message"]["content"])
            return {"success": True, "answer": answer, "elapsed_time": elapsed}
        return {"success": False, "error": f"HTTP {response.status_code}", "elapsed_time": elapsed}
    except Exception as error:
        return {"success": False, "error": str(error), "elapsed_time": round(time.perf_counter() - started, 2)}


def analyze_document_business_intelligence(doc_data, raw_content=""):
    """
    Comprehensive AI Business, Tax, and Risk Analytics for receipts and slips.
    Returns:
    - expense_category: Category, Account Code, Confidence, Narration, Reason
    - tax_compliance: Tax invoice type, Tax ID, VAT claimability, Reimbursement status, Guidelines
    - fraud_anomaly: Risk level, Risk score, Checks performed, Warnings
    - executive_insights: Executive summary, Cost optimization recommendations
    """
    if not doc_data or not isinstance(doc_data, dict):
        doc_data = {}

    store_name = str(doc_data.get("store_name") or "").strip()
    payer_name = str(doc_data.get("payer_name") or "").strip()
    date_str = str(doc_data.get("date") or "").strip()
    receipt_no = str(doc_data.get("receipt_no") or "").strip()
    items = doc_data.get("items") or []

    total = doc_data.get("total")
    subtotal = doc_data.get("subtotal")
    vat = doc_data.get("vat")
    transfer_amount = doc_data.get("transfer_amount")
    fee = doc_data.get("fee")

    amount = transfer_amount if transfer_amount is not None else total
    amount_val = 0.0
    try:
        amount_val = float(amount) if amount is not None else 0.0
    except (ValueError, TypeError):
        amount_val = 0.0

    full_text = (
        f"{store_name} {payer_name} {receipt_no} {raw_content} "
        + " ".join([str(it.get("name", "")) for it in items])
    )
    full_text_lower = full_text.lower()

    is_slip = transfer_amount is not None or "สลิป" in full_text or "โอนเงิน" in full_text

    # 1. AI Expense Categorization & Account Code
    category_name = "อื่นๆ / ค่าใช้จ่ายเบ็ดเตล็ด (Miscellaneous)"
    account_code = "5999-01"
    confidence = "80%"
    reason = "จัดหมวดหมู่ตามข้อมูลทั่วไปของเอกสาร"

    food_keywords = [
        "coffee", "cafe", "tea", "ชา", "กาแฟ", "อาหาร", "amazon", "starbucks",
        "7-eleven", "food", "kitchen", "restaurant", "croissant", "sandwich",
        "ขนม", "เบเกอรี่", "เครื่องดื่ม", "ข้าว", "ก๋วยเตี๋ยว", "kfc", "mcdonald",
    ]
    transport_keywords = [
        "ptt", "shell", "caltex", "bangchak", "น้ำมัน", "gasoline", "diesel",
        "ทางด่วน", "tollway", "grab", "taxi", "แท็กซี่", "bts", "mrt", "รถไฟ",
        "การบินไทย", "airasia", "nokair", "ยานพาหนะ", "ที่จอดรถ",
    ]
    office_keywords = [
        "officemate", "b2s", "กระดาษ", "paper", "ปากกา", "เครื่องเขียน",
        "อุปกรณ์สำนักงาน", "สมุด", "stationery", "printer", "หมึกพิมพ์", "แฟ้ม",
    ]
    maintenance_keywords = [
        "homepro", "ไทวัสดุ", "hardware", "ซ่อม", "อะไหล่", "บำรุงรักษา",
        "เครื่องมือช่าง", "หลอดไฟ", "ประปา", "ช่าง",
    ]
    util_keywords = [
        "การไฟฟ้า", "การประปา", "กฟน", "กฟภ", "tot", "true", "ais", "dtac",
        "3bb", "nt", "โทรศัพท์", "internet", "อินเทอร์เน็ต", "ค่าไฟ", "ค่าน้ำ",
    ]

    if is_slip:
        if fee is not None and float(fee) > 0 and amount_val == float(fee):
            category_name = "ค่าธรรมเนียมธนาคารและธุรกรรม (Bank & Financial Fees)"
            account_code = "5301-01"
            confidence = "95%"
            reason = "เป็นสลิปค่าธรรมเนียมธุรกรรมทางการเงิน"
        else:
            category_name = "ชำระเงินค่าสินค้า/บริการ/โอนชำระหนี้ (Payment & Settlement)"
            account_code = "1101-02"
            confidence = "92%"
            reason = "เป็นสลิปโอนเงินผ่านระบบธนาคาร/PromptPay"
    elif any(k in full_text_lower for k in food_keywords):
        category_name = "ค่าอาหารและเครื่องดื่ม / รับรอง (Food & Beverage)"
        account_code = "5101-01"
        confidence = "94%"
        reason = "ตรวจพบรายการอาหาร เครื่องดื่ม หรือร้านอาหาร/คาเฟ่"
    elif any(k in full_text_lower for k in transport_keywords):
        category_name = "ค่าเดินทางและยานพาหนะ (Travel & Transportation)"
        account_code = "5102-01"
        confidence = "92%"
        reason = "ตรวจพบสถานีบริการน้ำมัน ค่าเดินทาง หรือขนส่งสาธารณะ"
    elif any(k in full_text_lower for k in office_keywords):
        category_name = "ค่าเครื่องเขียนและอุปกรณ์สำนักงาน (Office Supplies)"
        account_code = "5103-01"
        confidence = "90%"
        reason = "ตรวจพบสินค้าเครื่องเขียน วัสดุ หรืออุปกรณ์สำนักงาน"
    elif any(k in full_text_lower for k in maintenance_keywords):
        category_name = "ค่าซ่อมแซมและบำรุงรักษา (Repairs & Maintenance)"
        account_code = "5104-01"
        confidence = "88%"
        reason = "ตรวจพบวัสดุก่อสร้าง อะไหล่ หรือการซ่อมบำรุง"
    elif any(k in full_text_lower for k in util_keywords):
        category_name = "ค่าสาธารณูปโภคและสื่อสาร (Utilities & Telecom)"
        account_code = "5106-01"
        confidence = "95%"
        reason = "ตรวจพบบริการสาธารณูปโภค ค่าไฟฟ้า ประปา หรือเครือข่ายสื่อสาร"

    doc_ref = receipt_no if receipt_no and receipt_no != "ไม่ระบุ" else date_str
    narration = f"บันทึก{category_name.split(' (')[0]} {store_name or 'ผู้รับเงิน'} อ้างอิง {doc_ref} ยอด {amount_val:,.2f} บาท"

    # 2. AI Tax & Reimbursement Assessment
    tax_id_matches = re.findall(r"(?<!\d)\d{13}(?!\d)", full_text)
    tax_id = tax_id_matches[0] if tax_id_matches else None

    is_full_tax_inv = bool(re.search(r"ใบกำกับภาษีเต็มรูป|tax\s*invoice|ต้นฉบับใบกำกับภาษี", full_text_lower))
    is_simplified = bool(re.search(r"อย่างย่อ|abb|pos|ใบเสร็จรับเงิน/ใบกำกับภาษีอย่างย่อ", full_text_lower)) or (
        not is_full_tax_inv and not is_slip and vat is not None and float(vat or 0) > 0
    )

    vat_val = 0.0
    try:
        vat_val = float(vat) if vat is not None else 0.0
    except (ValueError, TypeError):
        vat_val = 0.0

    if is_slip:
        tax_doc_type = "สลิปโอนเงินผ่านธนาคาร (Bank Transfer Slip)"
        tax_claimable = "❌ ไม่เข้าเกณฑ์ (ไม่ใช่ใบกำกับภาษี)"
        reimbursement_status = "⚠️ เบิกได้หากมีใบแจ้งหนี้/ใบเสร็จประกอบ"
        tax_notes = "สลิปโอนเงินเป็นหลักฐานการจ่ายเงิน ต้องแนบใบเสร็จรับเงินหรือใบแจ้งหนี้ที่มีเลขผู้เสียภาษีของผู้รับเงินเพื่อใช้เป็นค่าใช้จ่ายทางภาษี"
    elif is_full_tax_inv or (tax_id and vat_val > 0 and not is_simplified):
        tax_doc_type = "ใบกำกับภาษีเต็มรูป (Full Tax Invoice)"
        tax_claimable = f"✅ เคลมภาษีซื้อได้ 100% (ภาษี {vat_val:,.2f} บาท)"
        reimbursement_status = "✅ เบิกบริษัทได้สมบูรณ์ (ภาษีถูกต้องครบถ้วน)"
        tax_notes = "เอกสารมีเลขประจำตัวผู้เสียภาษีครบถ้วน นำภาษีซื้อมาหักภาษีขายใน ภ.พ.30 ได้ตามกฎหมายสรรพากร"
    elif is_simplified:
        tax_doc_type = "ใบเสร็จรับเงิน/ใบกำกับภาษีอย่างย่อ (Simplified Invoice)"
        tax_claimable = "⚠️ ภาษีซื้อต้องห้าม (ห้ามนำมาเคลมภาษีซื้อใน ภ.พ.30)"
        reimbursement_status = "✅ เบิกเป็นค่าใช้จ่ายบริษัทได้ (แต่ห้ามเคลม VAT)"
        tax_notes = "ใบกำกับภาษีอย่างย่อใช้เป็นรายจ่ายทางภาษีเงินได้นิติบุคคล (ภ.ง.ด.50) ได้เต็มจำนวน แต่ไม่สามารถนำยอด VAT ไปขอคืนหรือเคลมภาษีซื้อได้ หากต้องการเคลมภาษีซื้อให้แจ้งร้านค้าออกใบกำกับภาษีเต็มรูป"
    else:
        tax_doc_type = "ใบเสร็จรับเงินทั่วไป (General Receipt)"
        tax_claimable = "❌ ไม่มีภาษีมูลค่าเพิ่ม (Non-VAT)"
        reimbursement_status = "✅ เบิกค่าใช้จ่ายได้ตามระเบียบบริษัท"
        tax_notes = "เป็นหลักฐานการรับเงินทั่วไป สามารถลงเป็นรายจ่ายกิจการได้หากมีรายละเอียดผู้รับเงินชัดเจน"

    # 3. AI Fraud & Anomaly Risk Detection
    risk_checks = []
    risk_score = 0

    if date_str and date_str != "ไม่ระบุ":
        try:
            doc_d = _dt.date.fromisoformat(date_str)
            today_d = _dt.date.today()
            if doc_d > today_d:
                risk_score += 40
                risk_checks.append("🚩 วันที่ในเอกสารเป็นวันที่ในอนาคต (Future Date Anomaly)")
            elif (today_d - doc_d).days > 90:
                risk_score += 20
                risk_checks.append(f"⚠️ เอกสารออกเกิน 90 วันแล้ว ({(today_d - doc_d).days} วันก่อน) อาจเกินกำหนดเบิกจ่ายบริษัท")
            else:
                risk_checks.append("✅ วันที่เอกสารอยู่ในเกณฑ์ปกติ")
        except Exception:
            risk_checks.append("ℹ️ รูปแบบวันที่เอกสารไม่เป็น ISO")
    else:
        risk_score += 15
        risk_checks.append("⚠️ ไม่พบวันที่ระบุในเอกสาร")

    if amount_val <= 0:
        risk_score += 20
        risk_checks.append("⚠️ ไม่พบยอดเงินที่ชัดเจน")
    elif amount_val >= 50000.0 and is_slip:
        risk_score += 15
        risk_checks.append(f"ℹ️ ยอดโอนสูง ({amount_val:,.2f} บาท) ตรวจสอบความสอดคล้องกับอำนาจอนุมัติจ่าย")
    elif amount_val % 1000 == 0 and amount_val >= 5000 and not is_slip and not items:
        risk_score += 20
        risk_checks.append(f"⚠️ ยอดเงินเป็นจำนวนกลม ({amount_val:,.2f} บาท) โดยไม่มีรายการสินค้าแยกบรรทัด")
    else:
        risk_checks.append("✅ ยอดเงินสมเหตุสมผลและสอดคล้องกับรายการ")

    if subtotal is not None and vat is not None:
        try:
            sub_val = float(subtotal)
            if sub_val > 0:
                expected_vat = round(sub_val * 0.07, 2)
                diff = abs(vat_val - expected_vat)
                if diff > 1.0:
                    risk_score += 25
                    risk_checks.append(f"🚩 ยอด VAT ({vat_val:,.2f} บาท) ไม่ตรงกับ 7% ของยอดก่อนภาษี ({expected_vat:,.2f} บาท)")
                else:
                    risk_checks.append("✅ อัตราภาษีมูลค่าเพิ่ม (VAT 7%) ถูกต้องตามสมการ")
        except Exception:
            pass

    if risk_score >= 40:
        risk_level = "🔴 เฝ้าระวังสูง (High Risk)"
    elif risk_score >= 20:
        risk_level = "🟡 ควรตรวจสอบเพิ่มเติม (Medium Risk)"
    else:
        risk_level = "🟢 ปลอดภัย / ความเสี่ยงต่ำ (Low Risk)"

    # 4. AI Executive Summary & Insights
    rec_list = []
    if is_simplified and vat_val > 0:
        rec_list.append("💡 **ข้อแนะนำประหยัดต้นทุน:** เอกสารนี้มียอดภาษี แต่เป็นใบกำกับภาษีอย่างย่อ แนะนำให้แจ้งร้านค้าออกใบกำกับภาษีเต็มรูปเพื่อประหยัดภาษีมูลค่าเพิ่ม 7% ให้องค์กร")
    if amount_val > 1000 and category_name.startswith("ค่าอาหาร"):
        rec_list.append("💡 **การคุมงบประมาณ:** ค่าอาหาร/เครื่องดื่มรับรอง ควรระบุรายชื่อผู้รับรองและวัตถุประสงค์ทางธุรกิจประกอบการเบิกเงิน")
    if not rec_list:
        rec_list.append("💡 **สถานะภาพรวม:** เอกสารมีความถูกต้องเรียบร้อย สามารถนำเข้าสู่ระบบบัญชีและการเงินได้ทันที")

    summary_text = (
        f"เอกสารประเภท {tax_doc_type} จาก '{store_name or 'ไม่ระบุ'}' วันที่ {date_str or 'ไม่ระบุ'} "
        f"ยอดเงินสุทธิ {amount_val:,.2f} บาท จัดเป็นหมวดหมู่ {category_name} ผังบัญชี {account_code} "
        f"สถานะการเบิกจ่าย: {reimbursement_status}"
    )

    return {
        "expense_category": {
            "name": category_name,
            "code": account_code,
            "confidence": confidence,
            "narration": narration,
            "reason": reason,
        },
        "tax_compliance": {
            "doc_type": tax_doc_type,
            "tax_id": tax_id or "ไม่พบในเอกสาร",
            "claimable": tax_claimable,
            "status": reimbursement_status,
            "notes": tax_notes,
            "vat_amount": vat_val,
        },
        "fraud_anomaly": {
            "level": risk_level,
            "score": risk_score,
            "checks": risk_checks,
        },
        "executive_insights": {
            "summary": summary_text,
            "recommendations": rec_list,
        },
    }


def analyze_batch_portfolio(all_results):
    """
    Analyzes multiple scanned documents across a batch:
    - Expense breakdown by category
    - Total expenditures, claimable vs non-claimable VAT
    - Duplicate detection (matching receipt numbers or identical store+date+amount)
    - Portfolio executive advice
    """
    valid_docs = [r for r in all_results if r.get("success") and r.get("data")]
    if not valid_docs:
        return None

    category_totals = {}
    category_counts = {}
    total_spending = 0.0
    total_vat = 0.0
    claimable_vat = 0.0
    duplicates = []

    seen_receipts = {}
    seen_fingerprints = {}

    for idx, doc in enumerate(valid_docs):
        data = doc.get("data", {})
        raw = doc.get("raw_content", "")
        file_name = doc.get("file_name", f"เอกสาร #{idx + 1}")

        bi = analyze_document_business_intelligence(data, raw)
        cat_name = bi["expense_category"]["name"]

        amt = data.get("transfer_amount") if data.get("transfer_amount") is not None else data.get("total")
        try:
            amt_val = float(amt) if amt is not None else 0.0
        except (ValueError, TypeError):
            amt_val = 0.0

        vat_val = bi["tax_compliance"].get("vat_amount", 0.0)

        total_spending += amt_val
        total_vat += vat_val
        if "✅ เคลมภาษีซื้อได้" in bi["tax_compliance"].get("claimable", ""):
            claimable_vat += vat_val

        category_totals[cat_name] = category_totals.get(cat_name, 0.0) + amt_val
        category_counts[cat_name] = category_counts.get(cat_name, 0) + 1

        # Check duplicate receipt_no
        r_no = str(data.get("receipt_no") or "").strip()
        if r_no and r_no != "ไม่ระบุ":
            if r_no in seen_receipts:
                duplicates.append({
                    "type": "เลขที่เอกสารซ้ำกัน (Duplicate Receipt No.)",
                    "detail": f"เลขที่ '{r_no}' ซ้ำกันระหว่าง {seen_receipts[r_no]} กับ {file_name}",
                })
            else:
                seen_receipts[r_no] = file_name

        # Check duplicate fingerprint (store + date + amount)
        s_name = str(data.get("store_name") or "").strip()
        d_val = str(data.get("date") or "").strip()
        if s_name and d_val and amt_val > 0:
            fp = f"{s_name}_{d_val}_{amt_val:.2f}"
            if fp in seen_fingerprints:
                duplicates.append({
                    "type": "ยอดเงินและคู่ค้าซ้ำกัน (Identical Store/Date/Amount)",
                    "detail": f"ร้าน '{s_name}' วันที่ {d_val} ยอด {amt_val:,.2f} บาท ซ้ำกันระหว่าง {seen_fingerprints[fp]} กับ {file_name}",
                })
            else:
                seen_fingerprints[fp] = file_name

    sorted_cats = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)

    return {
        "total_documents": len(valid_docs),
        "total_spending": total_spending,
        "total_vat": total_vat,
        "claimable_vat": claimable_vat,
        "category_totals": sorted_cats,
        "category_counts": category_counts,
        "duplicates": duplicates,
        "top_category": sorted_cats[0][0] if sorted_cats else "ไม่ระบุ",
    }


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