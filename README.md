# Wongpanit Price Dashboard

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
GITHUB_DATA_DIR = "data"
```

4. Token ต้องมีสิทธิ์อ่านและเขียน Contents ของ repository นั้นเท่านั้น
5. กด Update ครั้งแรกด้วย ID สูงสุดที่ต้องการ ระบบจะสร้าง/อัปเดตไฟล์:
   - `data/announcements.csv` ประวัติราคา
   - `data/state.csv` ID ล่าสุดที่ตรวจแล้ว

หลังจากนั้นการกด Update จะเริ่มจาก ID ถัดไปใน `state.csv` และ commit ข้อมูลกลับ GitHub อัตโนมัติ

## หมายเหตุ

- ต้องเปิดแอปผ่าน Streamlit ไม่ใช่ `python scrap.py`
- ถ้าไม่มี GitHub secrets การเขียนไฟล์บน Streamlit Cloud อาจหายเมื่อแอป restart จึงควรตั้งค่า GitHub persistence ก่อนใช้งานจริง
- ห้าม commit token ลง source code หรือไฟล์ใน repository
