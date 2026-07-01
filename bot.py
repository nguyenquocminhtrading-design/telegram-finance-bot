import os
import time
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import telebot
from telebot.types import Message
import io
import openpyxl

from config import TELEGRAM_TOKEN, ADMIN_USER_ID, WEBHOOK_URL, DATABASE_PATH
from database import (
    add_transaction, add_transfer, get_bank_balance,
    get_transactions, add_asset, save_state, load_state, clear_state, get_db, get_assets
)
from asset_manager import get_asset_summary, liquidate_asset
from finance_logic import get_balance, get_monthly_summary, get_category_breakdown, get_all_bank_balances
from gsheets_reader import sync_all_from_sheets, full_sync_from_sheets, read_expenses_from_sheet, read_portfolio_from_sheet
from gsheets_sync import sync_expense_to_gsheet, sync_transfer_to_gsheet, sync_asset_to_gsheet
from simulation import run_monte_carlo, generate_projection_chart
from nav_fetcher import fetch_nav_from_vnsignal, update_asset_nav, refresh_all_assets
from llm_parser import parse_transaction as parse_gemini
from groq_parser import parse_transaction as parse_groq
from local_parser import parse_transaction_local
from telebot.formatting import escape_markdown

logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

VALID_BANKS = ["VCB", "ACB", "HDBANK", "CASH", "MOMO"]

def with_timeout(timeout_secs=8):
    def decorator(func):
        def wrapper(*args, **kwargs):
            with ThreadPoolExecutor(max_workers=1) as pool:
                f = pool.submit(func, *args, **kwargs)
                try:
                    return f.result(timeout=timeout_secs)
                except FutureTimeout:
                    logger.error(f"TIMEOUT {timeout_secs}s: {func.__name__}")
                    return None
                except Exception as e:
                    logger.warning(f"{func.__name__} error: {e}")
                    return None
        return wrapper
    return decorator

def safe_api(func):
    wrapped = with_timeout(5)(func)
    def wrapper(*args, **kwargs):
        for attempt in range(2):
            result = wrapped(*args, **kwargs)
            if result is not None:
                return result
            time.sleep(0.5)
        return None
    return wrapper

# Monkey-patch để mọi lời gọi bot.send_message đều có timeout + retry
bot.send_message = safe_api(bot.send_message)
# bot.reply_to gọi nội bộ self.send_message → tự động an toàn

def is_admin(user_id):
    return ADMIN_USER_ID == 0 or user_id == ADMIN_USER_ID

def parse_amount(text):
    text = text.replace(",", "").replace(".", "").strip()
    multipliers = {"k": 1000, "tr": 1_000_000}
    suffix = text[-2:].lower() if len(text) > 2 else text[-1:].lower()
    if suffix in multipliers:
        num = float(text[:-len(suffix)]) if suffix in ["tr"] else float(text[:-1])
        return num * multipliers[suffix]
    return float(text)

# Bảng mapping text → tên chuẩn bank
_BANK_ALIASES = {
    "vcb": "VCB", "vietcombank": "VCB", "vietcom": "VCB",
    "acb": "ACB", "asia": "ACB",
    "hdbank": "HDBANK", "hd": "HDBANK",
    "cash": "CASH", "tiền mặt": "CASH", "tien mat": "CASH", "mặt": "CASH", "tienmat": "CASH",
    "momo": "MOMO", "ví momo": "MOMO", "vi momo": "MOMO",
}

def resolve_bank_text(text):
    """Chuyển text tự do → tên bank chuẩn (VCB/ACB/HDBANK/CASH/MOMO). Trả None nếu không khớp."""
    t = text.strip().lower()
    if t in _BANK_ALIASES:
        return _BANK_ALIASES[t]
    t_upper = text.strip().upper()
    if t_upper in VALID_BANKS:
        return t_upper
    # Partial match
    for alias, bank in _BANK_ALIASES.items():
        if alias in t:
            return bank
    return None

BANK_LIST_STR = " / ".join(VALID_BANKS)  # "VCB / ACB / HDBANK / CASH / MOMO"

def ask_bank_text(uid, amount, cat, desc):
    """Hỏi bank bằng text — không dùng nút ảo."""
    save_state(uid, {"pending_bank": {"amount": amount, "category": cat, "desc": desc}})
    bot.send_message(uid,
        f"💰 {amount:+,.0f} VND | {desc}\n"
        f"Tài khoản? ({BANK_LIST_STR})")

def ask_transfer_from_text(uid, amount):
    """Hỏi tài khoản nguồn bằng text."""
    save_state(uid, {"pending_transfer_pick": {"amount": amount, "step": "from"}})
    bot.send_message(uid,
        f"💸 Chuyển: {abs(amount):,.0f} VND\n"
        f"Từ tài khoản? ({BANK_LIST_STR})")

def ask_transfer_to_text(uid, amount, from_bank):
    """Hỏi tài khoản đích bằng text (loại from_bank ra)."""
    others = " / ".join(b for b in VALID_BANKS if b != from_bank)
    save_state(uid, {"pending_transfer_pick": {"amount": amount, "step": "to", "from_bank": from_bank}})
    bot.send_message(uid,
        f"💸 Từ: {from_bank} → Sang tài khoản? ({others})")

