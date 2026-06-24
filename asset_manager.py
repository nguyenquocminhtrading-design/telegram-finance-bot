from datetime import date, datetime
from database import (
    get_assets,
    get_asset_by_id,
    update_asset_value,
    deactivate_asset,
    log_depreciation,
    add_transaction,
    get_db,
)


def run_monthly_depreciation(user_id=0, reference_date=None):
    if reference_date is None:
        reference_date = date.today()
    month_key = reference_date.strftime("%Y-%m")

    assets = get_assets(user_id, active_only=True)
    results = []

    for asset in assets:
        aid = asset["id"]
        current = asset["current_value"]
        monthly = asset["monthly_depreciation"]

        if current <= 0:
            deactivate_asset(aid)
            continue

        dep_amount = min(monthly, current)
        remaining = round(current - dep_amount, 2)
        update_asset_value(aid, remaining)
        log_depreciation(aid, month_key, dep_amount, remaining)

        desc = f"Depreciation: {asset['name']} ({month_key})"
        add_transaction(
            user_id=user_id,
            amount=-dep_amount,
            category="depreciation",
            description=desc,
            transaction_date=reference_date.isoformat(),
            is_asset=0,
        )

        is_done = remaining <= 0
        if is_done:
            deactivate_asset(aid)

        results.append({
            "asset_id": aid,
            "name": asset["name"],
            "depreciation": dep_amount,
            "remaining": remaining,
            "fully_depreciated": is_done,
        })

        # Sync depreciation to Google Sheets
        try:
            from gsheets_sync import sync_depreciation_log, update_capitalized_asset_value
            sync_depreciation_log({
                "date": reference_date.isoformat(),
                "asset_name": asset["name"],
                "period": month_key,
                "amount": dep_amount,
                "remaining_value": remaining,
            })
            conn = get_db()
            row = conn.execute(
                "SELECT original_value FROM assets WHERE id = ?", (aid,)
            ).fetchone()
            conn.close()
            original = row["original_value"] if row else 0
            depreciated_sofar = round(original - remaining, 2)
            status = "Fully Depreciated" if is_done else "Active"
            update_capitalized_asset_value(asset["name"], remaining, depreciated_sofar, status)
        except Exception as e:
            print(f"[Depreciation] Sheet sync error for {asset['name']}: {e}")

    return results


def liquidate_asset(aid, sell_price, user_id=0):
    asset = get_asset_by_id(aid)
    if not asset:
        return None

    remaining = asset["current_value"]
    gain_loss = round(sell_price - remaining, 2)
    desc = f"Liquidation: {asset['name']} (sold for {sell_price})"

    tid = add_transaction(
        user_id=user_id,
        amount=sell_price,
        category="asset_liquidation",
        description=desc,
        is_asset=0,
    )

    from excel_sync import sync_asset_to_portfolio
    sync_asset_to_portfolio({
        "date": datetime.now().isoformat()[:10],
        "name": asset["name"],
        "value": sell_price,
        "note": f"Liquidated, remaining value: {remaining}"
    }, is_buy=False)

    deactivate_asset(aid)
    return {
        "transaction_id": tid,
        "asset_name": asset["name"],
        "sell_price": sell_price,
        "remaining_value": remaining,
        "gain_loss": gain_loss,
    }


def get_asset_summary(user_id=0):
    assets = get_assets(user_id, active_only=False)
    total_original = 0
    total_current = 0
    active_count = 0
    for a in assets:
        total_original += a["original_value"]
        total_current += a["current_value"]
        if a["is_active"]:
            active_count += 1
    return {
        "total_original": round(total_original, 2),
        "total_current": round(total_current, 2),
        "active_count": active_count,
        "total_assets": len(assets),
        "assets": assets,
    }
