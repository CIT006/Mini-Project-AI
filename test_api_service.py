import unittest
import os
from concurrent.futures import Future
import threading
from unittest.mock import patch
import api_service


class ApiKeyLoadingTests(unittest.TestCase):
    def test_document_qa_uses_the_single_primary_model(self):
        self.assertEqual(api_service.PRIMARY_MODEL_NAME, "Typhoon-S 8B")
        self.assertEqual(api_service.PRIMARY_MODEL_ID, api_service.AVAILABLE_MODELS["Typhoon-S 8B"])

    def test_environment_key_takes_precedence(self):
        with patch.dict(os.environ, {"THAILLM_APIKEY": " env-key "}), patch.object(
            api_service, "_read_streamlit_secret", return_value="file-key"
        ):
            self.assertEqual(api_service._load_api_key("THAILLM_APIKEY"), "env-key")

    def test_streamlit_secret_is_used_when_environment_is_empty(self):
        with patch.dict(os.environ, {"THAILLM_APIKEY": ""}), patch.object(
            api_service, "_read_streamlit_secret", return_value="file-key"
        ):
            self.assertEqual(api_service._load_api_key("THAILLM_APIKEY"), "file-key")


class StructuredExtractionTests(unittest.TestCase):
    def test_json_parser_handles_fenced_json_with_surrounding_text(self):
        parsed = api_service.parse_json_object(
            'ผลลัพธ์:\n```json\n{"total": 203.3, "items": []}\n```'
        )

        self.assertEqual(parsed, {"total": 203.3, "items": []})

    def test_json_parser_returns_none_instead_of_inventing_data(self):
        self.assertIsNone(api_service.parse_json_object("อ่านยอดเงินไม่ได้"))

    def test_model_reasoning_is_rejected_as_ocr(self):
        self.assertTrue(api_service.is_ocr_meta_response("The user wants me to extract text from this image"))
        self.assertFalse(api_service.is_ocr_meta_response("ยอดโอน 1,000.00 บาท"))

    def test_transfer_summary_keeps_fee_separate(self):
        summary = api_service.summarize_document_data({
            "transfer_amount": 1_000_000,
            "fee": 20,
            "debited_total": 1_000_020,
        })

        self.assertIn("ยอดโอน 1,000,000.00 บาท", summary)
        self.assertIn("ค่าธรรมเนียม 20.00 บาท", summary)
        self.assertIn("ยอดหักบัญชีรวม 1,000,020.00 บาท", summary)

    def test_summary_does_not_invent_missing_total(self):
        summary = api_service.summarize_document_data({"total": None})

        self.assertIn("ไม่สามารถสกัดยอดเงิน", summary)


class AuditFinancialsTests(unittest.TestCase):
    def test_valid_subtotal_and_vat_pass(self):
        result = api_service.audit_financials({
            "items": [{"name": "item", "quantity": 1, "price": 100}],
            "subtotal": 100,
            "vat": 7,
            "total": 107,
        })

        self.assertEqual(result["status"], "passed")
        self.assertIn("VAT", result["msg"])

    def test_item_sum_mismatch_with_subtotal_warns(self):
        result = api_service.audit_financials({
            "items": [{"name": "item", "quantity": 1, "price": 100}],
            "subtotal": 90,
            "vat": 7,
            "total": 97,
        })

        self.assertEqual(result["status"], "warning")
        self.assertIn("ยอดก่อนภาษี", result["msg"])

    def test_vat_reconciliation_mismatch_warns(self):
        result = api_service.audit_financials({
            "items": [{"name": "item", "quantity": 1, "price": 100}],
            "subtotal": 100,
            "vat": 7,
            "total": 108,
        })

        self.assertEqual(result["status"], "warning")
        self.assertIn("VAT", result["msg"])

    def test_total_is_used_when_subtotal_is_missing(self):
        result = api_service.audit_financials({
            "items": [{"name": "item", "quantity": 2, "price": 50}],
            "vat": 0,
            "total": 100,
        })

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["diff"], 0)

    def test_missing_values_return_info(self):
        result = api_service.audit_financials({"items": []})

        self.assertEqual(result["status"], "info")

    def test_line_total_is_not_multiplied_by_quantity_again(self):
        result = api_service.audit_financials({
            "items": [{"name": "item", "quantity": 2, "unit_price": 50, "line_total": 100}],
            "subtotal": 100,
            "vat": 7,
            "total": 107,
        })

        self.assertEqual(result["status"], "passed")

    def test_discount_is_included_in_subtotal_check(self):
        result = api_service.audit_financials({
            "items": [{"name": "item", "quantity": 1, "unit_price": 100}],
            "subtotal": 100,
            "discount": 10,
            "vat": 6.3,
            "total": 96.3,
        })

        self.assertEqual(result["status"], "passed")

    def test_small_currency_mismatch_warns(self):
        result = api_service.audit_financials({
            "items": [{"name": "item", "quantity": 1, "unit_price": 100}],
            "subtotal": 100,
            "vat": 7,
            "total": 100.5,
        })

        self.assertEqual(result["status"], "warning")

    def test_transfer_slip_reports_amount_without_fabricating_item_audit(self):
        result = api_service.audit_financials({
            "document_type": "สลิปโอนเงิน",
            "items": [],
            "subtotal": None,
            "vat": None,
            "total": 1250,
            "transfer_amount": 1250,
            "fee": 20,
            "debited_total": 1270,
        })

        self.assertEqual(result["status"], "passed")
        self.assertIn("1,270.00", result["msg"])

    def test_transfer_fee_mismatch_warns(self):
        result = api_service.audit_financials({
            "document_type": "สลิปโอนเงิน",
            "items": [],
            "transfer_amount": 1_000_000,
            "fee": 20,
            "debited_total": 1_000_030,
        })

        self.assertEqual(result["status"], "warning")

    def test_unknown_vat_does_not_claim_total_reconciliation_passed(self):
        result = api_service.audit_financials({
            "items": [{"name": "item", "quantity": 1, "unit_price": 100}],
            "subtotal": 100,
            "vat": None,
            "total": 107,
        })

        self.assertEqual(result["status"], "info")
        self.assertIn("ยืนยันยอดสุทธิไม่ได้", result["msg"])

    def test_total_without_subtotal_or_vat_is_not_assumed_to_pass(self):
        result = api_service.audit_financials({
            "items": [{"name": "item", "quantity": 2, "unit_price": 50}],
            "total": 107,
        })

        self.assertEqual(result["status"], "info")
        self.assertIn("ไม่มีรายการหรือยอดย่อย", result["msg"])