def do_transfer(uid, amount, desc, from_bank, to_bank):
    """
    Thực thi chuyển tiền giữa 2 tài khoản:
    1. Ghi 2 dòng đối ứng atomic vào SQLite (from_bank: -amount, to_bank: +amount)
    2. Ghi 1 dòng duy nhất vào Google Sheets tab 'Transfers' (auto-create nếu chưa có)
    3. Tính balance mới của 2 tài khoản và trả về confirmation text
    Tổng balance tổng không đổi (net = 0).
    """
    from datetime import date as _date
    # 1. Ghi atomic vào SQLite
    add_transfer(uid, amount, from_bank, to_bank, desc)

    # 2. Sync 1 dòng duy nhất vào GSheets tab 'Transfers' (không phải Expenses)
    try:
        sync_transfer_to_gsheet({
            "date": _date.today().isoformat(),
            "amount": amount,
            "from_bank": from_bank,
            "to_bank": to_bank,
            "description": desc,
        })
    except Exception as e:
        logger.warning(f"GSheet transfer sync error: {e}")

    # 3. Lấy balance mới của 2 tài khoản
    from_bal = get_bank_balance(from_bank, uid)
    to_bal   = get_bank_balance(to_bank, uid)

    return (
        f"\u2705 Chuy\u1ec3n {abs(amount):,.0f} VND\n"
        f"{from_bank} \u2192 {to_bank}\n\n"
        f"\U0001f4b3 {from_bank}: {from_bal:+,.0f}\n"
        f"\U0001f4b3 {to_bank}: {to_bal:+,.0f}"
    )

def after_tx_sync(uid, amount, cat, desc, bank, tid=None):
    try:
        from datetime import date
        sync_expense_to_gsheet({
            "date": date.today().isoformat(),
            "amount": amount,
            "category": cat,
            "description": desc,
            "bank_account": bank or "",
        })
    except Exception as e:
        logger.warning(f"GSheet sync error: {e}")

@bot.message_handler(commands=["start"])
def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Access denied.")
        return
    bot.reply_to(message, "Welcome to Personal Finance Bot!\nType /help to see all commands.")

@bot.message_handler(commands=["help"])
def cmd_help(message: Message):
    if not is_admin(message.from_user.id):
        return
    help_text = (
        "📊 *FINANCE BOT — HƯỚNG DẪN* 📊\n"
        "─────────────────────────────\n"
        "🗣 *Nhắn tự nhiên (không cần lệnh):*\n"
        "  `+500 lương vcb` — tiền vào (dấu `+` = thu nhập)\n"
        "  `-70 xăng vcb` — tiền ra (dấu `-` = chi tiêu)\n"
        "  `ăn cơm 50k` — bot tự hỏi tài khoản\n"
        "  `nhận lương 15tr acb` — thu nhập tự động\n\n"
        "💸 *Chuyển tiền (2 cách):*\n"
        "  1️⃣ Nhắn: `chuyển 2tr từ VCB sang ACB`\n"
        "  2️⃣ Lệnh: `/transfer 2000000 VCB ACB`\n"
        "     hoặc: `/transfer 2tr VCB ACB`\n\n"
        "💳 *Tài khoản hỗ trợ:*\n"
        "  `VCB` · `ACB` · `HDBANK` · `CASH` · `MOMO`\n\n"
        "💰 *Số dư & Báo cáo:*\n"
        "  `/balance` — tổng số dư\n"
        "  `/bankbalance` — số dư từng tài khoản\n"
        "  `/report` — báo cáo tháng (thu, chi, phân loại)\n"
        "  `/setbalance <bank> <amount>` — đặt số dư ban đầu\n\n"
        "📦 *Tài sản:*\n"
        "  `/asset` — danh mục tài sản\n"
        "  `/buy DCDS 10000000 VCB` — mua quỹ (thêm bank để trừ tiền)\n"
        "  `/buy VNM 100 65000 VCB` — mua cổ phiếu (có bank optional)\n"
        "  `/sell DCDS 5000000 VCB` — bán theo tên, tiền về bank\n"
        "  `/liquidate 3 7000000 VCB` — thanh lý theo ID + bank\n"
        "  `/nav <id> [ticker]` — cập nhật NAV quỹ\n"
        "  `/refresh` — refresh NAV tất cả tài sản\n\n"
        "📊 *Công cụ:*\n"
        "  `/project [monthly] [months]` — Monte Carlo projection\n"
        "  `/export` — xuất file Excel\n"
        "  `/sync` — đồng bộ từ Google Sheets\n"
        "  `/fullsync` — xóa SQLite và import lại từ Google Sheets\n"
        "  `/web` — link Web Dashboard\n\n"
        "🔧 *Debug:*\n"
        "  `/ping` `/dbcheck` `/gscheck` `/envcheck` `/logs` `/navtest` `/webhook_info`\n\n"
        "💡 *Vốn hóa tài sản:*\n"
        "  Chi tiêu ≥ 200,000 VND → bot hỏi có vốn hóa không\n"
        "  Trả lời: `yes` hoặc `no`"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=["setbalance"])
def cmd_setbalance(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "/setbalance <bank> <amount>\nVD: /setbalance VCB 5000000")
        return
    bank = parts[1].upper()
    try:
        amount = float(parts[2].replace(",", "").replace(".", ""))
    except ValueError:
        bot.reply_to(message, "Invalid amount.")
        return
    add_transaction(message.from_user.id, amount, "initial_balance",
                    f"Số dư ban đầu {bank}", is_asset=0, bank_account=bank)
    bot.reply_to(message, f"✅ Initial balance {bank}: {amount:+,.0f} VND")

