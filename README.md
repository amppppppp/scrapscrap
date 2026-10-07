# Wongpanit Price Dashboard

//////
## Run Website ใช้ https://scrapscrap.streamlit.app/
/////
Streamlit dashboard สำหรับเก็บประวัติราคาจาก Wongpanit โดยตรวจเฉพาะ ID ใหม่และไม่เพิ่มประกาศซ้ำ

## รันในเครื่อง

```powershell
cd "d:\VScode\scrap price"
py -3.13 -m pip install -r requirements.txt
py -3.13 -m streamlit run scrap.py
```

ถ้าไม่ได้ตั้งค่า GitHub secrets แอปจะใช้ `announcements.csv` และ `state.csv` ในโฟลเดอร์เดียวกับ `scrap.py`

## Deploy บน Streamlit Community Cloud

1. สร้าง GitHub repository แล้ว push ไฟล์ `scrap.py` และ `requirements.txt` ขึ้นไป
2. เปิด [Streamlit Community Cloud](https://share.streamlit.io/) แล้วเลือก repository, branch และไฟล์ `scrap.py`
3. ตั้งค่า Secrets ของแอปเป็น TOML ดังนี้:

```toml
GITHUB_TOKEN = "ใส่_token_ที่นี่"
GITHUB_REPO = "username/repository"
GITHUB_BRANCH = "main"
```

4. Token ต้องมีสิทธิ์อ่านและเขียน Contents ของ repository นั้นเท่านั้น โดยค่าเริ่มต้นระบบจะอ่านและบันทึก `announcements.csv` กับ `state.csv` ที่ root ของ repository หากต้องการเก็บในโฟลเดอร์ `data` ให้เพิ่ม `GITHUB_DATA_DIR = "data"` ใน Secrets
5. กด Update ครั้งแรกด้วย ID สูงสุดที่ต้องการ ระบบจะสร้าง/อัปเดตไฟล์:
   - `announcements.csv` ประวัติราคา
   - `state.csv` ID ล่าสุดที่ตรวจแล้ว

หลังจากนั้นการกด Update จะเริ่มจาก ID ถัดไปของสินค้าที่เลือก โดยเก็บสถานะแยกสินค้าใน `state.csv` และ commit ข้อมูลกลับ GitHub อัตโนมัติ ข้อมูลใน `announcements.csv` จะถูกโหลดก่อน และหากสินค้าที่เลือกยังไม่มีข้อมูล ระบบจะดึงข้อมูลเฉพาะสินค้านั้น

## หมายเหตุ

- ต้องเปิดแอปผ่าน Streamlit ไม่ใช่ `python scrap.py`
- ถ้าไม่มี GitHub secrets แอปจะแสดงคำเตือนและใช้ไฟล์ในเครื่อง ซึ่งข้อมูลอาจหายเมื่อ Streamlit Cloud restart จึงต้องตั้ง `GITHUB_TOKEN` และ `GITHUB_REPO` ก่อนใช้งานจริง
- ห้าม commit token ลง source code หรือไฟล์ใน repository
