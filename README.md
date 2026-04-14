# Auto Quiz (Playwright Python)

Script `auto_quiz.py` tự động đăng nhập, đọc câu hỏi trên trang, dò câu tương ứng trong data (JSON/biến), rồi **click đáp án khớp**.  
Nếu câu hỏi **không có trong data** hoặc **không khớp đáp án**, script sẽ **bỏ qua và chuyển sang câu tiếp theo**.

## Yêu cầu

- Python 3.10+ (khuyến nghị)
- Windows / PowerShell

## Cài đặt

1. Cài đặt các thư viện yêu cầu từ file `requirements.txt`:
```bash
pip install -r requirements.txt
```

2. Cài đặt trình duyệt Chromium cho Playwright:
```bash
python -m playwright install chromium
```

## Cấu hình

1. **Tài khoản đăng nhập (.env)**
   - Đổi tên file `.env.example` thành `.env` (hoặc tạo file `.env`).
   - Điền tên đăng nhập và mật khẩu của bạn vào `QUIZ_USERNAME` và `QUIZ_PASSWORD` trong file `.env`.

2. Mở file `auto_quiz.py` và chỉnh các mục ở phần **CẤU HÌNH**:

- **URL website**
  - `LOGIN_URL`, `QUIZ_URL`
- **XPath**
  - `XPATH_USERNAME`, `XPATH_PASSWORD`, `XPATH_BTN_LOGIN`
  - `XPATH_QUESTION_TEXT`, `XPATH_OPTION_TEXT`, `XPATH_OPTION_CLICK`
  - `XPATH_BTN_NEXT` (nút Next phân trang)
  - `XPATH_BTN_SUBMIT` chỉ để tham khảo (**script không click Submit**)
- **Giới hạn quét**
  - `MAX_QUESTIONS_PER_PAGE`: tối đa số câu trên 1 trang
  - `MAX_OPTIONS`: số đáp án mỗi câu
- **So khớp mờ**
  - `FUZZY_MATCH_THRESHOLD` (mặc định `0.70`)

## Chuẩn bị data câu hỏi (khuyến nghị dùng JSON)

Repo có file mẫu `questions.example.json`.

1. Tạo file mới, ví dụ: `questions.json` (cùng thư mục với `auto_quiz.py`)
2. Nội dung có dạng:

```json
[
  {
    "question": "Nội dung câu hỏi (copy từ đề càng sát càng tốt)",
    "answer": "Nội dung đáp án đúng (copy đúng nội dung hiển thị)"
  }
]
```

3. Trỏ `auto_quiz.py` tới file JSON:

- Sửa biến:
  - `QUESTIONS_JSON_FILE = "questions.json"`

> Nếu `QUESTIONS_JSON_FILE` để rỗng, script sẽ dùng `QUESTIONS_DATA` (được tách riêng trong `questions_data.py`).

## Chạy

```bash
python auto_quiz.py
```

## Hành vi quan trọng

- **Không có trong data**: in log “BỎ QUA” và chuyển câu khác.
- **Không khớp đáp án trên trang**: cũng “BỎ QUA”.
- **Không tự nộp bài**: script dừng lại sau khi chọn đáp án; bạn tự kiểm tra và nhấn Submit thủ công.

## Troubleshooting nhanh

- **Không click được/không đọc được câu hỏi**: XPath có thể sai (web thay layout). Cập nhật lại `XPATH_QUESTION_TEXT`, `XPATH_OPTION_TEXT`, `XPATH_OPTION_CLICK`.
- **So khớp không ổn**: tăng/giảm `FUZZY_MATCH_THRESHOLD` (ví dụ 0.75 hoặc 0.65).
- **File JSON không load**: kiểm tra đường dẫn `QUESTIONS_JSON_FILE` và encoding UTF-8.

# auto_complete_quest
