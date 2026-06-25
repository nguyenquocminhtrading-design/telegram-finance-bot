from datetime import date, timedelta
from database import get_db

VALID_BANKS = ["VCB", "ACB", "HDBANK", "CASH", "MOMO"]


def get_balance(user_id=0):
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as bal FROM transactions WHERE user_id = ? AND is_asset = 0",
        (user_id,),
    ).fetchone()
    conn.close()
    return round(row["bal"], 2) if row else 0.0


def get_all_bank_balances(user_id=0):
    """Trả về dict {bank: balance} theo thứ tự chuẩn và tổng balance."""
    conn = get_db()
    rows = conn.execute(
        "SELECT bank_account, SUM(amount) as balance FROM transactions"
        " WHERE bank_account IS NOT NULL AND bank_account != ''"
        " AND user_id = ?"
        " GROUP BY bank_account ORDER BY balance DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    balances = {r["bank_account"]: round(r["balance"], 2) for r in rows}
    ordered = {bank: round(balances.get(bank, 0.0), 2) for bank in VALID_BANKS}
    total = round(sum(ordered.values()), 2)
    return ordered, total


def get_monthly_summary(user_id=0, year=None, month=None):
    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month

    start = f"{year}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1}-01-01"
    else:
        end = f"{year}-{month + 1:02d}-01"

    conn = get_db()
    rows = conn.execute(
        """SELECT
               SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as income,
               SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as expense
           FROM transactions
           WHERE user_id = ? AND transaction_date >= ? AND transaction_date < ? AND is_asset = 0 AND category != 'transfer'""",
        (user_id, start, end),
    ).fetchone()
    conn.close()

    income = round(rows["income"] or 0, 2) if rows else 0
    expense = round(rows["expense"] or 0, 2) if rows else 0
    return {"income": income, "expense": expense, "net": round(income - expense, 2)}


def get_category_breakdown(user_id=0, year=None, month=None):
    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month

    start = f"{year}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1}-01-01"
    else:
        end = f"{year}-{month + 1:02d}-01"

    conn = get_db()
    rows = conn.execute(
        """SELECT category, SUM(ABS(amount)) as total
           FROM transactions
           WHERE user_id = ? AND amount < 0 AND transaction_date >= ? AND transaction_date < ? AND is_asset = 0 AND category != 'transfer'
           GROUP BY category ORDER BY total DESC""",
        (user_id, start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_cash_flow(user_id=0, months=12):
    today = date.today()
    result = []
    for i in range(months - 1, -1, -1):
        ym = today.month - i
        y = today.year
        while ym < 1:
            ym += 12
            y -= 1
        while ym > 12:
            ym -= 12
            y += 1
        summary = get_monthly_summary(user_id, y, ym)
        summary["year"] = y
        summary["month"] = ym
        summary["label"] = f"{y}-{ym:02d}"
        result.append(summary)
    return result


def get_top_categories(user_id=0, limit=5, year=None, month=None):
    breakdown = get_category_breakdown(user_id, year, month)
    return breakdown[:limit]


def get_full_report(user_id=0):
    balance = get_balance(user_id)
    today = date.today()
    monthly = get_monthly_summary(user_id, today.year, today.month)
    cash_flow = get_cash_flow(user_id)
    categories = get_category_breakdown(user_id)
    return {
        "balance": balance,
        "monthly": monthly,
        "cash_flow": cash_flow,
        "categories": categories,
    }
