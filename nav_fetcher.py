import re
import sqlite3
import requests
import logging
from database import get_assets, update_asset_value, get_db, get_asset_by_id

logger = logging.getLogger(__name__)

NAV_SOURCES = {
    "DCDS": "https://vnsignal.vn/quy-dau-tu/dcds",
    "DCDE": "https://vnsignal.vn/quy-dau-tu/dcde",
    "DCBF": "https://vnsignal.vn/quy-dau-tu/dcbf",
    "DCIP": "https://vnsignal.vn/quy-dau-tu/dcip",
    "E1VFVN30": "https://vnsignal.vn/quy-dau-tu/e1vfvn30",
    "FUEVFVND": "https://vnsignal.vn/quy-dau-tu/fuevfvnd",
    "FUESSVFL": "https://vnsignal.vn/quy-dau-tu/fuessvfl",
}

def fetch_nav_from_vnsignal(ticker):
    url = NAV_SOURCES.get(ticker.upper())
    if not url:
        return None, None, f"Không hỗ trợ ticker '{ticker}'"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        text = resp.text
        match = re.search(r'NAV Gần Nhất\s*([\d.]+)\s*VND\s*([\d]+/[\d]+/[\d]+)', text)
        if match:
            nav_value = float(match.group(1).replace(".", "").replace(",", ""))
            nav_date = match.group(2)
            return nav_value, nav_date, None
        match2 = re.search(r'([\d,.]+)\s*VND/chứng chỉ quỹ', text)
        if match2:
            raw = match2.group(1).replace(".", "").replace(",", ".")
            nav_value = float(raw)
            return nav_value, None, None
        return None, None, "Không tìm thấy NAV trong trang VNSignal"
    except requests.RequestException as e:
        return None, None, f"Lỗi VNSignal: {e}"

def fetch_nav_cached(ticker):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT last_nav, last_nav_date FROM assets WHERE ticker = ? AND last_nav IS NOT NULL LIMIT 1",
            (ticker.upper(),)
        ).fetchone()
        conn.close()
        if row:
            return row["last_nav"], row["last_nav_date"], None
    except Exception:
        conn.close()
    return None, None, f"No cached NAV for {ticker}"

def fetch_nav(ticker, asset_id=None):
    nav, nav_date, err = fetch_nav_from_vnsignal(ticker)
    if nav is not None:
        return nav, nav_date, None
    cached, cached_date, _ = fetch_nav_cached(ticker)
    if cached is not None:
        logger.warning(f"VNSignal fail for {ticker}, using cached NAV {cached}")
        return cached, cached_date, f"Using cached NAV ({err})"
    return None, None, err

def update_asset_nav(asset_id, ticker=None):
    asset = None
    for a in get_assets(0):
        if a["id"] == asset_id:
            asset = a
            break
    if not asset:
        return False, "Tài sản không tồn tại"
    t = ticker or asset.get("ticker", "")
    if not t:
        return False, "Tài sản chưa có ticker"
    nav, nav_date, err = fetch_nav(t, asset_id)
    if nav is None:
        cached = asset.get("last_nav")
        if cached:
            return True, {"nav": cached, "date": asset.get("last_nav_date"), "new_value": asset["current_value"], "name": asset["name"], "cached": True}
        return False, err
    quantity = asset["original_value"] / 100000
    new_value = round(nav * quantity, 2)
    update_asset_value(asset_id, new_value)
    conn = get_db()
    try:
        conn.execute("UPDATE assets SET last_nav = ?, last_nav_date = ?, ticker = ? WHERE id = ?",
                     (nav, nav_date or "", t.upper(), asset_id))
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
    return True, {"nav": nav, "date": nav_date, "new_value": new_value, "name": asset["name"], "cached": False}

def refresh_all_assets():
    results = []
    assets = get_assets(0, active_only=True)
    for asset in assets:
        ticker = asset.get("ticker", "")
        if not ticker:
            continue
        ok, data = update_asset_nav(asset["id"], ticker)
        results.append({"asset_id": asset["id"], "name": asset["name"], "ok": ok, "data": data})
    return results

def add_ticker_column():
    conn = get_db()
    try:
        conn.execute("ALTER TABLE assets ADD COLUMN ticker TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE assets ADD COLUMN last_nav REAL DEFAULT NULL")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE assets ADD COLUMN last_nav_date TEXT DEFAULT NULL")
    except Exception:
        pass
    conn.commit()
    conn.close()
