import os
import logging
from datetime import date, datetime

import telebot
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file
import io
import openpyxl

from config import TELEGRAM_TOKEN, WEBHOOK_URL, SECRET_KEY, DATABASE_PATH
from database import init_db, get_transactions, get_transaction_by_id
from database import update_transaction, delete_transaction, count_transactions
from database import get_assets, get_categories, get_setting, set_setting
from finance_logic import get_balance, get_monthly_summary, get_category_breakdown, get_cash_flow, get_full_report
from asset_manager import get_asset_summary, run_monthly_depreciation
from scheduler import create_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = SECRET_KEY

init_db()

scheduler = create_scheduler()
scheduler.start()


@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    report = get_full_report()
    assets = get_asset_summary()
    return render_template("dashboard.html", report=report, assets=assets)


@app.route("/snapshot")
def snapshot():
    report = get_full_report()
    assets = get_asset_summary()
    return render_template("mobile_snapshot.html", report=report, assets=assets)


@app.route("/transactions")
def transactions_page():
    page = request.args.get("page", 1, type=int)
    per_page = 20
    category = request.args.get("category")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    offset = (page - 1) * per_page
    txs = get_transactions(0, per_page, offset, category, start_date, end_date)
    total = count_transactions(0, category, start_date, end_date)
    cats = get_categories(0)
    return render_template(
        "transactions.html",
        transactions=txs,
        categories=cats,
        page=page,
        per_page=per_page,
        total=total,
        selected_category=category,
        start_date=start_date,
        end_date=end_date,
    )


@app.route("/assets")
def assets_page():
    summary = get_asset_summary()
    return render_template("assets.html", summary=summary)


@app.route("/reports")
def reports_page():
    report = get_full_report()
    return render_template("reports.html", report=report)


@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/ping")
def ping():
    return "pong", 200


@app.route("/api/transactions", methods=["GET"])
def api_transactions():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    category = request.args.get("category")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    offset = (page - 1) * per_page
    txs = get_transactions(0, per_page, offset, category, start_date, end_date)
    total = count_transactions(0, category, start_date, end_date)
    return jsonify({"data": txs, "total": total, "page": page, "per_page": per_page})


@app.route("/api/transactions", methods=["POST"])
def api_add_transaction():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    from database import add_transaction
    tid = add_transaction(
        user_id=0,
        amount=data.get("amount", 0),
        category=data.get("category", "other"),
        description=data.get("description", ""),
        transaction_date=data.get("transaction_date", date.today().isoformat()),
        is_asset=data.get("is_asset", 0),
    )
    return jsonify({"id": tid}), 201


@app.route("/api/transactions/<int:tid>", methods=["PUT"])
def api_update_transaction(tid):
    data = request.get_json()
    tx = get_transaction_by_id(tid)
    if not tx:
        return jsonify({"error": "Not found"}), 404
    update_transaction(
        tid,
        data.get("amount", tx["amount"]),
        data.get("category", tx["category"]),
        data.get("description", tx["description"]),
        data.get("transaction_date", tx["transaction_date"]),
    )
    return jsonify({"ok": True})


@app.route("/api/transactions/<int:tid>", methods=["DELETE"])
def api_delete_transaction(tid):
    tx = get_transaction_by_id(tid)
    if not tx:
        return jsonify({"error": "Not found"}), 404
    delete_transaction(tid)
    return jsonify({"ok": True})


@app.route("/api/summary")
def api_summary():
    report = get_full_report()
    return jsonify(report)


@app.route("/api/assets")
def api_assets():
    summary = get_asset_summary()
    return jsonify(summary)


@app.route("/api/categories")
def api_categories():
    cats = get_categories(0)
    return jsonify(cats)


@app.route("/api/run-depreciation", methods=["POST"])
def api_run_depreciation():
    results = run_monthly_depreciation()
    return jsonify({"depreciated": len(results), "details": results})


@app.route("/api/export/excel", methods=["GET"])
def api_export_excel():
    txs = get_transactions(0, 10000, 0) # Export up to 10k transactions
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"
    
    # Headers
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
    
    # Auto-adjust column widths
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = (max_length + 2)
        ws.column_dimensions[column].width = adjusted_width

    excel_file = io.BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)
    
    return send_file(
        excel_file,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"finance_export_{date.today().isoformat()}.xlsx"
    )


@app.route("/webhook/<token>", methods=["POST"])
def webhook(token):
    if token != TELEGRAM_TOKEN:
        return "Unauthorized", 403
    from bot import bot
    update = request.get_data(as_text=True)
    try:
        bot.process_new_updates([telebot.types.Update.de_json(update)])
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