class ImageOptimizationTests(unittest.TestCase):
    def test_optimize_image_downscales_large_image(self):
        import io
        from PIL import Image
        img = Image.new("RGB", (2400, 3200), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        raw_bytes = buf.getvalue()

        opt_bytes, mime = api_service.optimize_image_for_ocr(raw_bytes, max_dim=1200)
        self.assertEqual(mime, "image/jpeg")
        self.assertLess(len(opt_bytes), len(raw_bytes))

        # Verify dimension
        opt_img = Image.open(io.BytesIO(opt_bytes))
        self.assertLessEqual(max(opt_img.size), 1200)

    def test_optimize_image_handles_corrupt_gracefully(self):
        corrupt = b"not_an_image"
        out_bytes, mime = api_service.optimize_image_for_ocr(corrupt)
        self.assertEqual(out_bytes, corrupt)
        self.assertEqual(mime, "image/jpeg")


class NameRefinementTests(unittest.TestCase):
    def _resp(self, content):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
        return r

    def test_second_pass_replaces_names_on_transfer_slip(self):
        first = self._resp('{"raw_ocr": "x", "data": {"transfer_amount": 30, "total": 30, "store_name": "ผิด", "payer_name": "ผิด", "items": []}}')
        second = self._resp('{"payer_name": "นาย ธันยบูรณ์ พ***", "receiver_name": "นาย ปรเมศ ไชยนาพันธุ์"}')
        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service, "TYPHOON_OCR_APIKEY", ""
        ), patch.object(
            api_service._http_session, "post", side_effect=[first, second]
        ):
            result = api_service.extract_document_intelligence(b"img")
        self.assertEqual(result["data"]["store_name"], "นาย ปรเมศ ไชยนาพันธุ์")
        self.assertEqual(result["data"]["payer_name"], "นาย ธันยบูรณ์ พ***")
        self.assertIn("นาย ปรเมศ ไชยนาพันธุ์", result["data"]["ocr_text"])

    def test_failed_second_pass_keeps_first_pass_names(self):
        first = self._resp('{"raw_ocr": "x", "data": {"transfer_amount": 30, "total": 30, "store_name": "เดิม", "items": []}}')
        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service, "TYPHOON_OCR_APIKEY", ""
        ), patch.object(
            api_service._http_session, "post", side_effect=[first, RuntimeError("boom")]
        ):
            result = api_service.extract_document_intelligence(b"img")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["store_name"], "เดิม")

    def test_receipts_skip_second_pass(self):
        first = self._resp('{"raw_ocr": "x", "data": {"total": 10, "items": []}}')
        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service, "TYPHOON_OCR_APIKEY", ""
        ), patch.object(api_service._http_session, "post", side_effect=[first]) as post:
            api_service.extract_document_intelligence(b"img")
        self.assertEqual(post.call_count, 1)


class UnreliableNameTests(unittest.TestCase):
    def test_mixed_thai_and_latin_is_flagged(self):
        self.assertTrue(api_service.name_looks_unreliable("สามนวล autherland"))
        self.assertTrue(api_service.name_looks_unreliable("รันย์บุรณ์ P * * *"))

    def test_clean_names_are_not_flagged(self):
        self.assertFalse(api_service.name_looks_unreliable("นาย ธันยบูรณ์ พ***"))
        self.assertFalse(api_service.name_looks_unreliable("7-ELEVEN"))
        self.assertFalse(api_service.name_looks_unreliable(None))

    def test_only_transfer_slips_report_fields(self):
        slip = {"transfer_amount": 30, "store_name": "สามนวล autherland", "payer_name": "นาย ก"}
        self.assertEqual(api_service.unreliable_name_fields(slip), ["ผู้รับเงิน"])
        self.assertEqual(api_service.unreliable_name_fields({"store_name": "ร้าน ABC"}), [])

    def test_mixed_second_pass_does_not_overwrite_clean_first_pass(self):
        from unittest.mock import MagicMock
        def resp(c):
            r = MagicMock(); r.status_code = 200
            r.json.return_value = {"choices": [{"message": {"content": c}, "finish_reason": "stop"}]}
            return r
        first = resp('{"raw_ocr": "x", "data": {"transfer_amount": 30, "total": 30, "store_name": "นาย ก", "items": []}}')
        second = resp('{"receiver_name": "นาย autherland"}')
        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service._http_session, "post", side_effect=[first, second]
        ):
            result = api_service.extract_document_intelligence(b"img")
        self.assertEqual(result["data"]["store_name"], "นาย ก")


class TyphoonNameTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(api_service, "TYPHOON_MIN_INTERVAL", 0)
        p.start(); self.addCleanup(p.stop)
        api_service._typhoon_calls.clear()

    SLIP = "โอนเงินสำเร็จ\nจาก\nนาย ธันยบูรณ์ พ***\nกรุงไทย\nXXX-X-XX075-2\nไปยัง\nนาย ปรเมศ ไชยนาพันธุ์\nพร้อมเพย์\nจำนวนเงิน 30.00 บาท"

    def test_names_follow_from_and_to_labels(self):
        self.assertEqual(
            api_service.names_from_ocr_text(self.SLIP),
            {"payer_name": "นาย ธันยบูรณ์ พ***", "store_name": "นาย ปรเมศ ไชยนาพันธุ์"},
        )

    def test_same_line_and_markdown_labels(self):
        text = "## จาก นาย ก ใจดี\n**ไปยัง**\n"
        self.assertEqual(api_service.names_from_ocr_text(text), {"payer_name": "นาย ก ใจดี"})

    def test_no_labels_returns_empty(self):
        self.assertEqual(api_service.names_from_ocr_text("ใบเสร็จ 7-ELEVEN\nรวม 240.00"), {})
        self.assertEqual(api_service.names_from_ocr_text(None), {})

    def _resp(self, content):
        from unittest.mock import MagicMock
        r = MagicMock(); r.status_code = 200
        r.json.return_value = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
        return r

    def _router(self, typhoon, *qwen_responses):
        """Route mocked POSTs by URL (Typhoon now runs in parallel with Qwen)."""
        qwen_iter = iter(qwen_responses)

        def _post(url, *args, **kwargs):
            if url == api_service.TYPHOON_OCR_URL:
                return typhoon
            return next(qwen_iter)

        return _post

    def test_typhoon_names_override_qwen_and_skip_second_qwen_pass(self):
        first = self._resp('{"raw_ocr": "x", "data": {"transfer_amount": 30, "total": 30, "store_name": "ผิด", "items": []}}')
        typhoon = self._resp(self.SLIP)
        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service, "TYPHOON_OCR_APIKEY", "t"
        ), patch.object(api_service._http_session, "post", side_effect=self._router(typhoon, first)) as post:
            result = api_service.extract_document_intelligence(b"img")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result["data"]["store_name"], "นาย ปรเมศ ไชยนาพันธุ์")
        self.assertEqual(result["data"]["name_source"], "typhoon-ocr")
        self.assertIn("นาย ปรเมศ ไชยนาพันธุ์", result["data"]["ocr_text"])

    def test_typhoon_without_labels_falls_back_to_qwen_pass(self):
        first = self._resp('{"raw_ocr": "x", "data": {"transfer_amount": 30, "total": 30, "store_name": "เดิม", "items": []}}')
        typhoon = self._resp("ข้อความไม่มีป้ายชื่อ")
        refine = self._resp('{"receiver_name": "นาย ข"}')
        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service, "TYPHOON_OCR_APIKEY", "t"
        ), patch.object(api_service._http_session, "post", side_effect=self._router(typhoon, first, refine)):
            result = api_service.extract_document_intelligence(b"img")
        self.assertEqual(result["data"]["store_name"], "นาย ข")

    def test_no_typhoon_key_means_no_typhoon_call(self):
        self.assertIsNone(api_service.typhoon_ocr_text(b"img")) if not api_service.TYPHOON_OCR_APIKEY else None


