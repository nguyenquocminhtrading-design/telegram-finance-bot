import re
from datetime import datetime
import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import io
import openpyxl

from config import TELEGRAM_TOKEN, ADMIN_USER_ID, WEBHOOK_URL
from database import add_transaction, get_transactions, get_assets, get_categories, update_transaction
from database import add_asset
from asset_manager import get_asset_summary, liquidate_asset
from finance_logic import get_balance, get_monthly_summary, get_category_breakdown
from gsheets_sync import sync_expense_to_gsheet, sync_asset_to_gsheet
from excel_sync import sync_expense_to_excel
from simulation import run_monte_carlo, generate_projection_chart
from llm_parser import parse_transaction

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

user_state = {}

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
        "📝 *Logging Transactions:*\n"
        "  `+500 salary March`\n"
        "  `-200 lunch`\n"
        "  `-10000 laptop` (can be capitalized)\n\n"
        "💼 *Asset Management:*\n"
        "  `/buy <asset> <qty> <price>` - Buy asset\n"
        "  `/liquidate <id> <price>` - Sell asset\n"
        "  `/asset` - View all assets\n\n"
        "📈 *Reports & Status:*\n"
        "  `/balance` - Current balance\n"
        "  `/report` - Monthly report\n"
        "  `/project <amount> <months>` - Monte Carlo Projection\n"
        "  `/export` - Export to Excel\n"
        "  `/web` - Dashboard link\n"
        "─────────────────────────────"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=["balance"])
def cmd_balance(message: Message):
    if not is_admin(message.from_user.id):
        return
    bal = get_balance()
    resp = f"Current Balance: **{bal:,.0f} VND**" if abs(bal) >= 1000 else f"Current Balance: **{bal}**"
    bot.reply_to(message, resp, parse_mode="Markdown")

@bot.message_handler(commands=["report"])
def cmd_report(message: Message):
    if not is_admin(message.from_user.id):
        return
    summary = get_monthly_summary()
    cats = get_category_breakdown()
    lines = [f"Report - {datetime.now().strftime('%Y-%m')}",
             f"Income: +{summary['income']:,.0f}",
             f"Expense: -{summary['expense']:,.0f}",
             f"Net: {summary['net']:,.0f}",
             ""]
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
             f"Total original: {summary['total_original']:,.0f}",
             f"Current value: {summary['total_current']:,.0f}",
             ""]
    for a in summary["assets"]:
        marker = " [active]" if a["is_active"] else " [done]"
        lines.append(f"- {a['name']}: {a['current_value']:,.0f}/{a['original_value']:,.0f}{marker}")
    bot.reply_to(message, "\n".join(lines))

@bot.message_handler(commands=["web"])
def cmd_web(message: Message):
    base = WEBHOOK_URL.rsplit("/webhook", 1)[0] if "/webhook" in WEBHOOK_URL else WEBHOOK_URL
    if base.startswith("https://"):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Open Mini App", web_app=WebAppInfo(url=f"{base}/snapshot")))
        bot.reply_to(message, f"Dashboard: {base}/dashboard\nOr open Mini App below:", reply_markup=markup)
    else:
        bot.reply_to(message, f"Dashboard: {base}/dashboard\n(Mini App requires HTTPS webhook URL)")

@bot.message_handler(commands=["project", "montecarlo"])
def cmd_project(message: Message):
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split()
    monthly_contribution = 5000000 # default 5tr
    months = 60 # default 60 months
    
    if len(parts) >= 2:
        try:
            monthly_contribution = parse_amount(parts[1])
        except ValueError:
            pass
            
    if len(parts) >= 3:
        try:
            months = int(parts[2])
        except ValueError:
            pass
            
    bot.reply_to(message, f"🏃 Running Monte Carlo simulation...\n"
                          f"Monthly Contribution: {monthly_contribution:,.0f} VND\n"
                          f"Period: {months} months")
                          
    # Get current active assets value
    summary = get_asset_summary()
    current_portfolio_value = summary['total_current']
    
    # Run simulation
    paths = run_monte_carlo(current_portfolio_value, monthly_contribution, months=months)
    chart_buf, stats = generate_projection_chart(paths, monthly_contribution)
    
    # Build reply text
    text = (
        f"📊 **Projection Results ({months} Months)** 📊\n\n"
        f"Starting Portfolio: {current_portfolio_value:,.0f} VND\n"
        f"Monthly Added: {monthly_contribution:,.0f} VND\n"
        f"Total Capital Invested: {stats['capital']:,.0f} VND\n\n"
        f"📉 Worst Case (10%): {stats['p10']:,.0f} VND\n"
        f"📈 **Expected (Median): {stats['median']:,.0f} VND**\n"
        f"🚀 Best Case (90%): {stats['p90']:,.0f} VND"
    )
    
    bot.send_photo(message.chat.id, photo=chart_buf, caption=text, parse_mode="Markdown")

