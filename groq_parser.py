import json
import logging
from config import GROQ_API_KEY

logger = logging.getLogger(__name__)

_client = None
if GROQ_API_KEY:
    try:
        from groq import Groq
        _client = Groq(api_key=GROQ_API_KEY)
        logger.info("Groq client initialized")
    except ImportError:
        logger.warning("groq package not installed. Run: pip install groq")
    except Exception as e:
        logger.warning(f"Groq init error: {e}")


def parse_transaction(text: str) -> dict:
    """Parse transaction using Groq (Gemini fallback). Returns dict or None."""
    if not GROQ_API_KEY or not _client:
        return None

    prompt = f"""You are a personal finance assistant. Analyze this transaction message and return ONLY a JSON object (no markdown, no extra text).

Rules:
1. "action": one of ["expense", "income", "transfer"]. Default "expense".
2. "amount": integer. Examples: "50k" -> 50000, "2 triệu" -> 2000000.
3. "category": English short category ("food", "transport", "shopping", "bill", "health", "salary", "entertainment", "other").
4. "bank": account name ("VCB", "ACB", "HDBANK", "CASH", "MOMO", etc.). null if not mentioned.
5. "from_bank" & "to_bank": only for action="transfer". null if not mentioned.
6. "description": Vietnamese short summary.

Examples:
"+500 lương vcb" -> {{"action": "income", "amount": 500, "category": "salary", "bank": "VCB", "description": "lương"}}
"-70 xăng" -> {{"action": "expense", "amount": 70, "category": "transport", "bank": null, "description": "xăng"}}
"chuyển 2tr từ VCB sang ACB" -> {{"action": "transfer", "amount": 2000000, "from_bank": "VCB", "to_bank": "ACB", "description": "chuyển tiền"}}
"ăn cơm 50k" -> {{"action": "expense", "amount": 50000, "category": "food", "bank": null, "description": "ăn cơm"}}
"nhận lương 15tr vào VCB" -> {{"action": "income", "amount": 15000000, "category": "salary", "bank": "VCB", "description": "nhận lương"}}

Message: "{text}"
JSON:"""

    try:
        response = _client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=512,
        )
        result = response.choices[0].message.content.strip()
        if result.startswith("```json"):
            result = result[7:]
        if result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        return json.loads(result.strip())
    except Exception as e:
        print(f"Groq parser error: {e}")
        return None