class DateNormalizationTests(unittest.TestCase):
    def test_formats_seen_in_real_exports(self):
        cases = {
            "22 ก.ย. 2569": "2026-09-22",
            "26 ก.ย. 2569 - 12:54": "2026-09-26",
            "22/9/2569": "2026-09-22",
            "25/9/2569": "2026-09-25",
            "22/09/2026": "2026-09-22",
            "22-ก.ย.-69": "2026-09-22",
            "26 กันยายน 2569": "2026-09-26",
            "2026-09-27": "2026-09-27",
            "27/09/2026 14:30": "2026-09-27",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(api_service.parse_date(text), expected)

    def test_bare_day_or_garbage_is_not_a_date(self):
        for text in ("26", "", None, "ไม่ระบุ", "31/02/2569"):
            with self.subTest(text=text):
                self.assertIsNone(api_service.parse_date(text))

    def test_normalize_keeps_raw_and_flags_partial_date(self):
        ok = {"date": "22 ก.ย. 2569"}
        api_service.normalize_document_date(ok)
        self.assertEqual((ok["date"], ok["date_raw"], ok["check_warnings"]), ("2026-09-22", "22 ก.ย. 2569", []))
        partial = {"date": "26"}
        api_service.normalize_document_date(partial)
        self.assertEqual(partial["date"], "26")
        self.assertTrue(partial["check_warnings"])


class CrossCheckTests(unittest.TestCase):
    TEXT = "โอนเงินสำเร็จ\nจำนวนเงิน\n55.00 บาท\nค่าธรรมเนียม 0.00 บาท\nวันที่ทำรายการ 26 ก.ย. 2569 - 12:54"

    def test_amount_and_date_read_from_ocr_text(self):
        self.assertEqual(api_service._amount_from_ocr_text(self.TEXT), 55.0)
        self.assertEqual(api_service._date_from_ocr_text(self.TEXT), "2026-09-26")

    def test_fee_line_is_never_mistaken_for_amount(self):
        self.assertIsNone(api_service._amount_from_ocr_text("จำนวนเงิน\nค่าธรรมเนียม 20.00 บาท"))

    def test_amount_mismatch_warns_but_keeps_value(self):
        data = {"transfer_amount": 50, "date": "2026-09-26"}
        api_service.apply_ocr_crosscheck(data, self.TEXT)
        self.assertEqual(data["transfer_amount"], 50)
        self.assertTrue(any("ยอดโอนไม่ตรงกัน" in w for w in data["check_warnings"]))

    def test_partial_date_is_completed_from_typhoon(self):
        data = {"transfer_amount": 55, "date": "26"}
        api_service.normalize_document_date(data)
        api_service.apply_ocr_crosscheck(data, self.TEXT)
        self.assertEqual(data["date"], "2026-09-26")
        self.assertEqual(data["date_raw"], "26")
        self.assertEqual(data["check_warnings"], [])

    def test_conflicting_date_uses_typhoon_and_warns(self):
        data = {"transfer_amount": 55, "date": "22 ก.ย. 2569"}
        api_service.normalize_document_date(data)
        api_service.apply_ocr_crosscheck(data, self.TEXT)
        self.assertEqual(data["date"], "2026-09-26")
        self.assertTrue(any("วันที่ไม่ตรงกัน" in w for w in data["check_warnings"]))

    def test_matching_reads_add_no_warnings(self):
        data = {"transfer_amount": 55, "date": "26 ก.ย. 2569"}
        api_service.normalize_document_date(data)
        api_service.apply_ocr_crosscheck(data, self.TEXT)
        self.assertEqual(data["check_warnings"], [])


class NameSourceAndLimiterTests(unittest.TestCase):
    def setUp(self):
        self._interval = patch.object(api_service, "TYPHOON_MIN_INTERVAL", 0)
        self._interval.start()
        self.addCleanup(self._interval.stop)
        api_service._typhoon_calls.clear()

    def _resp(self, content, status=200, headers=None):
        from unittest.mock import MagicMock
        r = MagicMock(); r.status_code = status; r.headers = headers or {}
        r.json.return_value = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
        return r

    def test_odd_characters_flag_name(self):
        self.assertTrue(api_service.name_looks_unreliable("นาย ᵒᵒᵒ"))
        self.assertFalse(api_service.name_looks_unreliable("นาย ธันยบูรณ์ พ***"))

    def test_source_reports_why_typhoon_was_not_used(self):
        first = self._resp('{"raw_ocr": "x", "data": {"transfer_amount": 30, "total": 30, "store_name": "เดิม", "items": []}}')
        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(api_service, "TYPHOON_OCR_APIKEY", ""), patch.object(
            api_service._http_session, "post", side_effect=[first, RuntimeError("x")]
        ):
            result = api_service.extract_document_intelligence(b"img")
        self.assertIn("ไม่มีคีย์ Typhoon", result["data"]["name_source"])

    def test_429_waits_and_retries(self):
        ok = self._resp("จาก\nนาย ก\nไปยัง\nนาย ข")
        limited = self._resp("", status=429, headers={"Retry-After": "1"})
        with patch.object(api_service, "TYPHOON_OCR_APIKEY", "t"), patch.object(api_service.time, "sleep") as sleep, patch.object(
            api_service._http_session, "post", side_effect=[limited, ok]
        ) as post:
            text, status = api_service._typhoon_ocr_request(b"img")
        self.assertEqual((status, post.call_count), ("ok", 2))
        self.assertIn("นาย ข", text)
        sleep.assert_any_call(1.0)

    def test_limiter_waits_when_window_is_full(self):
        now = api_service.time.monotonic()
        api_service._typhoon_calls.extend([now] * api_service.TYPHOON_MAX_PER_MINUTE)
        with patch.object(api_service.time, "sleep", side_effect=lambda _: api_service._typhoon_calls.clear()) as sleep:
            api_service._typhoon_wait_for_slot()
        self.assertTrue(sleep.called)



class BusinessIntelligenceAndQATests(unittest.TestCase):
    def test_format_document_context_includes_items_and_financials(self):
        doc = {
            "store_name": "Amazon Cafe",
            "date": "2026-09-27",
            "receipt_no": "REC-99",
            "total": 115.0,
            "items": [
                {"name": "Tea", "quantity": 1, "unit_price": 65.0, "line_total": 65.0},
                {"name": "Croissant", "quantity": 1, "unit_price": 50.0, "line_total": 50.0}
            ]
        }
        ctx = api_service.format_document_context_for_qa(doc, "RAW OCR TEXT")
        self.assertIn("Amazon Cafe", ctx)
        self.assertIn("Tea", ctx)
        self.assertIn("65.00", ctx)
        self.assertIn("115.00", ctx)
        self.assertIn("RAW OCR TEXT", ctx)

    def test_business_intelligence_categorizes_food_correctly(self):
        doc = {
            "store_name": "Starbucks Coffee",
            "total": 175.0,
            "items": [{"name": "Latte", "line_total": 175.0}]
        }
        bi = api_service.analyze_document_business_intelligence(doc)
        self.assertIn("ค่าอาหารและเครื่องดื่ม", bi["expense_category"]["name"])
        self.assertEqual(bi["expense_category"]["code"], "5101-01")

    def test_business_intelligence_categorizes_fuel_correctly(self):
        doc = {
            "store_name": "PTT Station",
            "total": 1200.0,
            "items": [{"name": "Gasohol 95", "line_total": 1200.0}]
        }
        bi = api_service.analyze_document_business_intelligence(doc)
        self.assertIn("ค่าเดินทางและยานพาหนะ", bi["expense_category"]["name"])
        self.assertEqual(bi["expense_category"]["code"], "5102-01")

    def test_batch_portfolio_detects_duplicates(self):
        doc1 = {"success": True, "file_name": "doc1.jpg", "data": {"receipt_no": "REC-01", "total": 100.0, "store_name": "Shop A", "date": "2026-09-01"}}
        doc2 = {"success": True, "file_name": "doc2.jpg", "data": {"receipt_no": "REC-01", "total": 100.0, "store_name": "Shop A", "date": "2026-09-01"}}
        batch_res = api_service.analyze_batch_portfolio([doc1, doc2])
        self.assertEqual(len(batch_res["duplicates"]), 2)  # both receipt_no and fingerprint
        self.assertEqual(batch_res["total_spending"], 200.0)



if __name__ == "__main__":
    unittest.main()

class RetryAndBatchContextTests(unittest.TestCase):
    def test_structured_fallback_recovers_from_bad_vision_json_using_parallel_ocr(self):
        ocr_future = Future()
        ocr_future.set_result(("ยอดสุทธิ 107.00 บาท", "ok"))
        fallback = {
            "success": True,
            "data": {"document_type": "ใบเสร็จ", "subtotal": 100, "vat": 7, "total": 107, "items": []},
            "raw_content": "ยอดสุทธิ 107.00 บาท",
            "elapsed_time": 0.2,
            "fallback_used": "Typhoon OCR text",
        }

        with patch.object(api_service, "_extract_document_intelligence_once", return_value={
            "success": False, "error": "invalid JSON", "retryable": True, "elapsed_time": 0.1
        }), patch.object(api_service, "_extract_structured_from_ocr_text", return_value=fallback) as rescue:
            result = api_service._extract_with_retries(
                b"image", "image/jpeg", "base64", "url", {}, {"data": {}}, {}, 1,
                ocr_future, timings={}, typhoon_cancel=threading.Event(),
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["fallback_used"], "Typhoon OCR text")
        rescue.assert_called_once_with("ยอดสุทธิ 107.00 บาท", "url", {})

    def test_structured_fallback_is_not_used_for_permanent_auth_failure(self):
        ocr_future = Future()
        ocr_future.set_result(("OCR text", "ok"))
        with patch.object(api_service, "_extract_document_intelligence_once", return_value={
            "success": False, "error": "HTTP 401", "retryable": False, "elapsed_time": 0.1
        }), patch.object(api_service, "_extract_structured_from_ocr_text") as rescue:
            result = api_service._extract_with_retries(
                b"image", "image/jpeg", "base64", "url", {}, {"data": {}}, {}, 2,
                ocr_future, timings={}, typhoon_cancel=threading.Event(),
            )

        self.assertFalse(result["success"])
        self.assertFalse(result["retryable"])
        rescue.assert_not_called()

    def test_missing_api_key_is_marked_permanent(self):
        with patch.object(api_service, "THAILLM_APIKEY", ""):
            result = api_service.extract_document_intelligence(b"img")

        self.assertFalse(result["success"])
        self.assertFalse(result["retryable"])

    def test_manual_rescue_starts_immediately_and_uses_short_backoff(self):
        responses = [
            {"success": False, "error": "schema mismatch", "retryable": True, "elapsed_time": 0.01},
            {"success": True, "data": {"items": []}, "raw_content": "", "elapsed_time": 0.01},
        ]
        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service, "TYPHOON_OCR_APIKEY", ""
        ), patch.object(
            api_service, "_extract_document_intelligence_once", side_effect=responses
        ), patch.object(api_service.time, "sleep") as sleep:
            result = api_service.extract_document_intelligence(b"img", max_attempts=2, rescue=True)

        self.assertTrue(result["success"])
        sleep.assert_called_once_with(1.5)

    def test_permanent_auth_failure_is_not_retried(self):
        attempts = []

        def fake_once(*args, **kwargs):
            attempts.append(1)
            return {"success": False, "error": "Vision API HTTP 401", "retryable": False, "elapsed_time": 0.01}

        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service, "TYPHOON_OCR_APIKEY", ""
        ), patch.object(api_service, "_extract_document_intelligence_once", side_effect=fake_once), patch.object(
            api_service.time, "sleep"
        ) as sleep:
            result = api_service.extract_document_intelligence(b"img", max_attempts=3)

        self.assertEqual(len(attempts), 1)
        self.assertFalse(result["retryable"])
        self.assertEqual(result["attempts"], 1)
        sleep.assert_not_called()

    def test_retries_change_the_request_instead_of_repeating_it(self):
        seen = []

        def fake_once(mime, data, url, headers, schema, payload, timeout=40):
            seen.append((payload["temperature"], "raw_ocr" in payload["messages"][1]["content"][0]["text"], timeout))
            if len(seen) < 3:
                return {"success": False, "error": "schema", "retryable": True}
            return {"success": True, "data": {"items": []}, "raw_content": "", "elapsed_time": 0.1}

        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service, "TYPHOON_OCR_APIKEY", ""
        ), patch.object(api_service, "_extract_document_intelligence_once", fake_once), patch.object(
            api_service.time, "sleep", lambda *_: None
        ):
            result = api_service.extract_document_intelligence(b"img")
        self.assertTrue(result["success"])
        self.assertEqual(seen[0][0], 0)
        self.assertGreater(seen[1][0], 0)
        self.assertTrue(seen[0][1])
        self.assertFalse(seen[1][1])

    def test_rescue_mode_starts_with_the_changed_request(self):
        seen = []

        def fake_once(mime, data, url, headers, schema, payload, timeout=40):
            seen.append(payload["temperature"])
            return {"success": True, "data": {"items": []}, "raw_content": "", "elapsed_time": 0.1}

        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service, "TYPHOON_OCR_APIKEY", ""
        ), patch.object(api_service, "_extract_document_intelligence_once", fake_once), patch.object(
            api_service.time, "sleep", lambda *_: None
        ):
            api_service.extract_document_intelligence(b"img", rescue=True)
        self.assertGreater(seen[0], 0)

    def test_batch_context_has_system_computed_totals(self):
        results = [
            {"success": True, "file_name": "a.jpg", "data": {"transfer_amount": 100, "store_name": "ร้าน X", "payer_name": "ก", "date": "2026-09-22"}},
            {"success": True, "file_name": "b.jpg", "data": {"transfer_amount": 250.5, "store_name": "ร้าน X", "payer_name": "ก", "date": "2026-09-23", "fee": 2}},
            {"success": False, "file_name": "c.jpg", "error": "x"},
        ]
        text = api_service.format_batch_context_for_qa(results)
        self.assertIn("350.50 บาท", text)
        self.assertIn("ร้าน X = 350.50", text)
        self.assertIn("อ่านไม่สำเร็จ 1 ฉบับ", text)