@bot.message_handler(commands=["liquidate"])
def cmd_liquidate(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "Usage: /liquidate <asset_id> <sell_price>")
        return
    try:
        aid = int(parts[1])
        price = float(parts[2])
    except ValueError:
        bot.reply_to(message, "Invalid asset ID or price.")
        return
    result = liquidate_asset(aid, price)
    if result is None:
        bot.reply_to(message, "Asset not found.")
        return
    bot.reply_to(
        message,
        f"Liquidated {result['asset_name']}.\n"
        f"Sold for: {result['sell_price']:,.0f}\n"
        f"Remaining book value: {result['remaining_value']:,.0f}\n"
        f"Gain/Loss: {result['gain_loss']:+,.0f}",
    )

@bot.message_handler(commands=["export"])
def cmd_export(message: Message):
    if not is_admin(message.from_user.id):
        return
    bot.reply_to(message, "Generating Excel file, please wait...")
    txs = get_transactions(0, 10000, 0)
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"
    
    headers = ["ID", "Date", "Amount", "Category", "Description", "Is Asset"]
    ws.append(headers)
    
    for tx in txs:
        ws.append([
            tx["id"],
            tx["transaction_date"],
            tx["amount"],
            tx["category"],
            tx["description"],
            "Yes" if tx["is_asset"] else "No"
        ])
        
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        ws.column_dimensions[column].width = max_length + 2

    excel_file = io.BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)
    
    bot.send_document(
        message.chat.id,
        document=excel_file,
        visible_file_name=f"finance_export_{datetime.now().strftime('%Y%m%d')}.xlsx"
    )

