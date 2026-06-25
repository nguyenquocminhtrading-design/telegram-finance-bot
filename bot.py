import os
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import io
import openpyxl

from config import TELEGRAM_TOKEN, ADMIN_USER_ID, WEBHOOK_URL, DATABASE_PATH
from database import add_transaction, get_transactions, add_asset, save_state, load_state, clear_state, get_db
from asset_manager import get_asset_summary, liquidate_asset
from finance_logic import get_balance, get_monthly_summary, get_category_breakdown
from gsheets_reader import sync_all_from_sheets, read_expenses_from_sheet, read_portfolio_from_sheet
from gsheets_sync import sync_expense_to_gsheet
from simulation import run_monte_carlo, generate_projection_chart
from nav_fetcher import fetch_nav_from_vnsignal, update_asset_nav, refresh_all_assets
from llm_parser import parse_transaction
from local_parser import parse_transaction_local
from telebot.formatting import escape_markdown

logger = logging.getLogger(__name__)

class SafeBot:
    def __init__(self, raw_bot, timeout=8):
        self._b = raw_bot
        self._timeout = timeout
        self._methods = {"reply_to", "send_message", "send_photo", "send_document",
                         "edit_message_text", "edit_message_reply_markup",
                         "answer_callback_query", "send_animation"}

    def __getattr__(self, name):
        attr = getattr(self._b, name)
        if name in self._methods:
            def wrap(*a, **kw):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    f = pool.submit(attr, *a, **kw)
                    try:
                        return f.result(timeout=self._timeout)
                    except Exception as e:
                        logger.error(f"[SafeBot] {name}: {e}")
                        return None
            return wrap
        return attr

raw_bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
bot = SafeBot(raw_bot)

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
        return wrapper
    return decorator

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

def ask_bank(uid, amount, cat, desc):
    save_state(uid, {"pending_bank": {"amount": amount, "category": cat, "desc": desc}})
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(*(InlineKeyboardButton(b, callback_data=f"bank:{b}") for b in VALID_BANKS))
    bot.send_message(uid,
        f"Amount: {amount:+,.0f}\nDesc: {desc}\nWhich bank?",
        reply_markup=markup)

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
        "📊 *FINANCE BOT COMMAND PANEL* 📊\n"
        "─────────────────────────────\n"
        "🤖 *Tự động nhận diện:*\n"
        "  `ăn cơm 50k vcb`\n"
        "  `nhận lương 15tr acb`\n"
        "  `chuyển 2tr từ VCB sang CASH`\n\n"
        "📝 *Cú pháp:* `+500 salary` / `-200 lunch`\n\n"
        "💳 *Tài khoản:* VCB · ACB · HDBANK · CASH · MOMO\n\n"
        "💸 *Chuyển tiền:* `chuyển 5tr từ VCB sang ACB`\n\n"
        "💰 `/setbalance <bank> <amount>` - Số dư ban đầu\n\n"
        "💼 `/buy <asset> <qty> <price>` - Mua tài sản\n"
        "  `/liquidate <id> <price>` - Bán tài sản\n"
        "  `/asset` - Danh mục tài sản\n"
        "  `/nav <id> [ticker]` - Cập nhật NAV\n"
        "  `/refresh` - Refresh NAV tất cả\n\n"
        "📈 `/balance` - Số dư\n"
        "  `/bankbalance` - Số dư từng tài khoản\n"
        "  `/report` - Báo cáo tháng\n"
        "  `/project` - Monte Carlo\n"
        "  `/export` - Excel\n"
        "  `/web` - Dashboard\n\n"
        "🔄 `/sync` - Đồng bộ Google Sheets\n\n"
        "🔧 `/ping` `/dbcheck` `/gscheck` `/envcheck` `/logs` `/navtest`"
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
    conn = get_db()
    rows = conn.execute(
        "SELECT bank_account, SUM(amount) as balance FROM transactions"
        " WHERE bank_account IS NOT NULL AND bank_account != ''"
        " GROUP BY bank_account ORDER BY balance DESC"
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
    bal = get_balance()
    bot.reply_to(message, f"Balance: **{bal:,.0f} VND**", parse_mode="Markdown")

@bot.message_handler(commands=["report"])
def cmd_report(message: Message):
    if not is_admin(message.from_user.id):
        return
    summary = get_monthly_summary()
    cats = get_category_breakdown()
    lines = [f"Report - {datetime.now().strftime('%Y-%m')}",
             f"Income: +{summary['income']:,.0f}",
             f"Expense: -{summary['expense']:,.0f}",
             f"Net: {summary['net']:,.0f}", ""]
    if cats:
        lines.append("Top spending:")
        for c in cats[:5]:
            lines.append(f"  {c['category']}: {c['total']:,.0f}")
    bot.reply_to(message, "\n".join(lines))

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
    bot.reply_to(message, f"Dashboard: {base}/dashboard")

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
    msg = bot.reply_to(message, "Syncing from Google Sheets...")
    results = sync_all_from_sheets()
    e = results["expenses"]
    p = results["portfolio"]
    bot.edit_message_text(
        f"✅ *Sync complete*\n"
        f"Expenses: {e['imported']} imported, {e['skipped']} skipped\n"
        f"Portfolio: {p['imported']} imported, {p['skipped']} skipped",
        msg.chat.id, msg.message_id, parse_mode="Markdown"
    )

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
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "/liquidate <asset_id> <sell_price>")
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
    bot.reply_to(message,
        f"Liquidated {result['asset_name']}.\n"
        f"Sold: {result['sell_price']:,.0f}\n"
        f"Book value: {result['remaining_value']:,.0f}\n"
        f"Gain/Loss: {result['gain_loss']:+,.0f}")

