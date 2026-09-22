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


def normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return empty_announcements()
    frame = frame.copy()
    for column in ANNOUNCEMENT_COLUMNS:
        if column not in frame:
            frame[column] = ""
    frame["source_id_number"] = pd.to_numeric(frame["source_id"], errors="coerce")
    frame = frame.sort_values(["published_date", "item", "source_id_number"])
    frame = frame.drop_duplicates(subset=["published_date", "item"], keep="last")
    frame["announcement_key"] = frame.apply(
        lambda row: announcement_key(row["published_date"], row["item"], row["price"]), axis=1
    )
    return frame.drop(columns=["source_id_number"])[ANNOUNCEMENT_COLUMNS].reset_index(drop=True)


def remove_future_date_spikes(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop a page whose date jumps forward and then goes backward on later IDs."""
    if frame.empty:
        return frame
    kept_groups = []
    for _, item_data in frame.groupby("item", sort=False):
        item_data = item_data.copy()
        item_data["source_id_number"] = pd.to_numeric(item_data["source_id"], errors="coerce")
        item_data = item_data.sort_values("source_id_number").reset_index(drop=True)
        later_min_dates = item_data["published_date"][::-1].cummin()[::-1].shift(-1)
        is_spike = item_data["published_date"] > later_min_dates.fillna(item_data["published_date"])
        kept_groups.append(item_data.loc[~is_spike].drop(columns=["source_id_number"]))
    return pd.concat(kept_groups, ignore_index=True) if kept_groups else empty_announcements()


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
    return normalize_history(frame[ANNOUNCEMENT_COLUMNS])


def save_announcements(frame: pd.DataFrame) -> None:
    content = normalize_history(frame).to_csv(index=False).encode("utf-8-sig")
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


def announcement_key(published_date: str, item: str, price: str = "") -> str:
    raw_value = "|".join((published_date, item))
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:20]


def price_to_number(value: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else None


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


def scrape_page_date(page_id: int) -> str | None:
    response = requests.get(
        URL_TEMPLATE.format(id=page_id),
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")
    return parse_thai_date(tables[0].get_text(" ", strip=True)) if tables else None


def update_prices(first_id: int, max_id: int, existing: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if max_id < first_id:
        raise ValueError("Max ID ต้องมากกว่าหรือเท่ากับ ID เริ่มต้น")
    original_publications = set(zip(existing["published_date"], existing["item"]))
    scanned_rows = []
    duplicate_count = 0
    error_count = 0
    scanned_count = 0
    for page_id in range(first_id, max_id + 1):
        scanned_count += 1
        page_date = None
        try:
            page_date = scrape_page_date(page_id)
        except requests.RequestException:
            error_count += 1
        if page_date:
            for target_item in ITEMS.values():
                scanned_rows.append({
                    "announcement_key": "",
                    "source_id": str(page_id),
                    "published_date": page_date,
                    "item": target_item,
                    "price": "",
                    "url": URL_TEMPLATE.format(id=page_id),
                    "scraped_at": datetime.now().isoformat(timespec="seconds"),
                })
        for target_item in ITEMS.values():
            try:
                row = scrape_page(page_id, target_item)
                if row is None:
                    continue
                scanned_rows.append(row)
            except requests.RequestException:
                error_count += 1
            except Exception:
                error_count += 1
    combined = pd.concat([existing, pd.DataFrame(scanned_rows)], ignore_index=True)
    combined = remove_future_date_spikes(combined)
    combined = combined[combined["price"].astype(str).str.strip().ne("")]
    updated = normalize_history(combined)
    updated_publications = set(zip(updated["published_date"], updated["item"]))
    new_count = len(updated_publications - original_publications)
    duplicate_count = max(0, len(scanned_rows) - new_count)
    if not updated.empty:
        updated = updated.sort_values(["published_date", "source_id"]).reset_index(drop=True)
    return updated, {
        "scanned": scanned_count,
        "new": new_count,
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
        backfill = st.checkbox("ดึงข้อมูลย้อนหลัง", value=False)
        default_start = max(START_ID, last_scanned_id + 1)
        if backfill:
            first_id = st.number_input("ID เริ่มต้นย้อนหลัง", value=START_ID, min_value=START_ID, step=1)
        else:
            first_id = st.number_input("ID เริ่มต้นรอบถัดไป", value=default_start, min_value=START_ID, disabled=True)
        max_id = st.number_input("ID สูงสุดที่จะตรวจ", value=max(DEFAULT_MAX_ID, int(first_id)), min_value=START_ID, step=1)
        update_clicked = st.button("Update", type="primary", use_container_width=True)
        st.divider()
        st.metric("ID ล่าสุดที่ตรวจแล้ว", last_scanned_id)
        st.caption(f"เก็บข้อมูลที่: {ANNOUNCEMENTS_FILE.name}")

    if update_clicked:
        if max_id < first_id:
            st.error("ID สูงสุดต้องมากกว่า ID เริ่มต้น")
        else:
            with st.spinner(f"กำลังตรวจ ID {first_id} ถึง {max_id}..."):
                updated, summary = update_prices(int(first_id), int(max_id), existing)
                save_announcements(updated)
                save_last_id(max(last_scanned_id, int(max_id)))
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
    item_data["price_numeric"] = item_data["price"].apply(price_to_number)
    latest = item_data.sort_values("published_date").iloc[-1]
    metric_columns = st.columns(3)
    metric_columns[0].metric("ราคาล่าสุด", latest["price"])
    metric_columns[1].metric("วันที่ประกาศ", latest["published_date"])
    metric_columns[2].metric("จำนวนประกาศ", len(item_data))
    chart_data = item_data.dropna(subset=["price_numeric"]).sort_values("published_date")
    if not chart_data.empty:
        st.markdown("#### กราฟแนวโน้มราคา")
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