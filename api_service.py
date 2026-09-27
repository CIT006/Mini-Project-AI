import base64
import io
import json
import os
import re
import time
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
        summary = f"ยอดโอน {float(transfer_amount):,.2f} บาท"
        fee = data.get("fee")
        debited_total = data.get("debited_total")
        payer_name = data.get("payer_name")
        receiver_account = data.get("receiver_account")
        bank_name = data.get("bank_name")
        if payer_name:
            summary += f" โดย {payer_name}"
        if receiver_account:
            summary += f" ไปบัญชี {receiver_account}"
        if bank_name:
            summary += f" ({bank_name})"
        if fee is not None:
            summary += f" ค่าธรรมเนียม {float(fee):,.2f} บาท"
        if debited_total is not None:
            summary += f" ยอดหักบัญชีรวม {float(debited_total):,.2f} บาท"
        return summary
    total = data.get("total")
    if total is None:
        return "ไม่สามารถสกัดยอดเงินจากเอกสารได้ กรุณาตรวจข้อความ OCR และภาพต้นฉบับ"
    payer_name = data.get("payer_name")
    cashier = data.get("cashier")
    extra = ""
    if payer_name:
        extra += f" ผู้ซื้อ: {payer_name}"
    if cashier:
        extra += f" แคชเชียร์: {cashier}"
    return f"ยอดสุทธิที่ต้องชำระ {float(total):,.2f} บาท{extra}"


def optimize_image_for_ocr(image_bytes, max_dim=1200, quality=85):
    """
    Optimizes and downscales images in-memory to guarantee sub-3-second OCR processing.
    Downscales large phone camera images (3-10MB) to optimal OCR resolution (~1200px),
    greatly reducing network upload payload and Vision model inference latency.
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


def extract_document_intelligence(image_bytes, mime_type="image/jpeg"):
    if not THAILLM_APIKEY:
        return {
            "success": False,
            "error": "ยังไม่ได้ตั้งค่า THAILLM_APIKEY กรุณาเพิ่มคีย์ใน .streamlit/secrets.toml หรือ environment variables แล้วเริ่มแอปใหม่",
        }

    # Pre-process image to achieve sub-3-second response time
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
        # ✅ ฟิลด์ใหม่: ข้อมูลผู้จ่ายเงิน/ผู้โอน
        "payer_name": None,          # ชื่อผู้โอนเงิน / ผู้ซื้อ
        "payer_account": None,       # เลขบัญชีผู้โอน (ถ้ามี)
        "receiver_account": None,    # เลขบัญชีผู้รับ (ถ้ามี)
        "bank_name": None,           # ธนาคาร (ถ้าระบุ)
        "cashier": None,             # แคชเชียร์/พนักงาน (ใบเสร็จ)
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
    # ✅ เพิ่มคำสั่งสกัดข้อมูลผู้โอน
    "สำหรับสลิปโอน: ให้สกัด payer_name (ชื่อผู้โอน), payer_account (เลขบัญชีผู้โอน), "
    "receiver_account (เลขบัญชีผู้รับ), bank_name (ธนาคาร) จากภาพให้ครบถ้วน. "
    "สำหรับใบเสร็จ: ให้สกัด cashier (ชื่อ/รหัสพนักงานแคชเชียร์) และ payer_name (ชื่อลูกค้า/ผู้ซื้อ ถ้ามี)."
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
        "max_tokens": 800,
        "temperature": 0,
    }

    started = time.perf_counter()
    try:
        response = _http_session.post(url, headers=headers, json=payload, timeout=40)
        elapsed = round(time.perf_counter() - started, 2)
        if response.status_code != 200:
            return {"success": False, "error": f"Vision API HTTP {response.status_code}", "elapsed_time": elapsed}

        answer = clean_llm_response(response.json()["choices"][0]["message"]["content"])
        extracted = parse_json_object(answer)
        if not extracted or not isinstance(extracted.get("data"), dict):
            return {
                "success": False,
                "error": "โมเดลอ่านภาพแล้ว แต่คืนข้อมูลไม่ครบตาม schema จึงไม่แสดงยอดที่คาดเดา",
                "raw_content": answer,
                "elapsed_time": elapsed,
            }

        raw_ocr = str(extracted.get("raw_ocr") or "").strip()
        if is_ocr_meta_response(raw_ocr):
            return {
                "success": False,
                "error": "Vision model ตอบคำอธิบายแทนข้อความ OCR จึงหยุดการคำนวณเพื่อป้องกันยอดเงินผิด",
                "raw_content": raw_ocr,
                "elapsed_time": elapsed,
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
        return {"success": False, "error": str(error), "elapsed_time": round(time.perf_counter() - started, 2)}


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