@bot.message_handler(commands=["export"])
def cmd_export(message: Message):
    if not is_admin(message.from_user.id):
        return
    bot.reply_to(message, "Generating Excel...")
    txs = get_transactions(0, 10000, 0)
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

@bot.message_handler(commands=["buy"])
def cmd_buy(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        bot.reply_to(message, "/buy <name> <qty> <price>\n/buy VNM 100 65000")
        return
    name = parts[1]
    try:
        qty = float(parts[2])
        price = parse_amount(parts[3])
        total = qty * price
    except ValueError:
        bot.reply_to(message, "Invalid quantity or price.")
        return
    tid = add_transaction(message.from_user.id, -total, "investment",
                          f"Buy {qty} {name} @ {price}", is_asset=1)
    add_asset(message.from_user.id, tid, name, total, 1)
    bot.reply_to(message, f"✅ Bought {qty} {name} for {total:,.0f} VND.")

@bot.message_handler(commands=["sell"])
def cmd_sell(message: Message):
    if not is_admin(message.from_user.id):
        return
    bot.reply_to(message, "Use /liquidate <asset_id> <sell_price>")

@bot.message_handler(commands=["ping"])
def cmd_ping(message: Message):
    if not is_admin(message.from_user.id):
        return
    bot.reply_to(message, "pong")

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

@bot.callback_query_handler(func=lambda c: c.data.startswith("bank:"))
def handle_bank_callback(call: CallbackQuery):
    uid = call.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(call.id, "Access denied.")
        return
    bot.answer_callback_query(call.id)
    bank = call.data.split(":", 1)[1]
    loaded = load_state(uid)
    if "pending_bank" not in loaded:
        bot.send_message(uid, "Session expired. Send again.")
        return
    state = loaded["pending_bank"]
    try:
        tid = add_transaction(uid, state["amount"], state["category"], state["desc"],
                              is_asset=0, bank_account=bank)
        clear_state(uid)
        bal = get_balance()
        text = f"✅ Recorded: {state['amount']:+,.0f} - {state['desc']} ({bank})\nBalance: {bal:,.0f}"
        after_tx_sync(uid, state["amount"], state["category"], state["desc"], bank, tid)
        if state["amount"] < -199:
            save_state(uid, {"pending_capitalize_decision": {"tid": tid, "value": abs(state["amount"])}})
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("Yes", callback_data="cap:yes"),
                       InlineKeyboardButton("No", callback_data="cap:no"))
            bot.edit_message_text(text + "\n\nCapitalize as asset?", uid, call.message.message_id, reply_markup=markup)
        else:
            bot.send_message(uid, text)
    except Exception as e:
        logger.error(f"bank_callback error: {e}")
        bot.send_message(uid, f"Error: {e}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("cap:"))
def handle_cap_callback(call: CallbackQuery):
    uid = call.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(call.id, "Access denied.")
        return
    bot.answer_callback_query(call.id)
    choice = call.data.split(":", 1)[1]
    loaded = load_state(uid)
    key = "pending_capitalize_decision"
    if key not in loaded:
        bot.send_message(uid, "Session expired.")
        return
    state = loaded[key]
    try:
        if choice == "yes":
            save_state(uid, {"pending_capitalize": {"tid": state["tid"], "value": state["value"], "step": "ask_name"}})
            bot.send_message(uid, "What is the asset name? (e.g. MacBook Pro 14)")
        else:
            clear_state(uid)
            bot.send_message(uid, "Saved as regular expense.")
    except Exception as e:
        logger.error(f"cap_callback error: {e}")
        bot.send_message(uid, f"Error: {e}")

@bot.message_handler(func=lambda m: True)
def handle_main_message(message: Message):
    if not is_admin(message.from_user.id):
        return

    uid = message.from_user.id
    text = message.text.strip()
    loaded = load_state(uid)

    # --- State: pending_bank (user typing bank name) ---
    if "pending_bank" in loaded:
        bank_text = text.upper()
        bank = next((b for b in VALID_BANKS if b in bank_text or bank_text in b), None)
        if not bank:
            bot.reply_to(message, f"Invalid bank. Choose: {', '.join(VALID_BANKS)}")
            return
        state = loaded["pending_bank"]
        tid = add_transaction(uid, state["amount"], state["category"], state["desc"],
                              is_asset=0, bank_account=bank)
        clear_state(uid)
        bal = get_balance()
        text_reply = f"✅ Recorded: {state['amount']:+,.0f} - {state['desc']} ({bank})\nBalance: {bal:,.0f}"
        after_tx_sync(uid, state["amount"], state["category"], state["desc"], bank, tid)
        if state["amount"] < -199:
            save_state(uid, {"pending_capitalize_decision": {"tid": tid, "value": abs(state["amount"])}})
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("Yes", callback_data="cap:yes"),
                       InlineKeyboardButton("No", callback_data="cap:no"))
            bot.send_message(uid, text_reply + "\n\nCapitalize as asset?", reply_markup=markup)
        else:
            bot.send_message(uid, text_reply)
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

    # --- Parse transaction text ---
    parsed = parse_transaction(text)
    source = "gemini"
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
    if action == "transfer" and from_bank and to_bank:
        add_transaction(uid, -abs(amount), "transfer", desc, is_asset=0, bank_account=from_bank)
        add_transaction(uid, abs(amount), "transfer", desc, is_asset=0, bank_account=to_bank)
        after_tx_sync(uid, -abs(amount), "transfer", desc, from_bank)
        after_tx_sync(uid, abs(amount), "transfer", desc, to_bank)
        bot.reply_to(message, f"✅ Transferred {abs(amount):,.0f} from {from_bank} to {to_bank}.")
        return

    # --- INCOME / EXPENSE with bank ---
    if bank:
        tid = add_transaction(uid, amount, cat, desc, is_asset=0, bank_account=bank)
        after_tx_sync(uid, amount, cat, desc, bank, tid)
        bal = get_balance()
        text_reply = f"✅ Recorded: {amount:+,.0f} - {desc} ({bank})\nBalance: {bal:,.0f}"
        if amount < -199:
            save_state(uid, {"pending_capitalize_decision": {"tid": tid, "value": abs(amount)}})
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("Yes", callback_data="cap:yes"),
                       InlineKeyboardButton("No", callback_data="cap:no"))
            bot.reply_to(message, text_reply + "\n\nCapitalize as asset?", reply_markup=markup)
        else:
            bot.reply_to(message, text_reply)
        return

    # --- No bank yet -> ask ---
    ask_bank(uid, amount, cat, desc)

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