@bot.message_handler(commands=["buy"])
def cmd_buy(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        bot.reply_to(message, "Usage: /buy <asset_name> <quantity> <price_per_unit>\nExample: /buy VNM 100 65000")
        return
    
    asset_name = parts[1]
    try:
        qty = float(parts[2])
        price = parse_amount(parts[3])
        total_value = qty * price
    except ValueError:
        bot.reply_to(message, "Invalid quantity or price.")
        return
    
    # Add transaction for expense
    tid = add_transaction(message.from_user.id, -total_value, "investment", f"Buy {qty} {asset_name} @ {price}", is_asset=1)
    
    # Capitalize it
    aid = add_asset(message.from_user.id, tid, asset_name, total_value, 1) # Depreciate in 1 month (or could be 0, but logic expects >0)
    
    # Sync to Portfolio Google Sheet
    gs_ok, gs_err = sync_asset_to_gsheet({
        "date": datetime.now().isoformat()[:10],
        "name": asset_name,
        "value": total_value,
        "note": f"Bought {qty} units at {price}"
    }, is_buy=True)
    if not gs_ok:
        bot.send_message(
            message.chat.id,
            f"⚠️ *Cảnh báo:* Không sync tài sản vào Google Sheet!\n"
            f"Lỗi: `{gs_err}`",
            parse_mode="Markdown"
        )
    
    bot.reply_to(message, f"✅ Bought {qty} of {asset_name} for total {total_value:,.0f} VND.\nAsset tracked!")

@bot.message_handler(commands=["sell"])
def cmd_sell(message: Message):
    if not is_admin(message.from_user.id):
        return
    bot.reply_to(message, "To sell, use /liquidate <asset_id> <sell_price> for now.")

@bot.message_handler(func=lambda m: True)
def handle_message(message: Message):
    if not is_admin(message.from_user.id):
        return

    uid = message.from_user.id
    text = message.text.strip()

    # Thử gọi LLM
    parsed = parse_transaction(text)
    
    amount = None
    desc = None
    cat = None
    bank = None
    is_transfer = False
    from_bank = None
    to_bank = None

    if parsed and "amount" in parsed and parsed["amount"] is not None:
        try:
            amount = float(parsed["amount"])
            if parsed.get("action") == "expense":
                amount = -abs(amount)
            elif parsed.get("action") == "income":
                amount = abs(amount)
            elif parsed.get("action") == "transfer":
                is_transfer = True
                from_bank = parsed.get("from_bank")
                to_bank = parsed.get("to_bank")
                
            desc = parsed.get("description", text)
            cat = parsed.get("category", guess_category(desc))
            bank = parsed.get("bank")
        except ValueError:
            parsed = None # Bị lỗi cast số thì rớt xuống fallback
            
    if not amount:
        # Fallback to Regex
        match = re.match(r"^([+-])\s*([\d.,kKtTrR]+)\s*(.*)", text)
        if not match:
            bot.reply_to(
                message,
                "Lỗi phân tích cú pháp hoặc Gemini API không phản hồi.\n"
                "Sử dụng Format chuẩn: +<amount> <description> hoặc -<amount> <description>\n"
                "Ví dụ: +500 lương, -200 ăn trưa, -10tr mua laptop",
            )
            return

        sign = match.group(1)
        raw_amount = match.group(2)
        desc = match.group(3).strip()

        try:
            amount = parse_amount(raw_amount)
        except ValueError:
            bot.reply_to(message, "Sai định dạng số tiền.")
            return

        if sign == "-":
            amount = -amount
            
        cat = guess_category(desc)
        if cat == "transfer":
            is_transfer = True

    # Process Transfer
    if is_transfer:
        if not from_bank or not to_bank:
            bot.reply_to(message, f"Giao dịch: Chuyển tiền\nSố tiền: {abs(amount):,.0f}\nLỗi: AI không nhận diện được ngân hàng gửi và nhận. Hãy thử nói rõ hơn, vd: 'chuyển 50k từ VCB sang CASH'")
            return
            
        # Execute Transfer
        tid_from = add_transaction(uid, -abs(amount), "transfer", desc, is_asset=0, bank_account=from_bank)
        tid_to = add_transaction(uid, abs(amount), "transfer", desc, is_asset=0, bank_account=to_bank)
        
        # Sync BOTH to Google Sheets
        sync_expense_to_gsheet({
            "date": datetime.now().isoformat()[:10],
            "amount": -abs(amount),
            "category": "transfer",
            "description": f"Chuyển tiền sang {to_bank}: {desc}",
            "bank_account": from_bank
        })
        sync_expense_to_gsheet({
            "date": datetime.now().isoformat()[:10],
            "amount": abs(amount),
            "category": "transfer",
            "description": f"Nhận tiền từ {from_bank}: {desc}",
            "bank_account": to_bank
        })
        
        bot.reply_to(message, f"✅ Đã chuyển {abs(amount):,.0f} VND từ {from_bank} sang {to_bank}.")
        return

    # Normal Expense / Income
    if bank:
        # Bank is determined, record immediately
        tid = add_transaction(uid, amount, cat, desc, is_asset=0, bank_account=bank)
        
        # Sync
        gs_ok, gs_err = sync_expense_to_gsheet({
            "date": datetime.now().isoformat()[:10],
            "amount": amount,
            "category": cat,
            "description": desc,
            "bank_account": bank
        })
        if not gs_ok:
            bot.send_message(uid, f" *Cảnh báo:* Ghi vào Google Sheet thất bại!\nLỗi: `{gs_err}`", parse_mode="Markdown")
            
        sync_expense_to_excel({
            "date": datetime.now().isoformat()[:10],
            "amount": amount,
            "category": cat,
            "description": desc,
            "bank_account": bank
        })
        
        bot.reply_to(message, f"✅ Đã lưu: {amount:+,.0f} - {desc} ({bank})\nSố dư: {get_balance():,.0f}")
        return

    user_state[uid] = {
        "pending_tx": {
            "amount": amount,
            "category": cat,
            "description": desc,
        }
    }
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("VCB", callback_data="bank_VCB"),
        InlineKeyboardButton("ACB", callback_data="bank_ACB"),
        InlineKeyboardButton("HDBANK", callback_data="bank_HDBANK"),
        InlineKeyboardButton("CASH", callback_data="bank_CASH")
    )
    
    bot.reply_to(
        message,
        f"Amount: {amount:+,.0f}\nDesc: {desc}\n\nXin hãy chọn tài khoản:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    uid = call.from_user.id
    data = call.data

    if data.startswith("bank_"):
        bank = data.split("_")[1]
        state = user_state.get(uid, {}).get("pending_tx")
        if not state:
            bot.answer_callback_query(call.id, "Session expired.")
            return
            
        amount = state["amount"]
        desc = state["description"]
        cat = state["category"]
        
        tid = add_transaction(uid, amount, cat, desc, is_asset=0, bank_account=bank)
        
        # Sync to Expense Google Sheet
        gs_ok, gs_err = sync_expense_to_gsheet({
            "date": datetime.now().isoformat()[:10],
            "amount": amount,
            "category": cat,
            "description": desc,
            "bank_account": bank
        })
        if not gs_ok:
            bot.send_message(
                uid,
                f"⚠️ *Cảnh báo:* Ghi vào Google Sheet thất bại!\n"
                f"Dữ liệu đã lưu vào database local.\n"
                f"Lỗi: `{gs_err}`",
                parse_mode="Markdown"
            )

        # Sync to local Excel file
        sync_expense_to_excel({
            "date": datetime.now().isoformat()[:10],
            "amount": amount,
            "category": cat,
            "description": desc,
            "bank_account": bank
        })
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        if amount < -1000:
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("Yes - capitalize", callback_data=f"cap_{tid}_{abs(amount)}"),
                InlineKeyboardButton("No", callback_data=f"nocap_{tid}"),
            )
            bot.send_message(
                uid,
                f"Recorded: {amount:+,.0f} - {desc} ({bank})\n\n"
                f"Is this an asset to capitalize (depreciate over time)?",
                reply_markup=markup,
            )
        else:
            bal = get_balance()
            bot.send_message(
                uid,
                f"Recorded: {amount:+,.0f} - {desc} ({bank})\nBalance: {bal:,.0f}",
            )
            
        user_state[uid] = {"pending_capitalize": None}
        bot.answer_callback_query(call.id)

    elif data.startswith("cap_"):
        parts = data.split("_")
        tid = int(parts[1])
        asset_value = float(parts[2])
        user_state[uid] = {
            "pending_capitalize": {"tid": tid, "value": asset_value, "step": "ask_name"}
        }
        bot.send_message(uid, "Asset name (e.g. MacBook Pro 14):")
        bot.answer_callback_query(call.id)

    elif data.startswith("nocap_"):
        bot.send_message(uid, "Saved as regular expense.")
        bot.answer_callback_query(call.id)

    elif data == "cancel_capitalize":
        user_state[uid] = {}
        bot.send_message(uid, "Cancelled.")
        bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id].get("pending_capitalize"))