@bot.message_handler(commands=["bankbalance"])
def cmd_bankbalance(message: Message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    conn = get_db()
    rows = conn.execute(
        "SELECT bank_account, SUM(amount) as balance FROM transactions"
        " WHERE user_id = ? AND bank_account IS NOT NULL AND bank_account != ''"
        " GROUP BY bank_account ORDER BY balance DESC"
        , (uid,)
    ).fetchall()
    conn.close()
    if not rows:
        bot.reply_to(message, "No bank transactions yet.")
        return
    total = sum(r["balance"] for r in rows)
    lines = ["💳 *Balance by account:*", ""]
    for r in rows:
        lines.append(f"  {r['bank_account']}: `{r['balance']:+,.0f}` VND")
    lines.append("")
    lines.append(f"  *TOTAL: `{total:+,.0f}` VND*")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=["balance"])
def cmd_balance(message: Message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    balances, total = get_all_bank_balances(uid)
    lines = ["💰 *SỐ DƯ TÀI KHOẢN:*", ""]
    for bank, bal in balances.items():
        lines.append(f"  {bank}: `{bal:+,.0f}` VND")
    lines.append("")
    lines.append(f"  *Tổng bank: `{total:+,.0f}` VND*")
    summary = get_asset_summary(uid)
    if summary["active_count"] > 0:
        lines.append("")
        lines.append("📈 *DANH MỤC ĐẦU TƯ:*")
        lines.append("")
        for a in summary["assets"]:
            if a["is_active"]:
                lines.append(f"  {a['name']}: `{a['current_value']:+,.0f}` VND")
        lines.append("")
        lines.append(f"  *Tổng đầu tư: `{summary['total_current']:+,.0f}` VND*")
        grand_total = total + summary["total_current"]
        lines.append("")
        lines.append(f"💎 *TỔNG TÀI SẢN: `{grand_total:+,.0f}` VND*")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=["report"])
def cmd_report(message: Message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    summary = get_monthly_summary(uid)
    cats = get_category_breakdown(uid)
    balances, total_balance = get_all_bank_balances(uid)

    month_label = datetime.now().strftime('%Y-%m')
    lines = [
        f"📊 *BÁO CÁO THÁNG — {month_label}*",
        "─────────────────────────────",
        "💳 *SỐ DƯ TỪNG TÀI KHOẢN:*",
    ]
    if balances:
        for bank, bal in balances.items():
            lines.append(f"  {bank}: `{bal:+,.0f}` VND")
    else:
        lines.append("  (Chưa có giao dịch)")

    lines.append("")
    lines.append(f"💰 *TỔNG SỐ DƯ: `{total_balance:+,.0f}` VND*")
    lines.append("─────────────────────────────")
    lines.append(f"📈 Thu nhập tháng:  `+{summary['income']:,.0f}`")
    lines.append(f"📉 Chi tiêu tháng:  `-{summary['expense']:,.0f}`")
    lines.append(f"📊 Net (Thu - Chi): `{summary['net']:+,.0f}`")

    if cats:
        lines.append("")
        lines.append("🏆 *TOP CHI TIÊU:*")
        for c in cats[:5]:
            lines.append(f"  {c['category']}: `{c['total']:,.0f}`")

    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=["asset"])
def cmd_asset(message: Message):
    if not is_admin(message.from_user.id):
        return
    summary = get_asset_summary()
    if not summary["assets"]:
        bot.reply_to(message, "No capitalized assets.")
        return
    lines = [f"Assets ({summary['active_count']} active / {summary['total_assets']} total)",
             f"Original: {summary['total_original']:,.0f}",
             f"Current: {summary['total_current']:,.0f}", ""]
    for a in summary["assets"]:
        marker = " [active]" if a["is_active"] else " [done]"
        lines.append(f"- {a['name']}: {a['current_value']:,.0f}/{a['original_value']:,.0f}{marker}")
    bot.reply_to(message, "\n".join(lines))

@bot.message_handler(commands=["web"])
def cmd_web(message: Message):
    if not is_admin(message.from_user.id):
        return
    base = WEBHOOK_URL.rsplit("/webhook", 1)[0] if "/webhook" in WEBHOOK_URL else WEBHOOK_URL
    dashboard_url = f"{base}/dashboard"
    snapshot_url = f"{base}/snapshot"
    bot.reply_to(
        message,
        "🌐 Web links:\n"
        f"Desktop: {dashboard_url}\n"
        f"Mobile: {snapshot_url}\n\n"
        "Mở desktop khi xem trên máy tính, mở mobile snapshot khi dùng điện thoại."
    )

@bot.message_handler(commands=["nav"])
def cmd_nav(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "/nav <asset_id> [ticker]\nVD: /nav 1 DCDS", parse_mode="Markdown")
        return
    try:
        aid = int(parts[1])
    except ValueError:
        bot.reply_to(message, "Invalid asset ID")
        return
    ticker = parts[2].upper() if len(parts) >= 3 else None
    msg = bot.reply_to(message, f"Fetching NAV for asset #{aid}...")
    ok, result = update_asset_nav(aid, ticker)
    if not ok:
        bot.edit_message_text(f"❌ {result}", msg.chat.id, msg.message_id)
        return
    bot.edit_message_text(
        f"✅ *{result['name']}* — NAV: `{result['nav']:,.0f}`\n"
        f"Value: `{result['new_value']:,.0f}`\nDate: {result['date']}",
        msg.chat.id, msg.message_id, parse_mode="Markdown"
    )

