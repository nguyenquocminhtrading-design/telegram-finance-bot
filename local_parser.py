import re
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
    (r'(\d+\.?\d*)\s*tr', lambda m: float(m.group(1)) * 1_000_000),
    (r'(\d+\.?\d*)\s*triệu', lambda m: float(m.group(1)) * 1_000_000),
    (r'(\d+\.?\d*)\s*k', lambda m: float(m.group(1)) * 1000),
    (r'(\d+\.?\d*)\s*nghìn', lambda m: float(m.group(1)) * 1000),
    (r'(\d+)[\s,]*\.?\s*đ', lambda m: float(m.group(1).replace(',', ''))),
    (r'(\d{1,3}(?:[.,]\d{3})+)', lambda m: float(m.group(1).replace('.', '').replace(',', ''))),
    (r'(\d+)', lambda m: float(m.group(1))),
]

TRANSFER_PATTERN = re.compile(
    r'(?:chuyển|rút|nạp|gửi|chuyển.khoản)\s+'
    r'(\d+[\d,.,kK,tT,rR,mM]*)\s*'
    r'(?:từ|tư|ở)\s*(\w+)\s*'
    r'(?:sang|đến|vào|đi|qua|cho)\s*(\w+)',
    re.IGNORECASE
)

TRANSFER_SHORT_PATTERN = re.compile(
    r'(?:rút|nạp)\s+(\d+[\d,.,kK,tT,rR,mM]*)\s*'
    r'(?:từ|tư|ở)\s*(\w+)',
    re.IGNORECASE
)


def resolve_bank(text):
    text = text.upper().strip()
    for bank, keywords in BANK_KEYWORDS.items():
        for kw in keywords:
            if kw in text.lower() or (len(text) <= 5 and bank[:len(text)] == text):
                return bank
    return text


def parse_amount_local(text):
    for pattern, func in AMOUNT_PATTERNS:
        m = re.search(pattern, text)
        if m:
            return func(m)
    return None


def parse_transaction_local(text):
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

    # 1. Detect TRANSFER
    m = TRANSFER_PATTERN.search(text)
    if m:
        result["action"] = "transfer"
        result["amount"] = parse_amount_local(m.group(1))
        b1 = m.group(2).upper()
        b2 = m.group(3).upper()
        result["from_bank"] = resolve_bank(b1)
        result["to_bank"] = resolve_bank(b2)
        result["description"] = f"Chuyển từ {result['from_bank']} sang {result['to_bank']}"
        logger.info(f"Local: detected transfer {result['from_bank']} -> {result['to_bank']}")
        return result

    m = TRANSFER_SHORT_PATTERN.search(text)
    if m:
        result["action"] = "transfer"
        result["amount"] = parse_amount_local(m.group(1))
        b = m.group(2).upper()
        result["from_bank"] = resolve_bank(b)
        result["to_bank"] = "CASH"
        result["description"] = f"Rút từ {result['from_bank']}"
        logger.info(f"Local: detected withdrawal from {result['from_bank']}")
        return result

    # 2. Extract amount
    result["amount"] = parse_amount_local(text)

    # 3. Detect INCOME
    income_score = sum(1 for kw in ACTION_KEYWORDS["income"] if kw in text_lower)
    expense_score = sum(1 for kw in ["mua", "ăn", "đi", "trả", "đóng"] if kw in text_lower)
    if income_score > 0 and income_score >= expense_score:
        result["action"] = "income"

    # 4. Detect bank
    for bank, keywords in BANK_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                result["bank"] = bank
                break
        if result["bank"]:
            break

    # 5. Category by keyword scoring
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[cat] = score
    if scores:
        best_cat = max(scores, key=scores.get)
        if scores[best_cat] >= 1:
            result["category"] = best_cat

    # 6. Clean description: remove amount, bank words
    desc = text_original
    for pat, _ in AMOUNT_PATTERNS:
        desc = re.sub(pat, '', desc)
    for bank_keywords in BANK_KEYWORDS.values():
        for kw in bank_keywords:
            desc = re.sub(re.escape(kw), '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'\s+', ' ', desc).strip()
    if desc:
        result["description"] = desc[:80]

    logger.info(f"Local parsed: action={result['action']} amount={result['amount']} "
                f"cat={result['category']} bank={result['bank']}")
    return result