def handle_capitalize_flow(message: Message):
    uid = message.from_user.id
    state = user_state[uid]["pending_capitalize"]
    step = state.get("step")

    if step == "ask_name":
        state["name"] = message.text.strip()
        state["step"] = "ask_months"
        bot.reply_to(message, f"Asset name: {state['name']}\nDepreciation period (months, e.g. 12):")

    elif step == "ask_months":
        try:
            months = int(message.text.strip())
            if months < 1:
                raise ValueError
        except ValueError:
            bot.reply_to(message, "Please enter a valid number of months (>= 1).")
            return

        tid = state["tid"]
        name = state["name"]
        value = state["value"]
        aid = add_asset(uid, tid, name, value, months)

        from database import get_db
        conn = get_db()
        conn.execute("UPDATE transactions SET is_asset = 1 WHERE id = ?", (tid,))
        conn.commit()
        conn.close()

        bot.reply_to(
            message,
            f"Asset capitalized!\n"
            f"Name: {name}\n"
            f"Value: {value:,.0f}\n"
            f"Depreciation: {months} months\n"
            f"Monthly: {value / months:,.0f}\n\n"
            f"Use /asset to track it.",
        )
        
        # Sync to Portfolio Google Sheet
        gs_ok, gs_err = sync_asset_to_gsheet({
            "date": datetime.now().isoformat()[:10],
            "name": name,
            "value": value,
            "note": "Capitalized asset"
        }, is_buy=True)
        if not gs_ok:
            bot.send_message(
                uid,
                f"⚠️ *Cảnh báo:* Không sync tài sản vào Google Sheet!\n"
                f"Dữ liệu đã lưu vào database local.\n"
                f"Lỗi: `{gs_err}`",
                parse_mode="Markdown"
            )

        user_state[uid] = {}

