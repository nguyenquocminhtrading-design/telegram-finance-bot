import re
import unicodedata
import logging

logger = logging.getLogger(__name__)

BANK_KEYWORDS = {
    "VCB": ["vcb", "vietcombank", "vietcom"],
    "ACB": ["acb", "asia commercial"],
    "HDBANK": ["hdbank", "hd bank"],
    "CASH": ["cash", "tiền mặt", "tien mat", "mặt", "tienmat"],
    "MOMO": ["momo", "ví điện tử"],
}

ACTION_KEYWORDS = {
    "income": ["nhận", "lương", "thưởng", "thu nhập", "lãi", "cổ tức",
               "bán", "được trả", "hoàn tiền", "cashback", "vào", "có"],
    "transfer": ["chuyển", "rút", "nạp", "gửi", "chuyển khoản", "transfer",
                 "đi", "đưa", "sang"],
}

CATEGORY_KEYWORDS = {
    "food": ["ăn", "cơm", "phở", "bún", "hủ tiếu", "cháo", "miến", "mì",
             "bánh", "trà sữa", "cafe", "cà phê", "nước", "nhậu", "lẩu",
             "nướng", "lunch", "dinner", "breakfast", "trưa", "tối", "sáng",
             "khuya", "uống", "đồ uống", "starbucks", "highlands", "kfc",
             "lotteria", "grab food", "pizza", "burger", "snack", "trái cây",
             "hoa quả", "rau", "thịt", "cá", "siêu thị", "chợ", "thực phẩm",
             "đi chợ", "đi siêu thị", "bách hóa", "co.op", "winmart"],
    "transport": ["xăng", "đi", "xe", "taxi", "grab", "bus", "vé", "tàu",
                  "máy bay", "di chuyển", "đi lại", "parking", "gửi xe",
                  "đỗ xe", "xăng xe", "đổ xăng", "rửa xe", "bảo dưỡng",
                  "cầu đường", "phà", "xe ôm", "gojek", "be", "xanh sm",
                  "cưới", "hoa", "quà tặng"],
    "entertainment": ["phim", "movie", "cgv", "lotte", "bhd", "game",
                      "netflix", "spotify", "karaoke", "hát", "chơi",
                      "du lịch", "tour", "khách sạn", "resort", "bar",
                      "pub", "club", "bida", "massage", "spa", "steam",
                      "nạp game", "giải trí"],
    "bill": ["điện", "nước", "mạng", "internet", "wifi", "cáp", "phone",
             "điện thoại", "viettel", "fpt", "vnpt", "mobifone",
             "vinaphone", "thuê nhà", "tiền nhà", "trọ", "chung cư",
             "phí quản lý", "trả góp", "tín dụng", "thẻ tín dụng",
             "bảo hiểm", "vay", "fe credit", "rác"],
    "health": ["bệnh", "thuốc", "nhà thuốc", "pharmacity", "long châu",
               "khám", "bác sĩ", "bệnh viện", "viện", "nha khoa", "răng",
               "mắt", "kính", "gym", "tập", "yoga", "fitness", "vitamin",
               "sức khỏe", "xét nghiệm"],
    "shopping": ["mua", "shop", "shopee", "lazada", "tiki", "sendo",
                 "áo", "quần", "giày", "dép", "túi", "ví", "balo",
                 "mỹ phẩm", "skincare", "son", "điện thoại", "laptop",
                 "tai nghe", "ốp lưng", "cáp sạc", "sạc dự phòng",
                 "đồ gia dụng", "sách", "fahasa", "quà", "tặng", "hoa",
                 "thế giới di động", "tgdd", "fpt shop", "cellphones",
                 "điện máy", "phụ kiện", "đồ chơi", "thú cưng", "pet"],
    "salary": ["lương", "thưởng", "thu nhập", "lì xì", "phụ cấp",
               "hoa hồng", "freelance"],
    "transfer": ["chuyển", "rút", "nạp", "chuyển khoản"],
}

AMOUNT_PATTERNS = [
    (r'(\d+\.?\d*)\s*tr(?:iệu)?', lambda m: float(m.group(1)) * 1_000_000),
    (r'(\d+\.?\d*)\s*k', lambda m: float(m.group(1)) * 1000),
    (r'(\d+\.?\d*)\s*nghìn', lambda m: float(m.group(1)) * 1000),
    (r'(\d+)[\s,]*\.?\s*đ', lambda m: float(m.group(1).replace(',', ''))),
    (r'(\d{1,3}(?:[.,]\d{3})+)', lambda m: float(m.group(1).replace('.', '').replace(',', ''))),
    (r'(\d+)', lambda m: float(m.group(1))),
]