@bot.message_handler(commands=["refresh"])
def cmd_refresh(message: Message):
    if not is_admin(message.from_user.id):
        return
    msg = bot.reply_to(message, "Refreshing all NAVs...")
    results = refresh_all_assets()
    lines = ["✅ *Refresh complete*", ""]
    ok_count = sum(1 for r in results if r["ok"])
    lines.append(f"Success: {ok_count}/{len(results)}")
    for r in results:
        icon = "✅" if r["ok"] else "❌"
        if r["ok"]:
            d = r["data"]
            lines.append(f"{icon} {r['name']}: `{d['nav']:,.0f}` ({d['date']})")
        else:
            lines.append(f"{icon} {r['name']}: {r['data']}")
    bot.edit_message_text("\n".join(lines), msg.chat.id, msg.message_id, parse_mode="Markdown")

@bot.message_handler(commands=["sync"])
def cmd_sync(message: Message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    msg = bot.reply_to(message, "Syncing from Google Sheets...")
    results = sync_all_from_sheets(uid)
    e = results["expenses"]
    t = results["transfers"]
    p = results["portfolio"]
    bot.edit_message_text(
        f"✅ *Sync complete*\n"
        f"Expenses: {e['imported']} imported, {e['skipped']} skipped\n"
        f"Transfers: {t['imported']} imported, {t['skipped']} skipped\n"
        f"Portfolio: {p['imported']} imported, {p['skipped']} skipped",
        msg.chat.id, msg.message_id, parse_mode="Markdown"
    )

@bot.message_handler(commands=["fullsync"])
def cmd_fullsync(message: Message):
    if not is_admin(message.from_user.id):
        return
    save_state(message.from_user.id, {
        "pending_fullsync_confirm": {
            "requested_at": datetime.now().isoformat()
        }
    })
    bot.reply_to(
        message,
        "⚠️ Full sync sẽ xóa toàn bộ dữ liệu SQLite của bạn rồi import lại từ Google Sheets.\n"
        "Gõ `yes` để xác nhận, hoặc `no` để hủy.",
        parse_mode="Markdown"
    )
    return
    msg = bot.reply_to(
        message,
        "Full sync starting...\n"
        "This will clear SQLite data for your user and import again from Google Sheets."
    )
    results = full_sync_from_sheets(message.from_user.id)
    e = results["expenses"]
    t = results["transfers"]
    p = results["portfolio"]
    lines = [
        "✅ *Full sync complete*",
        f"Expenses: {e['imported']} imported, {e['skipped']} skipped",
        f"Transfers: {t['imported']} imported, {t['skipped']} skipped",
        f"Portfolio: {p['imported']} imported, {p['skipped']} skipped",
    ]
    bot.edit_message_text("\n".join(lines), msg.chat.id, msg.message_id, parse_mode="Markdown")

@bot.message_handler(commands=["project", "montecarlo"])
def cmd_project(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    monthly = 5000000
    months = 60
    if len(parts) >= 2:
        try: monthly = parse_amount(parts[1])
        except ValueError: pass
    if len(parts) >= 3:
        try: months = int(parts[2])
        except ValueError: pass
    bot.reply_to(message, f"Running Monte Carlo...\nMonthly: {monthly:,.0f}\nPeriod: {months}m")
    summary = get_asset_summary()
    paths = run_monte_carlo(summary['total_current'], monthly, months=months)
    chart, stats = generate_projection_chart(paths, monthly)
    text = (f"📊 **Projection ({months}m)**\n"
            f"Capital: {stats['capital']:,.0f}\n"
            f"Worst(10%): {stats['p10']:,.0f}\n"
            f"**Median: {stats['median']:,.0f}**\n"
            f"Best(90%): {stats['p90']:,.0f}")
    bot.send_photo(message.chat.id, photo=chart, caption=text, parse_mode="Markdown")

@bot.message_handler(commands=["liquidate"])
def cmd_liquidate(message: Message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "/liquidate <asset_id> <sell_price> [bank]")
        return
    try:
        aid = int(parts[1])
        price = float(parts[2])
    except ValueError:
        bot.reply_to(message, "Invalid asset ID or price.")
        return
    result = liquidate_asset(aid, price)
    if not result:
        bot.reply_to(message, "Asset not found.")
        return
    try:
        sync_asset_to_gsheet({
            "name": result["asset_name"],
            "value": price,
            "note": f"Liquidate {result['asset_name']}"
        }, is_buy=False)
    except Exception as e:
        logger.warning(f"GSheet liquidate sync error: {e}")
    bank = resolve_bank_text(parts[3]) if len(parts) >= 4 else None
    tid = result.get("transaction_id")
    if bank and tid:
        conn = get_db()
        conn.execute("UPDATE transactions SET bank_account = ? WHERE id = ?", (bank, tid))
        conn.commit()
        conn.close()
    elif tid and not bank:
        save_state(uid, {"pending_invest_bank": {"tid": tid, "money_out": -price}})
    msg = (f"Liquidated {result['asset_name']}.\n"
           f"Sold: {result['sell_price']:,.0f}\n"
           f"Book value: {result['remaining_value']:,.0f}\n"
           f"Gain/Loss: {result['gain_loss']:+,.0f}")
    if not bank:
        msg += f"\nVào tài khoản? ({BANK_LIST_STR})"
    else:
        msg += f"\nTiền về {bank}."
    bot.reply_to(message, msg)

@bot.message_handler(commands=["export"])
def cmd_export(message: Message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    bot.reply_to(message, "Generating Excel...")
    txs = get_transactions(uid, 10000, 0)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append(["ID", "Date", "Amount", "Category", "Description", "Is Asset"])
    for tx in txs:
        ws.append([tx["id"], tx["transaction_date"], tx["amount"],
                   tx["category"], tx["description"],
                   "Yes" if tx["is_asset"] else "No"])
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[col[0].column_letter].width = max_len + 2
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    bot.send_document(message.chat.id, document=buf,
                      visible_file_name=f"finance_{datetime.now():%Y%m%d}.xlsx")

FUND_NAMES = {"DCDS", "DCDE", "DCBF", "DCIP", "E1VFVN30", "FUEVFVND", "FUESSVFL"}

def _finish_buy(uid, name, total, desc, bank=None):
    tid = add_transaction(uid, -total, "investment", desc, is_asset=1, bank_account=bank or "")
    aid = add_asset(uid, tid, name, total, 1)
    conn = get_db()
    conn.execute("UPDATE assets SET ticker = ? WHERE id = ?", (name if name.upper() in FUND_NAMES else "", aid))
    conn.commit()
    conn.close()
    try:
        sync_asset_to_gsheet({"name": name, "value": total, "note": desc}, is_buy=True)
    except Exception as e:
        logger.warning(f"GSheet buy sync error: {e}")
    if bank:
        bot.send_message(uid, f"✅ Mua {name} {total:,.0f} VND từ {bank}.")
    else:
        save_state(uid, {"pending_invest_bank": {"tid": tid, "money_out": total}})
        bot.send_message(uid, f"✅ Mua {name} {total:,.0f} VND.\nTừ tài khoản? ({BANK_LIST_STR})")

@bot.message_handler(commands=["buy"])
def cmd_buy(message: Message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(
            message,
            "/buy DCDS 10000000 [bank]  (chứng chỉ quỹ)\n"
            "/buy VNM 100 65000 [bank]  (cổ phiếu)\n"
            "VD: /buy DCDS 10tr VCB")
        return
    name = parts[1]
    name_upper = name.upper()
    if name_upper in FUND_NAMES:
        try:
            total = parse_amount(parts[2])
        except (ValueError, TypeError):
            bot.reply_to(message, "Số tiền không hợp lệ. VD: 10000000, 10tr")
            return
        bank = resolve_bank_text(parts[3]) if len(parts) >= 4 else None
        _finish_buy(uid, name_upper, total, f"Mua {name_upper}", bank)
    else:
        if len(parts) < 4:
            bot.reply_to(message, "/buy <name> <qty> <price> [bank]\n/buy VNM 100 65000 VCB")
            return
        try:
            qty = float(parts[2])
            price = parse_amount(parts[3])
            total = qty * price
        except (ValueError, TypeError):
            bot.reply_to(message, "Invalid quantity or price.")
            return
        bank = resolve_bank_text(parts[4]) if len(parts) >= 5 else None
        _finish_buy(uid, name, total, f"Buy {qty} {name} @ {price}", bank)

@bot.message_handler(commands=["sell"])
def cmd_sell(message: Message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "/sell <name> <amount> [bank]\n  /sell DCDS 5000000 VCB\n  /sell VNM 5000000")
        return
    name = parts[1]
    try:
        value = parse_amount(parts[2])
    except (ValueError, TypeError):
        bot.reply_to(message, "Số tiền không hợp lệ.")
        return
    assets = get_assets(uid, active_only=True)
    target = None
    for a in assets:
        if a["name"].upper() == name.upper():
            target = a
            break
    if not target:
        bot.reply_to(message, f"Không tìm thấy tài sản \"{name}\".")
        return
    result = liquidate_asset(target["id"], value)
    if not result:
        bot.reply_to(message, "Không thể bán tài sản này.")
        return
    try:
        sync_asset_to_gsheet({
            "name": target["name"],
            "value": value,
            "note": f"Bán {target['name']}"
        }, is_buy=False)
    except Exception as e:
        logger.warning(f"GSheet sell sync error: {e}")
    bank = resolve_bank_text(parts[3]) if len(parts) >= 4 else None
    tid = result.get("transaction_id")
    if bank and tid:
        conn = get_db()
        conn.execute("UPDATE transactions SET bank_account = ? WHERE id = ?", (bank, tid))
        conn.commit()
        conn.close()
        bot.reply_to(message,
            f"✅ Sold {result['asset_name']} for {result['sell_price']:,.0f} VND.\n"
            f"Tiền về {bank} | Gain/Loss: {result['gain_loss']:+,.0f}")
    elif tid:
        save_state(uid, {"pending_invest_bank": {"tid": tid, "money_out": -value}})
        bot.reply_to(message,
            f"✅ Sold {result['asset_name']} for {result['sell_price']:,.0f} VND.\n"
            f"Gain/Loss: {result['gain_loss']:+,.0f}\n"
            f"Vào tài khoản? ({BANK_LIST_STR})")

@bot.message_handler(commands=["ping"])
def cmd_ping(message: Message):
    if not is_admin(message.from_user.id):
        return
    bot.reply_to(message, "pong")

@bot.message_handler(commands=["webhook_info"])
def cmd_webhook_info(message: Message):
    if not is_admin(message.from_user.id):
        return
    import requests
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getWebhookInfo", timeout=10)
        data = r.json()
        url = data.get("result", {}).get("url", "N/A")
        pending = data.get("result", {}).get("pending_update_count", "N/A")
        err = data.get("result", {}).get("last_error_message", "None")
        bot.reply_to(message,
            f"🌐 *Webhook Info*\n"
            f"URL: `{url}`\n"
            f"Pending: {pending}\n"
            f"Error: {err}",
            parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Lỗi: {e}")

@bot.message_handler(commands=["dbcheck"])
def cmd_dbcheck(message: Message):
    if not is_admin(message.from_user.id):
        return
    conn = get_db()
    txn = conn.execute("SELECT COUNT(*) as c FROM transactions").fetchone()["c"]
    ast = conn.execute("SELECT COUNT(*) as c FROM assets").fetchone()["c"]
    act = conn.execute("SELECT COUNT(*) as c FROM assets WHERE is_active=1").fetchone()["c"]
    db_sz = os.path.getsize(DATABASE_PATH) if os.path.exists(DATABASE_PATH) else 0
    conn.close()
    bot.reply_to(message,
        f"DB: {txn} txns, {ast} assets ({act} active), {db_sz/1024:.1f} KB",
        parse_mode="Markdown")

@bot.message_handler(commands=["gscheck"])
def cmd_gscheck(message: Message):
    if not is_admin(message.from_user.id):
        return
    from gsheets_reader import get_gspread_client
    client, err = get_gspread_client()
    if not client:
        bot.reply_to(message, f"❌ Google Sheets auth failed: {err}")
        return
    ed, ee = read_expenses_from_sheet()
    pd, pe = read_portfolio_from_sheet()
    lines = ["✅ *Google Sheets OK*", ""]
    lines.append(f"Expenses: {len(ed)} rows" if ed else f"⚠️ {ee}")
    lines.append(f"Portfolio: {len(pd)} rows" if pd else f"⚠️ {pe}")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=["envcheck"])
def cmd_envcheck(message: Message):
    if not is_admin(message.from_user.id):
        return
    from config import GEMINI_API_KEY, GOOGLE_CREDENTIALS_FILE, EXPENSE_SHEET_NAME, PORTFOLIO_SHEET_NAME
    def mask(s):
        if not s: return "<empty>"
        return s[:6] + "..." + s[-4:] if len(s) > 12 else s[:3] + "..."
    lines = [
        "⚙️ *Environment*",
        f"  WEBHOOK_URL: {WEBHOOK_URL or '<empty>'}",
        f"  TELEGRAM_TOKEN: {mask(TELEGRAM_TOKEN)}",
        f"  GEMINI_API_KEY: {mask(GEMINI_API_KEY)}",
        f"  GOOGLE_CREDENTIALS: {os.path.exists(GOOGLE_CREDENTIALS_FILE)}",
    ]
    bot.reply_to(message, "\n".join(escape_markdown(l) for l in lines), parse_mode="Markdown")

@bot.message_handler(commands=["logs"])
def cmd_logs(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    n = 20
    if len(parts) >= 2:
        try: n = min(int(parts[1]), 100)
        except ValueError: pass
    log_file = os.path.join(os.path.dirname(__file__), "bot.log")
    if not os.path.exists(log_file):
        bot.reply_to(message, "No bot.log found")
        return
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    text = "📋 *Last logs*:\n```\n" + "".join(lines[-n:])[-3000:] + "\n```"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=["navtest"])
def cmd_navtest(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "/navtest <ticker>\nVD: /navtest DCDS")
        return
    ticker = parts[1].upper()
    msg = bot.reply_to(message, f"Testing NAV for {ticker}...")
    nav, dt, err = fetch_nav_from_vnsignal(ticker)
    if err:
        bot.edit_message_text(f"❌ {err}", msg.chat.id, msg.message_id)
        return
    bot.edit_message_text(f"✅ {ticker}: `{nav:,.0f}` ({dt})", msg.chat.id, msg.message_id, parse_mode="Markdown")

@bot.message_handler(commands=["transfer"])
def cmd_transfer(message: Message):
    """
    /transfer <amount> <from_bank> <to_bank>
    Ví dụ: /transfer 2000000 VCB ACB
            /transfer 2tr VCB ACB
    """
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        bot.reply_to(message,
            "💸 Cú pháp: /transfer <số tiền> <từ> <sang>\n"
            f"Ví dụ: /transfer 2tr VCB ACB\n"
            f"Tài khoản: {BANK_LIST_STR}")
        return
    try:
        amount = parse_amount(parts[1])
    except (ValueError, TypeError):
        bot.reply_to(message, "❌ Số tiền không hợp lệ. VD: 2000000, 2tr, 500k")
        return
    from_bank = resolve_bank_text(parts[2])
    to_bank = resolve_bank_text(parts[3])
    if not from_bank:
        bot.reply_to(message, f"❌ Tài khoản nguồn không hợp lệ: {parts[2]}\nChọn: {BANK_LIST_STR}")
        return
    if not to_bank:
        bot.reply_to(message, f"❌ Tài khoản đích không hợp lệ: {parts[3]}\nChọn: {BANK_LIST_STR}")
        return
    if from_bank == to_bank:
        bot.reply_to(message, "❌ Tài khoản nguồn và đích không được giống nhau.")
        return
    desc = f"Chuyển từ {from_bank} sang {to_bank}"
    try:
        reply = do_transfer(uid, amount, desc, from_bank, to_bank)
        bot.reply_to(message, reply)
    except Exception as e:
        logger.error(f"cmd_transfer error: {e}")
        bot.reply_to(message, f"❌ Lỗi: {e}")

@bot.message_handler(func=lambda m: True)
def handle_main_message(message: Message):
    if not is_admin(message.from_user.id):
        return

    uid = message.from_user.id
    text = message.text.strip()
    loaded = load_state(uid)

    # --- State: pending_fullsync_confirm ---
    if "pending_fullsync_confirm" in loaded:
        affirm = text.lower() in ("yes", "y", "co", "có", "ok", "oke", "dong y", "đồng ý")
        if not affirm:
            clear_state(uid)
            bot.reply_to(message, "Đã hủy full sync.")
            return
        clear_state(uid)
        msg = bot.reply_to(message, "Đang full sync, chờ mình chút nhé...")
        try:
            results = full_sync_from_sheets(uid)
            e = results["expenses"]
            t = results["transfers"]
            p = results["portfolio"]
            lines = [
                "✅ *Full sync complete*",
                f"Expenses: {e['imported']} imported, {e['skipped']} skipped",
                f"Transfers: {t['imported']} imported, {t['skipped']} skipped",
                f"Portfolio: {p['imported']} imported, {p['skipped']} skipped",
            ]
            bot.edit_message_text("\n".join(lines), msg.chat.id, msg.message_id, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"fullsync error: {e}")
            bot.edit_message_text(f"❌ Full sync failed: {e}", msg.chat.id, msg.message_id)
        return

    # --- State: pending_bank (user trả lời tên bank) ---
    if "pending_bank" in loaded:
        bank = resolve_bank_text(text)
        if not bank:
            bot.reply_to(message, f"❌ Không nhận ra tài khoản \"{text}\". Thử lại: {BANK_LIST_STR}")
            return  # Giữ state → user gõ lại, không mất transaction
        state = loaded["pending_bank"]
        tid = add_transaction(uid, state["amount"], state["category"], state["desc"],
                              is_asset=0, bank_account=bank)
        clear_state(uid)
        after_tx_sync(uid, state["amount"], state["category"], state["desc"], bank, tid)
        bal = get_balance(uid)
        text_reply = f"✅ {state['amount']:+,.0f} | {state['desc']} ({bank}) | Balance: {bal:,.0f}"
        # Hỏi vốn hóa nếu chi tiêu ≥ 200,000 VND (threshold hợp lý)
        if state["amount"] < -200_000:
            save_state(uid, {"pending_capitalize_decision": {"tid": tid, "value": abs(state["amount"])}})
            bot.send_message(uid, text_reply + "\n\n💡 Vốn hóa tài sản? (yes / no)")
        else:
            bot.send_message(uid, text_reply)
        return

    # --- State: pending_transfer_pick (user trả lời bank cho transfer) ---
    if "pending_transfer_pick" in loaded:
        state = loaded["pending_transfer_pick"]
        bank = resolve_bank_text(text)
        step = state.get("step", "from")
        amount = state.get("amount", 0)
        if step == "from":
            if not bank:
                bot.reply_to(message, f"❌ Không nhận ra tài khoản. Thử lại: {BANK_LIST_STR}")
                return  # Giữ state
            ask_transfer_to_text(uid, amount, bank)
        elif step == "to":
            from_bank = state.get("from_bank")
            if not bank:
                others = " / ".join(b for b in VALID_BANKS if b != from_bank)
                bot.reply_to(message, f"❌ Không nhận ra tài khoản. Thử lại: {others}")
                return  # Giữ state
            if bank == from_bank:
                bot.reply_to(message, f"❌ Tài khoản đích phải khác nguồn ({from_bank}). Chọn tài khoản khác.")
                return
            clear_state(uid)
            desc = f"Chuyển từ {from_bank} sang {bank}"
            try:
                reply = do_transfer(uid, amount, desc, from_bank, bank)
                bot.reply_to(message, reply)
            except Exception as e:
                logger.error(f"transfer step error: {e}")
                bot.reply_to(message, f"❌ Lỗi khi chuyển: {e}")
        return

    # --- State: pending_invest_bank (user trả lời bank cho buy/sell/liquidate) ---
    if "pending_invest_bank" in loaded:
        bank = resolve_bank_text(text)
        if not bank:
            bot.reply_to(message, f"❌ Không nhận ra tài khoản \"{text}\". Thử lại: {BANK_LIST_STR}")
            return
        state = loaded["pending_invest_bank"]
        conn = get_db()
        conn.execute("UPDATE transactions SET bank_account = ? WHERE id = ?", (bank, state["tid"]))
        conn.commit()
        conn.close()
        clear_state(uid)
        bal = get_balance(uid)
        bot.reply_to(message, f"✅ Cập nhật bank: {bank} | Balance: {bal:,.0f} VND")
        return

    # --- State: pending_capitalize_decision (user typing yes/no) ---
    if "pending_capitalize_decision" in loaded:
        affirm = text.lower() in ("yes", "y", "có", "co", "ye", "ok", "oke", "đồng ý", "dong y")
        if affirm:
            state = loaded["pending_capitalize_decision"]
            save_state(uid, {"pending_capitalize": {"tid": state["tid"], "value": state["value"], "step": "ask_name"}})
            bot.reply_to(message, "What is the asset name? (e.g. MacBook Pro 14)")
        else:
            clear_state(uid)
            bot.reply_to(message, "Saved as regular expense.")
        return

    # --- State: pending_capitalize (asset name / months flow) ---
    cap = loaded.get("pending_capitalize")
    if cap and cap != "None":
        handle_capitalize_step(message, uid, cap)
        return

    # --- Parse transaction text: Gemini → Groq → local ---
    parsed = parse_gemini(text)
    source = "gemini"
    if not parsed or "amount" not in parsed or parsed["amount"] is None:
        parsed = parse_groq(text)
        source = "groq"
    if not parsed or "amount" not in parsed or parsed["amount"] is None:
        parsed = parse_transaction_local(text)
        source = "local"

    if not parsed or parsed.get("amount") is None:
        bot.reply_to(message,
            f"Could not parse: \"{text}\"\n"
            f"Try: +500 salary, -200 lunch, chuyển 5tr từ VCB sang ACB")
        return

    try:
        amount = float(parsed["amount"])
        action = parsed.get("action", "expense")
        desc = parsed.get("description", text)
        cat = parsed.get("category", "other")
        bank = parsed.get("bank")
        from_bank = parsed.get("from_bank") if action == "transfer" else None
        to_bank = parsed.get("to_bank") if action == "transfer" else None
    except (ValueError, TypeError):
        bot.reply_to(message, "Invalid transaction data.")
        return

    if action == "income":
        amount = abs(amount)
    elif action == "expense":
        amount = -abs(amount)

    logger.info(f"[{source}] {text} -> action={action} amount={amount} cat={cat} bank={bank}")

    # --- TRANSFER ---
    if action == "transfer":
        if from_bank and to_bank:
            # Đủ thông tin → thực hiện ngay
            reply = do_transfer(uid, amount, desc, from_bank, to_bank)
            bot.reply_to(message, reply)
        elif from_bank and not to_bank:
            # Biết from → hỏi to bằng text
            ask_transfer_to_text(uid, amount, from_bank)
        else:
            # Không biết gì → hỏi from trước
            ask_transfer_from_text(uid, amount)
        return

    # --- INCOME / EXPENSE with bank ---
    if bank:
        tid = add_transaction(uid, amount, cat, desc, is_asset=0, bank_account=bank)
        after_tx_sync(uid, amount, cat, desc, bank, tid)
        bal = get_balance(uid)
        text_reply = f"✅ {amount:+,.0f} | {desc} ({bank}) | Balance: {bal:,.0f}"
        # Hỏi vốn hóa chỉ khi là chi tiêu ≥ 200,000 VND (KHÔNG phải transfer)
        if amount < -200_000:
            save_state(uid, {"pending_capitalize_decision": {"tid": tid, "value": abs(amount)}})
            bot.reply_to(message, text_reply + "\n\n💡 Vốn hóa tài sản? (yes / no)")
        else:
            bot.reply_to(message, text_reply)
        return

    # --- Chưa có bank → hỏi bằng text ---
    ask_bank_text(uid, amount, cat, desc)

def handle_capitalize_step(message, uid, cap):
    step = cap.get("step")
    if step == "ask_name":
        cap["name"] = message.text.strip()
        cap["step"] = "ask_months"
        save_state(uid, {"pending_capitalize": cap})
        bot.reply_to(message, f"Asset name: {cap['name']}\nDepreciation period (months, e.g. 12):")
    elif step == "ask_months":
        try:
            months = int(message.text.strip())
            if months < 1:
                raise ValueError
        except ValueError:
            bot.reply_to(message, "Please enter a valid number of months (>= 1).")
            return
        tid = cap["tid"]
        name = cap["name"]
        value = cap["value"]
        add_asset(uid, tid, name, value, months)
        conn = get_db()
        conn.execute("UPDATE transactions SET is_asset = 1 WHERE id = ?", (tid,))
        conn.commit()
        conn.close()
        bot.reply_to(message,
            f"✅ Asset capitalized!\n"
            f"Name: {name}\nValue: {value:,.0f}\n"
            f"Depreciation: {months} months\nMonthly: {value/months:,.0f}\n\n"
            f"Use /asset to track it.")
        clear_state(uid)

def guess_category(desc):
    desc_lower = desc.lower()
    categories = {
        "food": ["ăn", "uống", "cơm", "phở", "bún", "cafe", "lunch", "dinner", "trưa", "tối", "sáng"],
        "transport": ["xe", "xăng", "grab", "taxi", "bus", "vé", "tàu", "đi"],
        "salary": ["lương", "thưởng", "thu nhập", "nhận", "lãi", "bán"],
        "entertainment": ["phim", "game", "movie", "netflix", "chơi", "karaoke"],
        "bill": ["điện", "nước", "mạng", "internet", "thuê", "trả", "phone"],
        "health": ["bệnh", "thuốc", "khám", "bác sĩ", "gym"],
        "shopping": ["mua", "shop", "áo", "quần", "giày", "shopee", "laptop"],
        "transfer": ["chuyển", "rút", "nạp"],
    }
    for cat, keywords in categories.items():
        for kw in keywords:
            if kw in desc_lower:
                return cat
    return "other"

def set_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