def guess_category(desc):
    desc_lower = desc.lower()
    categories = {
        "food": [
            "food", "eat", "lunch", "dinner", "breakfast", "grocer", "ăn", "uống", "cơm", "phở", "bún", "hủ tiếu", "cháo",
            "miến", "mì", "bánh", "trà sữa", "cafe", "cà phê", "nước", "nhậu", "hải sản", "lẩu", "nướng", "kfc", "lotteria",
            "highland", "starbucks", "phúc long", "phuc long", "thức ăn", "thực phẩm", "siêu thị", "chợ", "rau", "thịt", "cá",
            "trái cây", "hoa quả", "kẹo", "snack", "gà", "bò", "heo", "trưa", "tối", "sáng", "khuya", "ăn vặt", "nấu",
            "pizza", "burger", "mcdonald", "tocotoco", "gongcha", "koi", "the coffee house", "tch", "bạch tuộc", "sushi", "sashimi"
        ],
        "transport": [
            "transport", "taxi", "grab", "bus", "fuel", "gas", "parking", "xăng", "xe", "di chuyển", "đi lại", "vé", "tàu",
            "máy bay", "gojek", "be", "xanh sm", "gọi xe", "đỗ xe", "gửi xe", "rửa xe", "bảo dưỡng", "sửa xe", "nhớt",
            "thay nhớt", "cầu đường", "bot", "vetch", "epass", "grabcar", "grabbike", "xe ôm", "phà", "trạm thu phí"
        ],
        "salary": [
            "salary", "income", "bonus", "wage", "lương", "thưởng", "thu nhập", "nhận", "cấp", "lì xì", "bán", "tiền vô",
            "lãi", "cổ tức", "hoa hồng", "dự án", "freelance", "trả nợ", "hoàn tiền", "cashback", "tạm ứng", "phụ cấp"
        ],
        "entertainment": [
            "entertain", "movie", "game", "netflix", "spotify", "giải trí", "phim", "cgv", "lotte", "bhd", "chơi", "du lịch",
            "đi chơi", "hát", "karaoke", "bar", "pub", "club", "kịch", "nhạc", "youtube", "premium", "nạp", "steam",
            "thú cưng", "mèo", "chó", "pet", "hẹn hò", "date", "đồ chơi", "tour", "khách sạn", "resort", "bida", "massage"
        ],
        "bill": [
            "bill", "electric", "water", "internet", "phone", "rent", "điện", "nước", "mạng", "wifi", "cáp", "viễn thông",
            "viettel", "fpt", "vnpt", "mobifone", "vinaphone", "thuê bao", "tiền nhà", "thuê nhà", "trọ", "phí quản lý",
            "chung cư", "bảo vệ", "rác", "trả góp", "tín dụng", "credit", "thẻ", "khoản vay", "fe credit", "bảo hiểm", "vay"
        ],
        "health": [
            "health", "doctor", "medicine", "hospital", "gym", "khám", "bệnh", "thuốc", "nhà thuốc", "pharmacity", "long châu",
            "bác sĩ", "nha khoa", "răng", "mắt", "kính", "tập", "thể thao", "yoga", "fitness", "cali", "thực phẩm chức năng",
            "vitamin", "bảo hiểm y tế", "viện phí", "xét nghiệm", "sức khỏe", "massage", "spa", "chăm sóc"
        ],
        "shopping": [
            "shop", "buy", "purchase", "cloth", "shoe", "mua sắm", "quần", "áo", "giày", "dép", "túi", "ví", "balo",
            "mỹ phẩm", "skincare", "son", "shopee", "lazada", "tiki", "tiktok", "siêu thị", "coop", "winmart", "go!",
            "bigc", "bách hóa", "đồ gia dụng", "điện máy", "thế giới di động", "tgdd", "fpt shop", "cellphones", "điện thoại",
            "laptop", "phụ kiện", "tai nghe", "ốp lưng", "cáp", "sạc", "quà", "tặng", "hoa", "đồ", "sách", "fahasa"
        ],
        "transfer": [
            "chuyển", "rút", "transfer", "atm", "tiền mặt"
        ]
    }
    for cat, keywords in categories.items():
        for kw in keywords:
            if kw in desc_lower:
                return cat
    return "other"


def set_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