# Matches: "chuyển 2tr từ VCB sang ACB" / "chuyển 500k từ acb vào momo"
TRANSFER_PATTERN = re.compile(
    r'(?:chuy[eê]n|r[uú]t|n[aạ]p|g[uử]i|chuy[eê]n\s*kho[aả]n)\s+'
    r'([\d]+(?:[.,][\d]+)?(?:\s*(?:tr(?:i[eê]u)?|k|nghìn))?)\s*'
    r'(?:t[uừừ]|[oở])\s*([\w]+)\s+'
    r'(?:sang|[dđ][eế]n|v[aà]o|[dđ]i|qua|cho)\s*([\w]+)',
    re.IGNORECASE | re.UNICODE,
)

# Matches: "rút 2tr từ VCB" (destination defaults to CASH)
TRANSFER_SHORT_PATTERN = re.compile(
    r'(?:r[uú]t|n[aạ]p)\s+'
    r'([\d]+(?:[.,][\d]+)?(?:\s*(?:tr(?:i[eê]u)?|k|nghìn))?)\s*'
    r'(?:t[uừừ]|[oở])\s*([\w]+)',
    re.IGNORECASE | re.UNICODE,
)


def resolve_bank(text):
    text_stripped = text.upper().strip()
    text_lower = text.lower().strip()
    for bank, keywords in BANK_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower or text_stripped == bank:
                return bank
    # If it's a short known bank name return as-is uppercase
    return text_stripped if text_stripped else None


def parse_amount_local(text):
    for pattern, func in AMOUNT_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE | re.UNICODE)
        if m:
            return func(m)
    return None


def parse_transaction_local(text):
    # Chuẩn hóa Unicode NFC — điện thoại gửi NFD, regex dùng NFC
    text = unicodedata.normalize('NFC', text)
    text_lower = text.lower().strip()
    text_original = text.strip()

    result = {
        "action": "expense",
        "amount": None,
        "category": "other",
        "bank": None,
        "from_bank": None,
        "to_bank": None,
        "description": text_original,
        "from_local": True,
    }

    # 1. Detect full TRANSFER: "chuyển X từ A sang B"
    m = TRANSFER_PATTERN.search(text)
    if m:
        result["action"] = "transfer"
        result["amount"] = parse_amount_local(m.group(1))
        result["from_bank"] = resolve_bank(m.group(2))
        result["to_bank"] = resolve_bank(m.group(3))
        result["description"] = f"Chuyển từ {result['from_bank']} sang {result['to_bank']}"
        logger.info(f"Local: detected transfer {result['from_bank']} -> {result['to_bank']} amount={result['amount']}")
        return result

    # 2. Detect short TRANSFER: "rút X từ A" → to_bank defaults to CASH
    m = TRANSFER_SHORT_PATTERN.search(text)
    if m:
        result["action"] = "transfer"
        result["amount"] = parse_amount_local(m.group(1))
        result["from_bank"] = resolve_bank(m.group(2))
        result["to_bank"] = "CASH"
        result["description"] = f"Rút từ {result['from_bank']} ra tiền mặt"
        logger.info(f"Local: detected withdrawal from {result['from_bank']}, amount={result['amount']}")
        return result

    # 3. Extract amount
    result["amount"] = parse_amount_local(text)

    # 4. Detect INCOME
    income_score = sum(1 for kw in ACTION_KEYWORDS["income"] if kw in text_lower)
    expense_score = sum(1 for kw in ["mua", "ăn", "đi", "trả", "đóng"] if kw in text_lower)
    if income_score > 0 and income_score >= expense_score:
        result["action"] = "income"

    # 5. Detect bank
    for bank, keywords in BANK_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                result["bank"] = bank
                break
        if result["bank"]:
            break

    # 6. Category by keyword scoring
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[cat] = score
    if scores:
        best_cat = max(scores, key=scores.get)
        if scores[best_cat] >= 1:
            result["category"] = best_cat

    # 7. Clean description: remove amount & bank words
    desc = text_original
    for pat, _ in AMOUNT_PATTERNS:
        desc = re.sub(pat, '', desc, flags=re.IGNORECASE | re.UNICODE)
    for bank_kws in BANK_KEYWORDS.values():
        for kw in bank_kws:
            desc = re.sub(re.escape(kw), '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'\s+', ' ', desc).strip()
    if desc:
        result["description"] = desc[:80]

    logger.info(f"Local parsed: action={result['action']} amount={result['amount']} "
                f"cat={result['category']} bank={result['bank']}")
    return result
