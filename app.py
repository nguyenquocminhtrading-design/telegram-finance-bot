import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import date, datetime

import telebot
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file
import io
import openpyxl
import concurrent.futures
import threading

from config import TELEGRAM_TOKEN, WEBHOOK_URL, SECRET_KEY, DATABASE_PATH, ADMIN_USER_ID
from database import init_db, get_transactions, get_transaction_by_id
from database import update_transaction, delete_transaction, count_transactions
from database import get_assets, get_categories, get_setting, set_setting, get_db
from finance_logic import get_balance, get_monthly_summary, get_category_breakdown, get_cash_flow, get_full_report
from asset_manager import get_asset_summary, run_monthly_depreciation
from scheduler import create_scheduler

log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
file_handler = RotatingFileHandler("bot.log", maxBytes=5*1024*1024, backupCount=3)
file_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
logging.getLogger().addHandler(file_handler)
logging.getLogger().addHandler(console_handler)
logging.getLogger().setLevel(logging.INFO)

logger = logging.getLogger(__name__)

WEB_USER_ID = ADMIN_USER_ID or 0

app = Flask(__name__)
app.secret_key = SECRET_KEY

init_db()

scheduler = create_scheduler()
scheduler.start()

webhook_lock = threading.Lock()
recent_update_ids = set()
error_counter = 0


@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    report = get_full_report(WEB_USER_ID)
    assets = get_asset_summary(WEB_USER_ID)
    recent_transactions = get_transactions(WEB_USER_ID, limit=5, offset=0)
    return render_template("dashboard.html", report=report, assets=assets, recent_transactions=recent_transactions)


@app.route("/snapshot")
def snapshot():
    report = get_full_report(WEB_USER_ID)
    assets = get_asset_summary(WEB_USER_ID)
    return render_template("mobile_snapshot.html", report=report, assets=assets)


@app.route("/transactions")
def transactions_page():
    page = request.args.get("page", 1, type=int)
    per_page = 20
    category = request.args.get("category")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    offset = (page - 1) * per_page
    txs = get_transactions(WEB_USER_ID, per_page, offset, category, start_date, end_date)
    total = count_transactions(WEB_USER_ID, category, start_date, end_date)
    cats = get_categories(WEB_USER_ID)
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
    summary = get_asset_summary(WEB_USER_ID)
    return render_template("assets.html", summary=summary)


@app.route("/reports")
def reports_page():
    report = get_full_report(WEB_USER_ID)
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
    txs = get_transactions(WEB_USER_ID, per_page, offset, category, start_date, end_date)
    total = count_transactions(WEB_USER_ID, category, start_date, end_date)
    return jsonify({"data": txs, "total": total, "page": page, "per_page": per_page})


@app.route("/api/transactions", methods=["POST"])
def api_add_transaction():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    from database import add_transaction
    tid = add_transaction(
        user_id=WEB_USER_ID,
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
    report = get_full_report(WEB_USER_ID)
    return jsonify(report)


@app.route("/api/assets")
def api_assets():
    summary = get_asset_summary(WEB_USER_ID)
    return jsonify(summary)


@app.route("/api/categories")
def api_categories():
    cats = get_categories(WEB_USER_ID)
    return jsonify(cats)


@app.route("/api/run-depreciation", methods=["POST"])
def api_run_depreciation():
    results = run_monthly_depreciation(WEB_USER_ID)
    return jsonify({"depreciated": len(results), "details": results})


@app.route("/api/export/excel", methods=["GET"])
def api_export_excel():
    txs = get_transactions(WEB_USER_ID, 10000, 0)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"
    headers = ["ID", "Date", "Amount", "Category", "Description", "Is Asset"]
    ws.append(headers)
    for tx in txs:
        ws.append([
            tx["id"], tx["transaction_date"], tx["amount"],
            tx["category"], tx["description"],
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

    raw = request.get_data(as_text=True)
    try:
        update = telebot.types.Update.de_json(raw)
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
        return "Bad Request", 400

    uid = update.update_id

    if uid in recent_update_ids:
        return "OK", 200

    recent_update_ids.add(uid)
    if len(recent_update_ids) > 500:
        recent_update_ids.clear()

    if not webhook_lock.acquire(timeout=12):
        logger.warning(f"Webhook busy, dropping update {uid}")
        return "retry", 429

    from bot import bot
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            f = pool.submit(bot.process_new_updates, [update])
            f.result(timeout=12)
        logger.info(f"Webhook processed: update {uid}")
        global error_counter
        error_counter = 0
    except concurrent.futures.TimeoutError:
        logger.error(f"Webhook timeout: update {uid} > 12s")
        error_counter += 1
    except Exception as e:
        logger.error(f"Webhook error: update {uid}: {e}", exc_info=True)
        error_counter += 1
    finally:
        webhook_lock.release()

    return "OK", 200


@app.route("/health")
def health():
    checks = {"status": "ok", "timestamp": datetime.now().isoformat()}
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = str(e)
        checks["status"] = "degraded"
    checks["scheduler"] = "running" if scheduler.running else "stopped"
    if not scheduler.running:
        try:
            scheduler.start()
            checks["scheduler"] = "restarted"
        except Exception as e:
            checks["scheduler"] = f"failed: {e}"
            checks["status"] = "degraded"
    checks["error_counter"] = error_counter
    status_code = 200 if checks["status"] == "ok" else 503
    return jsonify(checks), status_code


@app.route("/keepalive")
def keepalive():
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except Exception:
        pass
    if not scheduler.running:
        try:
            scheduler.start()
        except Exception:
            pass
    from database import cleanup_stale_states
    try:
        cleanup_stale_states()
    except Exception:
        pass
    return jsonify({"ok": True, "time": datetime.now().isoformat()})


@app.route("/webhook/register", methods=["POST"])
def register_webhook():
    import requests
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
        json={"url": f"{WEBHOOK_URL}", "max_connections": 1}
    )
    return jsonify(resp.json())


@app.route("/webhook/info")
def webhook_info():
    import requests
    resp = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getWebhookInfo"
    )
    return jsonify(resp.json())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