# ---------------------------------------------------------------------------------------------
# Hand-transcribed from the attached slip (1791352924463.jpg, Krungthai "จ่ายบิลสำเร็จ"), in the
# shape Typhoon OCR markdown usually has. This is a FIXTURE, not real Typhoon output.
KRUNGTHAI_BILL_SLIP = (
    "Krungthai กรุงไทย\n\nจ่ายบิลสำเร็จ\nรหัสอ้างอิง C202610076280134784481\n\n"
    "นาย ธันยบูรณ์ พ***\nกรุงไทย\nXXX-X-XX075-2\n\nChaCooL\n(010753600031501)\n\n"
    "| รหัสร้านค้า | KB000002265886 |\n| รหัสธุรกรรม | KPS004KB000002265886 |\n"
    "| จำนวนเงิน | 25.00 บาท |\n| ค่าธรรมเนียม | 0.00 บาท |\n| วันที่ทำรายการ | 07 ต.ค. 2569 - 13:02 |"
)


class SlipWithoutLabelsTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(api_service, "TYPHOON_MIN_INTERVAL", 0)
        p.start(); self.addCleanup(p.stop)
        api_service._typhoon_calls.clear()

    def _resp(self, content):
        from unittest.mock import MagicMock
        r = MagicMock(); r.status_code = 200
        r.json.return_value = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
        return r

    def _run(self, qwen_json, typhoon_text):
        qwen, typhoon = self._resp(qwen_json), self._resp(typhoon_text)

        def post(url, *args, **kwargs):
            return typhoon if url == api_service.TYPHOON_OCR_URL else qwen

        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service, "TYPHOON_OCR_APIKEY", "t"
        ), patch.object(api_service._http_session, "post", side_effect=post):
            return api_service.extract_document_intelligence(b"img")

    def test_layout_reads_payer_then_merchant_without_labels(self):
        self.assertEqual(
            api_service.names_from_ocr_layout(KRUNGTHAI_BILL_SLIP),
            {"payer_name": "นาย ธันยบูรณ์ พ***", "store_name": "ChaCooL"},
        )

    def test_merchant_id_and_codes_are_never_taken_as_names(self):
        found = api_service.names_from_ocr_layout("นาย ก ใจดี\nกสิกรไทย\nxxx-x-x1234-x\nChaCooL (010753600031501)\nรหัสร้านค้า KB000002265886")
        self.assertEqual(found["store_name"], "ChaCooL")

    def test_unknown_layout_is_not_guessed(self):
        self.assertEqual(api_service.names_from_ocr_layout("ใบเสร็จ 7-ELEVEN\nรวม 240.00"), {})
        self.assertEqual(api_service.names_from_ocr_layout("นาย ก\nนาย ข\nจำนวนเงิน 30.00"), {})
        self.assertEqual(api_service.names_from_ocr_layout(None), {})

    def test_labelled_slips_still_use_labels(self):
        self.assertEqual(
            api_service.names_from_ocr_text(TyphoonNameTests.SLIP),
            {"payer_name": "นาย ธันยบูรณ์ พ***", "store_name": "นาย ปรเมศ ไชยนาพันธุ์"},
        )

    def test_latin_transliteration_of_thai_payer_is_replaced_by_ocr_name(self):
        qwen = '{"data": {"transfer_amount": 25, "total": 25, "payer_name": "RAN YU BORN P", "store_name": "ChaCooL", "items": []}}'
        data = self._run(qwen, KRUNGTHAI_BILL_SLIP)["data"]
        self.assertEqual(data["payer_name"], "นาย ธันยบูรณ์ พ***")
        self.assertEqual(data["store_name"], "ChaCooL")
        self.assertIn("โครงสร้าง", data["name_source"])
        self.assertTrue(any("ไม่มีป้าย" in w for w in data["check_warnings"]))

    def test_name_missing_from_ocr_is_flagged_not_rewritten(self):
        data = {"transfer_amount": 25, "payer_name": "RAN YU BORN P", "store_name": "ChaCooL"}
        warnings = api_service.ground_names_in_ocr(data, KRUNGTHAI_BILL_SLIP)
        self.assertEqual(len(warnings), 1)
        self.assertIn("RAN YU BORN P", warnings[0])
        self.assertEqual(data["payer_name"], "RAN YU BORN P")

    def test_receipts_are_not_grounded(self):
        self.assertEqual(api_service.ground_names_in_ocr({"total": 10, "store_name": "ร้าน X"}, "อะไรก็ได้"), [])


