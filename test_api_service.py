import unittest
import os
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
            api_service._http_session, "post", side_effect=[first]
        ) as post:
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