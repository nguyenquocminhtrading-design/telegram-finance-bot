import json
import google.generativeai as genai
from config import GEMINI_API_KEY

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def parse_transaction(text: str) -> dict:
    """
    Sử dụng Gemini API để phân tích tin nhắn người dùng thành JSON.
    Trả về dict nếu thành công, None nếu có lỗi hoặc không thể phân tích.
    """
    if not GEMINI_API_KEY:
        return None

    prompt = f"""
    Bạn là trợ lý tài chính cá nhân. Hãy phân tích tin nhắn giao dịch sau đây của người dùng và trả về một đối tượng JSON duy nhất (không có markdown formatting, không có text dư thừa, chỉ đúng JSON).
    
    Quy tắc phân tích:
    1. "action": Một trong ["expense", "income", "transfer"]. Mặc định là "expense" trừ khi người dùng nói rõ là nhận tiền, có lương (income) hoặc chuyển tiền (transfer).
    2. "amount": Số tiền (kiểu số nguyên). Ví dụ: "50k" -> 50000, "2 triệu" -> 2000000, "1.5tr" -> 1500000.
    3. "category": Danh mục chi tiêu (tiếng Anh ngắn gọn, ví dụ: "food", "transport", "shopping", "bill", "health", "salary", "entertainment", "other").
    4. "bank": Tên ngân hàng/ví (VD: "VCB", "ACB", "HDBANK", "CASH", "MOMO", v.v.). Nếu người dùng không nhắc đến, trả về null.
    5. "from_bank" & "to_bank": Chỉ dùng cho action="transfer". Tên tài khoản gửi đi và tài khoản nhận. Nếu không nhắc đến, trả về null.
    6. "description": Tóm tắt nội dung giao dịch thật ngắn gọn.
    
    Ví dụ 1: "trưa ăn cơm hết 50k quét vcb"
    -> {{"action": "expense", "amount": 50000, "category": "food", "bank": "VCB", "description": "ăn cơm"}}
    
    Ví dụ 2: "chuyển 2 triệu từ acb sang tiền mặt"
    -> {{"action": "transfer", "amount": 2000000, "from_bank": "ACB", "to_bank": "CASH", "description": "rút tiền mặt"}}
    
    Ví dụ 3: "nhận lương 15tr vào VCB"
    -> {{"action": "income", "amount": 15000000, "category": "salary", "bank": "VCB", "description": "nhận lương"}}
    
    Ví dụ 4: "mua cái áo shopee 250k"
    -> {{"action": "expense", "amount": 250000, "category": "shopping", "bank": null, "description": "mua áo shopee"}}
    
    Tin nhắn của người dùng: "{text}"
    JSON output:
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        # Bóc tách JSON từ response
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:-3]
        elif result_text.startswith("```"):
            result_text = result_text[3:-3]
            
        data = json.loads(result_text.strip())
        return data
    except Exception as e:
        print(f"Lỗi Gemini API: {e}")
        return None