class DocumentCheckTests(unittest.TestCase):
    GOOD = {"success": True, "data": {
        "store_name": "ChaCooL", "date": "2026-10-07", "transfer_amount": 25.0, "total": 25.0,
        "fee": 0.0, "debited_total": 25.0, "items": [], "check_warnings": []}}

    def _copy(self, **changes):
        import copy
        result = copy.deepcopy(self.GOOD)
        for key, value in changes.items():
            result["data"][key] = value
        return result

    def test_complete_document_is_checked_and_makes_no_api_call(self):
        with patch.object(api_service._http_session, "post", side_effect=AssertionError("network used")):
            check = api_service.check_document_result(self.GOOD)
        self.assertEqual(check["status"], "checked")
        self.assertEqual(check["issues"], [])

    def test_warnings_unreliable_names_and_equation_mismatch_need_review(self):
        self.assertEqual(api_service.check_document_result(self._copy(check_warnings=["วันที่ไม่ตรงกัน"]))["status"], "review")
        self.assertEqual(api_service.check_document_result(self._copy(payer_name="ไชยynaพิน"))["status"], "review")
        self.assertEqual(api_service.check_document_result(self._copy(debited_total=99.0))["status"], "review")

    def test_missing_amount_date_or_receiver_is_incomplete(self):
        self.assertEqual(api_service.check_document_result(self._copy(transfer_amount=None, total=None))["status"], "incomplete")
        self.assertEqual(api_service.check_document_result(self._copy(date="26"))["status"], "incomplete")
        self.assertEqual(api_service.check_document_result(self._copy(store_name="ไม่ระบุ"))["status"], "incomplete")

    def test_failed_and_unprocessed_results(self):
        self.assertEqual(api_service.check_document_result({"success": False, "error": "HTTP 500"})["status"], "error")
        self.assertEqual(api_service.check_document_result({})["status"], "not_processed")

    def test_user_verified_flag_is_not_changed_by_checking(self):
        result = self._copy()
        api_service.check_document_result(result)
        self.assertNotIn("verified", result)

    def test_batch_isolates_failures_reports_progress_and_reuses_unchanged_checks(self):
        results = [self._copy(), {"success": False, "error": "x"}, self._copy(date="26")]
        seen = []
        checks = api_service.check_batch_results(results, progress_callback=lambda d, t: seen.append((d, t)))
        self.assertEqual([c["status"] for c in checks], ["checked", "error", "incomplete"])
        self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])
        results[0]["batch_check"] = checks[0]
        with patch.object(api_service, "check_document_result", side_effect=AssertionError("recomputed")):
            again = api_service.check_batch_results(results[:1])
        self.assertIs(again[0], checks[0])
        results[0]["data"]["date"] = "2026-10-08"  # edited -> fingerprint changes -> recomputed
        self.assertNotEqual(results[0]["batch_check"]["fingerprint"], api_service.result_fingerprint(results[0]))

    def test_unexpected_exception_in_one_item_does_not_stop_the_batch(self):
        real = api_service.check_document_result
        calls = {"n": 0}

        def flaky(result):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return real(result)

        with patch.object(api_service, "check_document_result", side_effect=flaky):
            checks = api_service.check_batch_results([self._copy(), self._copy()])
        self.assertEqual([c["status"] for c in checks], ["error", "checked"])


# ---------------------------------------------------------------------------------------------
# Name grading, reconciliation and call-count / timing behaviour. All fixtures are hand-written OCR-style text
# in several slip styles (labelled, unlabelled, Thai/English, masked); none depends on one particular slip.
import io
import json


class NameGradingTests(unittest.TestCase):
    OCR = "โอนเงินสำเร็จ\nจาก\nนางสาว สมหญิง ใจดี\nไปยัง\nHappy Noodle Shop\nจำนวนเงิน 120.00 บาท"

    def test_exact_ignores_spaces_case_and_masking(self):
        for name in ("นางสาว สมหญิง ใจดี", "นางสาวสมหญิงใจดี", "happy noodle shop", "นางสาว สมหญิง ใจ***"):
            self.assertEqual(api_service.grade_name_against_ocr(name, self.OCR), "exact", name)

    def test_near_for_small_reading_difference(self):
        self.assertEqual(api_service.grade_name_against_ocr("นางสาว สมหญิง ใจดิ", self.OCR), "near")
        self.assertEqual(api_service.grade_name_against_ocr("Happy Noodle Shap", self.OCR), "near")

    def test_absent_for_unrelated_or_transliterated_name(self):
        self.assertEqual(api_service.grade_name_against_ocr("SOM YING JAIDEE", self.OCR), "absent")
        self.assertEqual(api_service.grade_name_against_ocr("Lucky Cafe", self.OCR), "absent")

    def test_unknown_when_no_name_or_ocr_too_short(self):
        self.assertEqual(api_service.grade_name_against_ocr(None, self.OCR), "unknown")
        self.assertEqual(api_service.grade_name_against_ocr("นาย ก", "บาท"), "unknown")
        self.assertEqual(api_service.grade_name_against_ocr("นาย ก", ""), "unknown")

    def test_grounding_warns_for_near_and_absent_only_and_records_grades(self):
        data = {"transfer_amount": 120, "payer_name": "SOM YING JAIDEE", "store_name": "Happy Noodle Shap"}
        warnings = api_service.ground_names_in_ocr(data, self.OCR)
        self.assertEqual(data["name_check"], {"payer_name": "absent", "store_name": "near"})
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("อักษรอังกฤษ" in w and "SOM YING JAIDEE" in w for w in warnings))
        self.assertEqual(data["payer_name"], "SOM YING JAIDEE")  # never rewritten
        clean = {"transfer_amount": 1, "payer_name": "นางสาว สมหญิง ใจดี", "store_name": "Happy Noodle Shop"}
        self.assertEqual(api_service.ground_names_in_ocr(clean, self.OCR), [])
        self.assertEqual(api_service.ground_names_in_ocr(data, ""), [])


