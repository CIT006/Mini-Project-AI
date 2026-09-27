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


if __name__ == "__main__":
    unittest.main()