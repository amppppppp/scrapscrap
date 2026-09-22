from __future__ import annotations

import base64
import hashlib
import io
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup


APP_DIR = Path(__file__).resolve().parent
ANNOUNCEMENTS_FILE = APP_DIR / "announcements.csv"
STATE_FILE = APP_DIR / "state.csv"
START_ID = 2800
DEFAULT_MAX_ID = 2875
URL_TEMPLATE = "https://wongpanit.com/print_history_price/{id}"
ITEMS = {
    "ทองเหลืองหนา": "ทองเหลืองหนา",
    "เหล็กบางไม่ซอย": "เหล็กบางไม่ซอย",
    "เหล็กหนาไม่ซอย": "เหล็กหนาไม่ซอย",
}
MONTHS = {
    "มกราคม": 1,
    "กุมภาพันธ์": 2,
    "มีนาคม": 3,
    "เมษายน": 4,
    "พฤษภาคม": 5,
    "มิถุนายน": 6,
    "กรกฎาคม": 7,
    "กรกฏาคม": 7,
    "สิงหาคม": 8,
    "กันยายน": 9,
    "ตุลาคม": 10,
    "พฤศจิกายน": 11,
    "ธันวาคม": 12,
}
ANNOUNCEMENT_COLUMNS = [
    "announcement_key",
    "source_id",
    "published_date",
    "item",
    "price",
    "url",
    "scraped_at",
]


def github_setting(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
    except (FileNotFoundError, KeyError, AttributeError):
        value = default
    return str(value or os.getenv(name, default)).strip()


def github_configured() -> bool:
    return bool(github_setting("GITHUB_TOKEN") and github_setting("GITHUB_REPO"))


def github_file_path(filename: str) -> str:
    data_dir = github_setting("GITHUB_DATA_DIR", "data").strip("/")
    return f"{data_dir}/{filename}" if data_dir else filename


def github_api_url(filename: str) -> str:
    repo = github_setting("GITHUB_REPO")
    return f"https://api.github.com/repos/{repo}/contents/{github_file_path(filename)}"


def github_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_setting('GITHUB_TOKEN')}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_read_file(filename: str) -> tuple[bytes | None, str | None]:
    response = requests.get(
        github_api_url(filename),
        headers=github_headers(),
        params={"ref": github_setting("GITHUB_BRANCH", "main")},
        timeout=20,
    )
    if response.status_code == 404:
        return None, None
    response.raise_for_status()
    payload = response.json()
    content = base64.b64decode(payload["content"].replace("\n", ""))
    return content, payload.get("sha")


def github_write_file(filename: str, content: bytes, message: str) -> None:
    _, sha = github_read_file(filename)
    payload = {
        "message": message,
        "content": base64.b64encode(content).decode("ascii"),
        "branch": github_setting("GITHUB_BRANCH", "main"),
    }
    if sha:
        payload["sha"] = sha
    response = requests.put(
        github_api_url(filename), headers=github_headers(), json=payload, timeout=20
    )
    response.raise_for_status()


def empty_announcements() -> pd.DataFrame:
    return pd.DataFrame(columns=ANNOUNCEMENT_COLUMNS)


def load_announcements() -> pd.DataFrame:
    if github_configured():
        content, _ = github_read_file("announcements.csv")
        if content is None:
            return empty_announcements()
        frame = pd.read_csv(io.BytesIO(content), dtype=str).fillna("")
    else:
        if not ANNOUNCEMENTS_FILE.exists():
            return empty_announcements()
        frame = pd.read_csv(ANNOUNCEMENTS_FILE, dtype=str).fillna("")
    for column in ANNOUNCEMENT_COLUMNS:
        if column not in frame:
            frame[column] = ""
    return frame[ANNOUNCEMENT_COLUMNS]


def save_announcements(frame: pd.DataFrame) -> None:
    content = frame[ANNOUNCEMENT_COLUMNS].to_csv(index=False).encode("utf-8-sig")
    if github_configured():
        github_write_file("announcements.csv", content, "Update Wongpanit price history")
    else:
        ANNOUNCEMENTS_FILE.write_bytes(content)


def load_last_id() -> int:
    if github_configured():
        content, _ = github_read_file("state.csv")
        if content is None:
            return START_ID - 1
        state = pd.read_csv(io.BytesIO(content), dtype=str)
    else:
        if not STATE_FILE.exists():
            return START_ID - 1
        state = pd.read_csv(STATE_FILE, dtype=str)
    if state.empty or "last_scanned_id" not in state:
        return START_ID - 1
    try:
        return int(state.iloc[0]["last_scanned_id"])
    except (TypeError, ValueError):
        return START_ID - 1


def save_last_id(last_id: int) -> None:
    content = pd.DataFrame(
        [{"last_scanned_id": last_id, "updated_at": datetime.now().isoformat(timespec="seconds")}]
    ).to_csv(index=False).encode("utf-8-sig")
    if github_configured():
        github_write_file("state.csv", content, f"Save Wongpanit scan state at ID {last_id}")
    else:
        STATE_FILE.write_bytes(content)


def parse_thai_date(text: str) -> str | None:
    compact_text = re.sub(r"\s+", " ", text).strip()
    pattern = r"(?:ที่\s*)?(\d{1,2})\s*(" + "|".join(MONTHS) + r")\s*(\d{4})"
    match = re.search(pattern, compact_text)
    if not match:
        return None
    day, month_name, buddhist_year = match.groups()
    try:
        date_value = datetime(int(buddhist_year) - 543, MONTHS[month_name], int(day))
    except ValueError:
        return None
    return date_value.strftime("%Y-%m-%d")