class LayoutVariantsTests(unittest.TestCase):
    def test_other_bank_thai_receiver_without_labels(self):
        text = "โอนเงินสำเร็จ\nนาย วิชัย รักดี\nกสิกรไทย\nxxx-x-x4567-x\n⋮\nร้าน ครัวคุณแม่\nรหัสร้านค้า 12345678\nจำนวนเงิน 80.00"
        self.assertEqual(
            api_service.names_from_ocr_layout(text),
            {"payer_name": "นาย วิชัย รักดี", "store_name": "ร้าน ครัวคุณแม่"},
        )

    def test_english_names_and_markdown_noise(self):
        text = "## Transfer\n\n**Mr. John Smith**\nSCB\nXXX-X-X1234-X\n\n![icon](x.png)\nGreen Garden Cafe\n(0105560001234)"
        found = api_service.names_from_ocr_layout(text)
        self.assertEqual(found["store_name"], "Green Garden Cafe")
        self.assertIn("John Smith", found["payer_name"])

    def test_no_receiver_after_block_returns_only_payer(self):
        found = api_service.names_from_ocr_layout("นาย ก\nกรุงไทย\nXXX-X-XX075-2\nจำนวนเงิน 10.00\nวันที่ 1 ม.ค. 2569")
        self.assertEqual(found, {"payer_name": "นาย ก"})

    def test_labels_win_over_layout(self):
        text = "จาก\nนาย ก ใจดี\nกรุงไทย\nXXX-X-XX075-2\nไปยัง\nนาย ข รักดี"
        self.assertEqual(api_service.names_from_ocr_text(text)["store_name"], "นาย ข รักดี")


class ExtractionCallCountTests(unittest.TestCase):
    def setUp(self):
        for patcher in (patch.object(api_service, "TYPHOON_MIN_INTERVAL", 0),):
            patcher.start(); self.addCleanup(patcher.stop)
        api_service._typhoon_calls.clear()

    def _resp(self, content):
        from unittest.mock import MagicMock
        r = MagicMock(); r.status_code = 200
        r.json.return_value = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
        return r

    def _run(self, qwen_json, typhoon_text, typhoon_key="t", refine_json='{"payer_name":"นาย ก","receiver_name":"ร้าน ข"}', image=b"img"):
        calls = {"qwen": 0, "typhoon": 0}

        def post(url, *args, **kwargs):
            if url == api_service.TYPHOON_OCR_URL:
                calls["typhoon"] += 1
                return self._resp(typhoon_text)
            calls["qwen"] += 1
            return self._resp(qwen_json if calls["qwen"] == 1 else refine_json)

        with patch.object(api_service, "THAILLM_APIKEY", "k"), patch.object(
            api_service, "TYPHOON_OCR_APIKEY", typhoon_key
        ), patch.object(api_service._http_session, "post", side_effect=post):
            result = api_service.extract_document_intelligence(image)
        return result, calls

    Q = '{"raw_ocr": "x", "data": {"transfer_amount": 25, "total": 25, "payer_name": "นาย ก", "store_name": "ร้าน ข", "items": []}}'

    def test_labelled_slip_needs_one_vision_call(self):
        result, calls = self._run(self.Q, "จาก\nนาย ก\nไปยัง\nร้าน ข\nจำนวนเงิน 25.00 บาท")
        self.assertEqual(calls, {"qwen": 1, "typhoon": 1})
        self.assertEqual(result["data"]["name_source"], "typhoon-ocr")

    def test_names_confirmed_by_ocr_skip_second_vision_call(self):
        result, calls = self._run(self.Q, "โอนสำเร็จ\nนาย ก\nร้าน ข\nจำนวนเงิน 25.00 บาท")
        self.assertEqual(calls["qwen"], 1)
        self.assertEqual(result["data"]["name_source"], "qwen (ตรงกับ OCR)")
        self.assertEqual(result["data"]["name_check"], {"payer_name": "exact", "store_name": "exact"})
        self.assertFalse(result["timings"]["refine_used"])

    def test_names_not_in_ocr_still_get_second_look_and_are_flagged(self):
        q = self.Q.replace("นาย ก", "RAN YU").replace("ร้าน ข", "SHOP X")
        result, calls = self._run(q, "โอนสำเร็จ\nนาย สมชาย ใจดี\nร้าน ข้าวแกง\nจำนวนเงิน 25.00 บาท",
                                  refine_json='{"payer_name": "SOMCHAI J", "receiver_name": "KHAO GAENG"}')
        self.assertEqual(calls["qwen"], 2)
        data = result["data"]
        self.assertTrue(result["timings"]["refine_used"])
        self.assertEqual(data["name_model_reading"]["payer_name"], "RAN YU")
        self.assertTrue(any("ไม่พบในข้อความ OCR" in w for w in data["check_warnings"]))

    def test_thai_name_transliterated_by_model_is_replaced_by_ocr_and_original_kept(self):
        q = self.Q.replace("นาย ก", "SOMCHAI J")
        text = "นาย สมชาย ใจ***\nกรุงเทพ\nXXX-X-X9999-X\nร้าน ข\nจำนวนเงิน 25.00 บาท"
        data = self._run(q, text)[0]["data"]
        self.assertEqual(data["payer_name"], "นาย สมชาย ใจ***")
        self.assertEqual(data["name_model_reading"], {"payer_name": "SOMCHAI J"})
        self.assertTrue(any("ต่างจากข้อความ OCR" in w for w in data["check_warnings"]))

    def test_role_swap_between_model_and_ocr_is_flagged(self):
        data = self._run(self.Q, "จาก\nร้าน ข\nไปยัง\nนาย ก\nจำนวนเงิน 25.00 บาท")[0]["data"]
        self.assertEqual((data["payer_name"], data["store_name"]), ("ร้าน ข", "นาย ก"))
        self.assertTrue(any("สลับ" in w for w in data["check_warnings"]))

    def test_without_typhoon_key_second_call_is_kept_and_no_name_check(self):
        result, calls = self._run(self.Q, "", typhoon_key="")
        self.assertEqual(calls, {"qwen": 2, "typhoon": 0})
        self.assertNotIn("name_check", result["data"])

    def test_timings_are_recorded_without_secrets(self):
        result, _ = self._run(self.Q, "จาก\nนาย ก\nไปยัง\nร้าน ข")
        timings = result["timings"]
        for key in ("prepare_s", "vision_s", "vision_calls", "typhoon_wait_s", "total_s"):
            self.assertIn(key, timings)
        self.assertEqual(timings["vision_calls"], 1)
        self.assertTrue(all(isinstance(v, (int, float, bool, str)) for v in timings.values()))
        self.assertLess(len(json.dumps(timings)), 300)  # numbers/flags only: no keys, no document content

    def test_image_is_prepared_once_and_shared_with_typhoon(self):
        real = api_service.optimize_image_for_ocr
        with patch.object(api_service, "optimize_image_for_ocr", side_effect=real) as optimize:
            self._run(self.Q, "จาก\nนาย ก\nไปยัง\nร้าน ข")
        self.assertEqual(optimize.call_count, 1)

    def test_receipt_does_not_consume_typhoon_quota_while_waiting(self):
        import time as _time
        now = _time.monotonic()
        api_service._typhoon_calls.extend([now] * api_service.TYPHOON_MAX_PER_MINUTE)  # quota exhausted
        receipt = '{"raw_ocr": "x", "data": {"total": 40, "store_name": "ร้าน", "items": []}}'
        started = _time.monotonic()
        result, calls = self._run(receipt, "ไม่ควรถูกเรียก")
        self.assertLess(_time.monotonic() - started, 5)
        self.assertEqual(calls["typhoon"], 0)
        self.assertEqual(len(api_service._typhoon_calls), api_service.TYPHOON_MAX_PER_MINUTE)
        self.assertTrue(result["success"])

    def test_low_resolution_image_is_flagged(self):
        from PIL import Image
        small = io.BytesIO(); Image.new("RGB", (300, 500), "white").save(small, "JPEG")
        self.assertIn("ความละเอียดต่ำ", api_service.image_quality_warning(small.getvalue()))
        big = io.BytesIO(); Image.new("RGB", (1000, 1400), "white").save(big, "JPEG")
        self.assertIsNone(api_service.image_quality_warning(big.getvalue()))
        self.assertIsNone(api_service.image_quality_warning(b"not an image"))

    def test_tall_screenshot_keeps_more_pixels_than_before(self):
        from PIL import Image
        shot = io.BytesIO(); Image.new("RGB", (1080, 2400), "white").save(shot, "JPEG")
        out, _ = api_service.optimize_image_for_ocr(shot.getvalue(), max_dim=api_service.OCR_MAX_DIM)
        self.assertEqual(Image.open(io.BytesIO(out)).size, (810, 1800))


