# ThaiDocAI · ตรวจเอกสารและยอดชำระอัจฉริยะ (Smart Document & Receipt Inspector)
Mini Project สำหรับวิชา Machine Learning (CIT0013)

ระบบผู้ช่วยตรวจสอบและวิเคราะห์เอกสาร ใบเสร็จ และสลิปการเงินภาษาไทยอัจฉริยะ ผสานพลังของ **Thai LLM**, **Typhoon OCR** และ **AI For Thai**

---

## 🎯 ฟีเจอร์เด่นของระบบ
1. **Multimodal OCR & Document Intelligence:** สแกนภาพใบเสร็จ/สลิป ดึงข้อความ ถอดตารางรายการสินค้า ราคา วันที่ ยอดรวมสุทธิ และรองรับการประมวลผลเป็นชุด (Batch Upload) ความเร็วสูง
2. **AI Business, Tax & Anomaly Analytics (วิเคราะห์ธุรกิจ & ภาษี AI):**
   - 🏷️ **จัดหมวดหมู่ค่าใช้จ่าย & ผังบัญชีอัตโนมัติ:** แนะนำรหัสบัญชี (Account Code) และสร้าง Narration สำหรับลงสมุดรายวันทันที
   - 📋 **ประเมินสิทธิ์ภาษี & การเบิกจ่าย:** ตรวจสอบเลขผู้เสียภาษี 13 หลัก และประเมินสิทธิ์การเคลมภาษีซื้อ (VAT 7%) ตามเกณฑ์สรรพากร
   - 🛡️ **ตรวจจับความเสี่ยงทุจริต & บิลผิดปกติ (Fraud Detection):** ตรวจสอบวันที่ย้อนหลัง/ในอนาคต, ยอดเงินผิดสังเกต, สมการภาษี, และตรวจจับบิลซ้ำซ้อนในชุด
   - 💡 **Executive Insights:** สรุปสาระสำคัญสำหรับผู้บริหารและข้อแนะนำในการประหยัดต้นทุน
3. **Interactive Document Q&A (ถาม-ตอบเอกสารอัจฉริยะ):** ถามข้อมูลใดๆ จากเอกสารได้ทุกมิติ ทั้งรายการสินค้า ราคาสูงสุด/ต่ำสุด ผลต่างยอดเงิน ผู้โอน ผู้รับเงิน หรือช่องทางการชำระ
4. **Financial Logic Audit:** ตรวจความถูกต้องของสมการตัวเลข ยอดก่อนภาษี + VAT = ยอดสุทธิ
5. **Thai Text-to-Speech (TTS):** สังเคราะห์เสียงพูดภาษาไทยแจ้งสถานะการประมวลผลผ่านบริการ **AI For Thai (VAJA)**
6. **Sentiment Analysis:** วิเคราะห์อารมณ์และโทนข้อความในเอกสารผ่าน **AI For Thai (SSense)**
7. **Multi-format Export:** ส่งออกข้อมูลที่ผ่านการตรวจทานแล้วเป็น **Excel (.xlsx)**, **CSV (UTF-8 BOM)** และ **JSON**

---

## 🛠️ โครงสร้างโปรเจกต์
- [app.py](app.py): หน้าเว็บ UI พัฒนาด้วย Streamlit แบ่งส่วนการทำงาน ตรวจเอกสาร, วิเคราะห์ธุรกิจ & ภาษี AI, แชตถาม-ตอบ และเครื่องมือเสริม
- [api_service.py](api_service.py): โมดูลหลักเชื่อมต่อ API (ThaiLLM, Typhoon OCR และ AI For Thai) พร้อมระบบสกัดข้อมูล วิเคราะห์บัญชี และภาษี
- [requirements.txt](requirements.txt): รายการไลบรารีที่จำเป็น

---

## 🚀 วิธีติดตั้งและรันโปรเจกต์
### เปิดแอปบน Windows
ใส่ API key ที่ใช้งานได้ในไฟล์ local [.streamlit/secrets.toml](.streamlit/secrets.toml) ก่อน จากนั้นดับเบิลคลิก [run_app.bat](run_app.bat) สคริปต์จะสร้าง virtual environment, ติดตั้ง dependencies และเปิด Streamlit ให้อัตโนมัติ

```toml
THAILLM_APIKEY = "ใส่คีย์ ThaiLLM"
AIFORTHAI_APIKEY = "ใส่คีย์ AI For Thai"
TYPHOON_OCR_API_KEY = "ใส่คีย์ Typhoon OCR (ถ้ามี)"
```

### รันด้วยตนเอง
```powershell
pip install -r requirements.txt
python -m streamlit run app.py
```
เปิด `http://localhost:8501` ในเบราว์เซอร์