def extract_price(tables, target_item: str) -> str | None:
    for table in tables:
        cells = table.find_all("td")
        for index in range(0, len(cells) - 1, 2):
            name = cells[index].get_text(" ", strip=True)
            price = cells[index + 1].get_text(" ", strip=True)
            if name == target_item and price:
                return price
    return None


def announcement_key(published_date: str, item: str, price: str) -> str:
    raw_value = "|".join((published_date, item, re.sub(r"\s+", "", price)))
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:20]


def scrape_page(page_id: int, target_item: str) -> dict | None:
    url = URL_TEMPLATE.format(id=page_id)
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return None
    published_date = parse_thai_date(tables[0].get_text(" ", strip=True))
    price = extract_price(tables, target_item)
    if not published_date or not price:
        return None
    return {
        "announcement_key": announcement_key(published_date, target_item, price),
        "source_id": str(page_id),
        "published_date": published_date,
        "item": target_item,
        "price": price,
        "url": url,
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
    }


def update_prices(first_id: int, max_id: int, existing: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if max_id < first_id:
        raise ValueError("Max ID ต้องมากกว่าหรือเท่ากับ ID เริ่มต้น")
    known_keys = set(existing["announcement_key"].astype(str))
    new_rows = []
    duplicate_count = 0
    error_count = 0
    scanned_count = 0
    for page_id in range(first_id, max_id + 1):
        scanned_count += 1
        for target_item in ITEMS.values():
            try:
                row = scrape_page(page_id, target_item)
                if row is None:
                    continue
                if row["announcement_key"] in known_keys:
                    duplicate_count += 1
                    continue
                known_keys.add(row["announcement_key"])
                new_rows.append(row)
            except requests.RequestException:
                error_count += 1
            except Exception:
                error_count += 1
    if new_rows:
        existing = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
        existing = existing.drop_duplicates(subset=["announcement_key"], keep="first")
        existing = existing.sort_values(["published_date", "source_id"]).reset_index(drop=True)
    return existing, {
        "scanned": scanned_count,
        "new": len(new_rows),
        "duplicates": duplicate_count,
        "errors": error_count,
    }


def render_dashboard() -> None:
    st.set_page_config(page_title="Wongpanit Price Dashboard", page_icon="📈", layout="wide")
    st.title("Wongpanit ราคาของเก่า")
    st.caption("อัปเดตเฉพาะ ID ใหม่ และไม่สร้างประวัติซ้ำเมื่อหน้าเว็บแสดงประกาศล่าสุดเดิม")

    existing = load_announcements()
    last_scanned_id = load_last_id()
    with st.sidebar:
        st.header("ตั้งค่า Update")
        target_item = st.selectbox("สินค้า", list(ITEMS))
        default_start = max(START_ID, last_scanned_id + 1)
        st.number_input("ID เริ่มต้นรอบถัดไป", value=default_start, min_value=START_ID, disabled=True)
        max_id = st.number_input("ID สูงสุดที่จะตรวจ", value=max(DEFAULT_MAX_ID, default_start), min_value=START_ID, step=1)
        update_clicked = st.button("Update", type="primary", use_container_width=True)
        st.divider()
        st.metric("ID ล่าสุดที่ตรวจแล้ว", last_scanned_id)
        st.caption(f"เก็บข้อมูลที่: {ANNOUNCEMENTS_FILE.name}")

    if update_clicked:
        if max_id < default_start:
            st.error("ID สูงสุดต้องมากกว่า ID เริ่มต้น")
        else:
            with st.spinner(f"กำลังตรวจ ID {default_start} ถึง {max_id}..."):
                updated, summary = update_prices(default_start, int(max_id), existing)
                save_announcements(updated)
                save_last_id(int(max_id))
                existing = updated
            st.success(
                f"อัปเดตเสร็จแล้ว: ตรวจ {summary['scanned']} ID, "
                f"เพิ่มใหม่ {summary['new']} รายการ, ซ้ำ {summary['duplicates']} รายการ, "
                f"ผิดพลาด {summary['errors']} รายการ"
            )

    item_data = existing[existing["item"] == target_item].copy()
    st.subheader(f"ประวัติราคา: {target_item}")
    if item_data.empty:
        st.info("ยังไม่มีข้อมูล กด Update เพื่อเริ่มดึงข้อมูล")
        return
    item_data["price_numeric"] = pd.to_numeric(
        item_data["price"].str.replace(",", "", regex=False), errors="coerce"
    )
    latest = item_data.sort_values("published_date").iloc[-1]
    metric_columns = st.columns(3)
    metric_columns[0].metric("ราคาล่าสุด", latest["price"])
    metric_columns[1].metric("วันที่ประกาศ", latest["published_date"])
    metric_columns[2].metric("จำนวนประกาศ", len(item_data))
    chart_data = item_data.dropna(subset=["price_numeric"]).sort_values("published_date")
    if not chart_data.empty:
        st.line_chart(chart_data.set_index("published_date")["price_numeric"])
    st.dataframe(
        item_data.sort_values("published_date", ascending=False)[
            ["published_date", "item", "price", "source_id", "url"]
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "ดาวน์โหลดประวัติ CSV",
        data=item_data.to_csv(index=False).encode("utf-8-sig"),
        file_name="wongpanit_price_history.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    render_dashboard()