class BatchBehaviourTests(unittest.TestCase):
    DOCS = [("a.jpg", b"AAA", "image/jpeg"), ("b.jpg", b"BBB", "image/jpeg"), ("a-copy.jpg", b"AAA", "image/jpeg"), ("c.jpg", b"CCC", "image/jpeg")]

    def _fake(self, fail=()):
        seen = []

        def fake(image_bytes, mime_type, attempts, rescue):
            seen.append(image_bytes)
            if image_bytes in fail:
                return {"success": False, "error": "boom"}
            return {"success": True, "data": {"store_name": image_bytes.decode()}, "raw_content": ""}
        return seen, fake

    def test_identical_files_are_read_once_and_copied_in_order(self):
        seen, fake = self._fake()
        with patch.object(api_service, "extract_document_intelligence", side_effect=fake):
            results = api_service.extract_documents_batch(self.DOCS, max_workers=2)
        self.assertEqual(sorted(seen), [b"AAA", b"BBB", b"CCC"])
        self.assertEqual([r["file_name"] for r in results], ["a.jpg", "b.jpg", "a-copy.jpg", "c.jpg"])
        self.assertEqual(results[2]["data"], results[0]["data"])
        self.assertIsNot(results[2], results[0])

    def test_failure_keeps_other_results_and_is_counted(self):
        _, fake = self._fake(fail={b"BBB"})
        details = []
        with patch.object(api_service, "extract_document_intelligence", side_effect=fake):
            results = api_service.extract_documents_batch(self.DOCS, max_workers=1, detail_callback=lambda *a: details.append(a))
        self.assertEqual([r["success"] for r in results], [True, False, True, True])
        self.assertEqual(details[0], (0, 1, 0, 4))
        self.assertEqual(details[-1][0], 4)   # done
        self.assertEqual(details[-1][2], 1)   # failed
        self.assertEqual(details[-1][3], 4)   # total

    def test_each_finished_result_is_handed_over_immediately(self):
        _, fake = self._fake()
        got = {}
        with patch.object(api_service, "extract_document_intelligence", side_effect=fake):
            api_service.extract_documents_batch(self.DOCS, max_workers=2, result_callback=lambda i, r: got.__setitem__(i, r["file_name"]))
        self.assertEqual(got, {0: "a.jpg", 1: "b.jpg", 2: "a-copy.jpg", 3: "c.jpg"})

    def test_interruption_cancels_files_that_have_not_started(self):
        seen, fake = self._fake()

        class Stop(BaseException):  # like Streamlit's rerun/stop exceptions
            pass

        def progress(done, total):
            raise Stop()

        docs = [(f"{i}.jpg", bytes([65 + i]) * 3, "image/jpeg") for i in range(8)]
        with patch.object(api_service, "extract_document_intelligence", side_effect=fake):
            with self.assertRaises(Stop):
                api_service.extract_documents_batch(docs, max_workers=1, progress_callback=progress)
        self.assertLess(len(seen), 8)

    def test_document_hash_is_stable_and_content_based(self):
        self.assertEqual(api_service.document_hash(b"x"), api_service.document_hash(b"x"))
        self.assertNotEqual(api_service.document_hash(b"x"), api_service.document_hash(b"y"))


# ---------------------------------------------------------------------------------------------
# REAL (noisy) Tesseract-Thai OCR of two actual Krungthai bill slips - not Typhoon output, but genuine OCR text with
# icon glyphs, a masked account read as "2%%%-%-%%075-2" and a Latin merchant name it could not read.
REAL_NOISY_OCR_SLIPS = [
    '”.  ”  ๆฯเทลเ!\n๕ ๕๑ %ฯ๓ซว .\n!     /         |\n๕   จ่ายบิลสําเร็จ                        โตไต]\nรหัสอฮ้างอิง 020261008628120844120           อ\n[ต]\n   นาย ธันยบูรณ์ พ **\nอ      กรุงไทย\nว     2%%%-%-%%075-2\n“พง\n.๐๑. แผอบแผลพ\n(010753600037406)\nหมายเลขร้านค้า1                         006001031257777\nเลขที่อ้างอิง2                     20240927000076740000\nจํานวนเงิน                        40 00 บาท\nค่าธรรมเนียม                                       0.00 บาท\nวันที่ทํารายการ                           08 ต.ค. 2569 - 20:20',
    '” . ๕ผู . «<แบนทตเาอ\n 2๕ /” ง%ซๆิต     เสอ      บ\n”          เณ๕     า\n!     /          |\n๕   จ่ายบิลสําเร็จ                          [ไร]\nรหัสอ้างอิง (20261007628013478481          ๓๒\n[ต เร ไฟ่\n   นาย ธันยบูรณ์ พ **\nอ      กรุงไทย\nว      2%%%-%-%%075-2\n“พง\n๑๑๑ แฝกล6001\n(010753600031501)\nรหัสร้านค้า                                6๕68000002265886\nรหัสธุรกรรม                     60500468000002265886\nจํานวนเงิน                                       25.00 บาท\nค่าธรรมเนียม                                       0.00 บาท\nวันที่ทํารายการ                              07 ต.ค. 2569 - 13:02',
]


class RealNoisyOcrTests(unittest.TestCase):
    def test_payer_is_read_from_real_noisy_ocr_and_junk_receiver_is_rejected(self):
        for text in REAL_NOISY_OCR_SLIPS:
            found = api_service.names_from_ocr_layout(text)
            self.assertEqual(found, {"payer_name": "นาย ธันยบูรณ์ พ **"})  # no junk receiver invented

    def test_masked_account_fingerprint_survives_ocr_noise(self):
        for text in REAL_NOISY_OCR_SLIPS:
            self.assertEqual(api_service.account_signature(api_service.account_from_ocr_layout(text)), "0752")
        self.assertEqual(api_service.account_signature("XXX-X-XX075-2"), "0752")
        self.assertIsNone(api_service.account_signature("XXX"))
        self.assertIsNone(api_service.account_signature(None))

    def test_bank_and_account_on_one_line_and_icon_noise(self):
        text = "อ      นาย วิชัย รักดี\nกสิกรไทย  XXX-X-X4567-X\n⋮\nร้าน ครัวคุณแม่\n(0105560001234)\nจำนวนเงิน 80.00"
        self.assertEqual(
            api_service.names_from_ocr_layout(text),
            {"payer_name": "นาย วิชัย รักดี", "store_name": "ร้าน ครัวคุณแม่"},
        )

    def test_receiver_with_merchant_id_beats_earlier_weak_candidate(self):
        text = "นาย ก ใจดี\nกรุงไทย\nXXX-X-XX075-2\nสำเร็จแล้ว ขอบคุณ\nGreen Garden Cafe\n(010753600031501)"
        self.assertEqual(api_service.names_from_ocr_layout(text)["store_name"], "Green Garden Cafe")

    def test_plausibility_filter(self):
        for junk in (".๐๑. แผอบแผลพ", "“พง", "ab", "|||| ---"):
            self.assertFalse(api_service._plausible_name(junk), junk)
        for good in ("นาย ธันยบูรณ์ พ***", "PAN DUANGJAI", "Yaowarat Pork Leg", "ChaCooL"):
            self.assertTrue(api_service._plausible_name(good), good)


class KnownNamesTests(unittest.TestCase):
    KNOWN = [
        {"role": "payer", "name": "นาย ธันยบูรณ์ พ***", "account": "XXX-X-XX075-2"},
        {"role": "receiver", "name": "ร้านข้าวแกงป้าแดง"},
        {"role": "receiver", "name": "Yaowarat Pork Leg"},
    ]

    def test_skeleton_ignores_thai_marks_spacing_and_masking(self):
        self.assertEqual(api_service.thai_skeleton("นาย ธันย์บุรณ์ พ***"), api_service.thai_skeleton("นายธันยบูรณ์พ"))
        self.assertNotEqual(api_service.thai_skeleton("นาย สมชาย"), api_service.thai_skeleton("นาย สมหญิง"))

    def test_match_by_account_even_when_name_is_garbled(self):
        entry, why = api_service.match_known_name("รณเย่บ รัน", self.KNOWN, "payer", "2%%%-%-%%075-2")
        self.assertEqual((entry["name"], why), ("นาย ธันยบูรณ์ พ***", "account"))

    def test_match_by_spelling_and_no_match_without_evidence(self):
        self.assertEqual(api_service.match_known_name("นาย ธันย์บุรณ์ พ***", self.KNOWN, "payer")[1], "spelling")
        self.assertIsNone(api_service.match_known_name("รณเย่บ รัน", self.KNOWN, "payer"))          # garbled, no account
        self.assertIsNone(api_service.match_known_name("นาย สมชาย ใจดี", self.KNOWN, "payer", "XXX-X-XX999-1"))
        self.assertIsNone(api_service.match_known_name("Yaowarat Pork Leg", self.KNOWN, "payer"))    # roles are separate

    def test_apply_replaces_name_keeps_original_and_warns(self):
        data = {"transfer_amount": 40, "payer_name": "รณเย่บ รัน", "payer_account": "XXX-X-XX075-2",
                "store_name": "Yaowarat Pork Lag", "name_source": "qwen (Typhoon ไม่พบป้าย จาก/ไปยัง)"}
        self.assertTrue(api_service.apply_known_names(data, self.KNOWN))
        self.assertEqual(data["payer_name"], "นาย ธันยบูรณ์ พ***")
        self.assertEqual(data["store_name"], "Yaowarat Pork Leg")
        self.assertEqual(data["name_model_reading"], {"payer_name": "รณเย่บ รัน", "store_name": "Yaowarat Pork Lag"})
        self.assertEqual(data["name_check"], {"payer_name": "known", "store_name": "known"})
        self.assertTrue(any("เลขบัญชีตรงกัน" in w for w in data["check_warnings"]))
        self.assertIn("ชื่อที่ผู้ใช้ยืนยัน", data["name_source"])
        self.assertIn("นาย ธันยบูรณ์ พ***", data["ocr_text"])

    def test_apply_does_nothing_for_unrelated_names_receipts_or_empty_list(self):
        data = {"transfer_amount": 40, "payer_name": "นาย สมชาย ใจดี", "store_name": "ร้านอื่น"}
        self.assertFalse(api_service.apply_known_names(data, self.KNOWN))
        self.assertEqual(data["payer_name"], "นาย สมชาย ใจดี")
        self.assertFalse(api_service.apply_known_names({"total": 5, "store_name": "ร้านข้าวแกงป้าแดง"}, self.KNOWN))
        self.assertFalse(api_service.apply_known_names(data, []))

    def test_same_name_is_marked_known_without_warning(self):
        data = {"transfer_amount": 40, "payer_name": "นาย ธันยบูรณ์ พ***", "store_name": "x"}
        self.assertFalse(api_service.apply_known_names(data, self.KNOWN))
        self.assertEqual(data["name_check"]["payer_name"], "known")
        self.assertNotIn("check_warnings", data)


class TyphoonRetryTests(unittest.TestCase):
    def setUp(self):
        for patcher in (patch.object(api_service, "TYPHOON_MIN_INTERVAL", 0), patch.object(api_service, "TYPHOON_OCR_APIKEY", "t"),
                        patch.object(api_service.time, "sleep", lambda *_: None)):
            patcher.start(); self.addCleanup(patcher.stop)
        api_service._typhoon_calls.clear()

    def _resp(self, status, content="ข้อความ OCR"):
        from unittest.mock import MagicMock
        r = MagicMock(); r.status_code = status; r.headers = {}
        r.json.return_value = {"choices": [{"message": {"content": content}}]}
        return r

    def test_server_error_is_retried_once_then_succeeds(self):
        with patch.object(api_service._http_session, "post", side_effect=[self._resp(503), self._resp(200)]) as post:
            self.assertEqual(api_service._typhoon_ocr_request(b"img"), ("ข้อความ OCR", "ok"))
        self.assertEqual(post.call_count, 2)

    def test_persistent_server_error_gives_up_after_one_retry(self):
        with patch.object(api_service._http_session, "post", side_effect=[self._resp(500), self._resp(500), self._resp(200)]) as post:
            self.assertEqual(api_service._typhoon_ocr_request(b"img"), (None, "http_error"))
        self.assertEqual(post.call_count, 2)

    def test_connection_error_retried_once_but_timeout_is_not(self):
        import requests
        with patch.object(api_service._http_session, "post", side_effect=[requests.exceptions.ConnectionError(), self._resp(200)]) as post:
            self.assertEqual(api_service._typhoon_ocr_request(b"img")[1], "ok")
        self.assertEqual(post.call_count, 2)
        api_service._typhoon_calls.clear()
        with patch.object(api_service._http_session, "post", side_effect=requests.exceptions.Timeout()) as post:
            self.assertEqual(api_service._typhoon_ocr_request(b"img"), (None, "error"))
        self.assertEqual(post.call_count, 1)

    def test_client_error_is_not_retried(self):
        with patch.object(api_service._http_session, "post", side_effect=[self._resp(422)]) as post:
            self.assertEqual(api_service._typhoon_ocr_request(b"img"), (None, "http_error"))
        self.assertEqual(post.call_count, 1)


class PayerAccountFlowTests(unittest.TestCase):
    def test_payer_account_comes_from_ocr_and_names_from_real_noisy_ocr(self):
        helper = ExtractionCallCountTests("test_labelled_slip_needs_one_vision_call")
        helper.setUp()
        q = '{"data": {"transfer_amount": 40, "total": 40, "payer_name": "รณเย่บ รัน", "store_name": "PAN DUANGJAI", "payer_account": "XXX-X-XX075-2", "items": []}}'
        result, calls = helper._run(q, REAL_NOISY_OCR_SLIPS[0])
        data = result["data"]
        self.assertEqual(data["payer_name"], "นาย ธันยบูรณ์ พ **")
        self.assertEqual(data["name_model_reading"], {"payer_name": "รณเย่บ รัน"})
        self.assertEqual(data["payer_account"], "2%%%-%-%%075-2")
        self.assertEqual(data["store_name"], "PAN DUANGJAI")  # junk OCR receiver was rejected, model's kept
        self.assertEqual(api_service.account_signature(data["payer_account"]), "0752")
        helper.doCleanups()