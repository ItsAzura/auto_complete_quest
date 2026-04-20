"""
auto_quiz.py – Tự động hoá trắc nghiệm nội bộ bằng Playwright (Python, Sync API)

Hướng dẫn:
  1. Cài đặt:  pip install playwright && python -m playwright install chromium
  2. Điền thông tin cấu hình bên dưới (URL, tài khoản, XPath, dữ liệu câu hỏi)
  3. Chạy:     python auto_quiz.py
  4. Script sẽ tự động submit khi timer còn lại đến mốc AUTO_SUBMIT_AT (nếu cấu hình).

Cách hoạt động:
  - Script dùng XPath template để quét từng câu hỏi trên trang
  - Đọc text câu hỏi → tìm trong JSON → đọc text từng đáp án → click đáp án khớp
  - Nếu có phân trang → click Next → lặp lại
"""

from playwright.sync_api import sync_playwright
import json
import sys
import time
from difflib import SequenceMatcher
import os
from dotenv import load_dotenv

# Tải các biến môi trường từ file .env
load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
# CẤU HÌNH – ĐIỀN THÔNG TIN CỦA BẠN VÀO ĐÂY
# ═══════════════════════════════════════════════════════════════════════════════

# ── Thông tin trang web & tài khoản ──────────────────────────────────────────
LOGIN_URL = "https://timhieunqdhcongdoan.nghean.gov.vn/login"
QUIZ_URL  = "https://timhieunqdhcongdoan.nghean.gov.vn/startExam"
USERNAME  = os.getenv("QUIZ_USERNAME", "")
PASSWORD  = os.getenv("QUIZ_PASSWORD", "")

# ── XPath đăng nhập ──────────────────────────────────────────────────────────
XPATH_USERNAME    = "/html/body/div/div[3]/div[2]/div[2]/form/div[1]/input"
XPATH_PASSWORD    = "/html/body/div/div[3]/div[2]/div[2]/form/div[2]/input"
XPATH_BTN_LOGIN   = "/html/body/div/div[3]/div[2]/div[2]/form/button"

# ── XPath trang kiểm tra ─────────────────────────────────────────────────────
XPATH_BTN_NEXT    = "/html/body/div[1]/div[3]/form/div[2]/a/button"
XPATH_BTN_SUBMIT  = "/html/body/div[1]/div[3]/form/div[4]/div/div[3]/input"
XPATH_BTN_START   = ""  # Nút Bắt đầu (để trống nếu không có)
XPATH_TIMER       = "/html/body/div[1]/div[3]/div[1]/div[2]/div/span"  # Timer đếm ngược (nếu có)

# ── Tự động nộp bài ──────────────────────────────────────────────────────────
# Khi timer còn lại <= mốc này thì tự động nhấn Submit.
# Định dạng: "MM:SS" (ví dụ "01:30" = còn 1 phút 30 giây) hoặc "HH:MM:SS".
# Để trống "" nếu không muốn tự động nộp.
AUTO_SUBMIT_AT = os.getenv("AUTO_SUBMIT_AT", "01:30")

# ── XPath Template cho câu hỏi & đáp án ──────────────────────────────────────
# {q} = chỉ số câu hỏi trên trang (1, 2, 3...)
# {a} = chỉ số đáp án (1, 2, 3...)
#
# VÍ DỤ: Nếu câu hỏi 1 có XPath text là:
#   /html/body/div[1]/div[3]/form/div[1]/div/div[1]/div/div[1]/span
# Và đáp án 1 là:
#   /html/body/div[1]/div[3]/form/div[1]/div/div[1]/div/div[2]/div[1]/label/div[2]
# Thì template sẽ là:
#   XPATH_QUESTION_TEXT = ".../div[{q}]/div/div[1]/span"
#   XPATH_OPTION_TEXT   = ".../div[{q}]/div/div[2]/div[{a}]/label/div[2]"

XPATH_QUESTION_TEXT = "/html/body/div[1]/div[3]/form/div[1]/div/div[{q}]/div/div[1]/span"
XPATH_OPTION_TEXT   = "/html/body/div[1]/div[3]/form/div[1]/div/div[{q}]/div/div[2]/div[{a}]/label/div[2]"
# XPath để click chọn đáp án (có thể khác XPath text nếu cần click vào label/input thay vì div text)
XPATH_OPTION_CLICK  = "/html/body/div[1]/div[3]/form/div[1]/div/div[{q}]/div/div[2]/div[{a}]/label"

MAX_QUESTIONS_PER_PAGE = 15   # Số câu hỏi tối đa trên 1 trang
MAX_OPTIONS            = 3   # Số đáp án tối đa mỗi câu

# ── Dữ liệu câu hỏi & đáp án ────────────────────────────────────────────────
# Chỉ cần 2 trường: "question" (text câu hỏi) và "answer" (text đáp án đúng)
# Script sẽ tự tìm đáp án trên trang dựa vào text.
try:
    # Ưu tiên lấy QUESTIONS_DATA từ file riêng để code gọn hơn.
    from questions_data import QUESTIONS_DATA  # type: ignore
except Exception:
    QUESTIONS_DATA = []

# ── Tuỳ chọn nâng cao ────────────────────────────────────────────────────────
DELAY_BETWEEN_ACTIONS_MS = 0     # Thời gian chờ giữa các thao tác (ms) - Giảm xuống mức thấp nhất để tối đa tốc độ
FUZZY_MATCH_THRESHOLD    = 0.70  # Ngưỡng so khớp mờ (0.0 → 1.0)
QUESTIONS_JSON_FILE      = ""    # Đường dẫn file JSON (tùy chọn, ưu tiên hơn QUESTIONS_DATA)
NAVIGATION_TIMEOUT_MS    = 30000 # Timeout điều hướng (ms)

# ═══════════════════════════════════════════════════════════════════════════════
# LOGIC CHÍNH – KHÔNG CẦN SỬA PHẦN NÀY
# ═══════════════════════════════════════════════════════════════════════════════


def normalize(text: str) -> str:
    """Chuẩn hoá text: bỏ khoảng trắng thừa, lowercase."""
    return " ".join(text.strip().split()).lower()


def fuzzy_match(text_a: str, text_b: str) -> float:
    """Trả về độ tương đồng giữa 2 chuỗi (0.0 → 1.0)."""
    return SequenceMatcher(None, normalize(text_a), normalize(text_b)).ratio()


def text_contains(haystack: str, needle: str) -> bool:
    """Kiểm tra needle có nằm trong haystack không (sau khi normalize)."""
    return normalize(needle) in normalize(haystack)


def load_questions() -> list:
    """Load dữ liệu câu hỏi từ biến hoặc file JSON."""
    data = QUESTIONS_DATA

    if QUESTIONS_JSON_FILE:
        try:
            with open(QUESTIONS_JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"📂 Đã load {len(data)} câu hỏi từ file: {QUESTIONS_JSON_FILE}")
        except FileNotFoundError:
            print(f"❌ Không tìm thấy file: {QUESTIONS_JSON_FILE}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"❌ Lỗi đọc JSON: {e}")
            sys.exit(1)

    if not data:
        print("❌ Không có dữ liệu câu hỏi! Điền QUESTIONS_DATA hoặc QUESTIONS_JSON_FILE.")
        sys.exit(1)

    return data


def build_question_index(questions: list) -> list[tuple[str, dict]]:
    """Pre-normalize tất cả câu hỏi 1 lần để tra cứu nhanh hơn."""
    return [(normalize(item.get("question", "")), item) for item in questions]


def parse_time_to_seconds(time_str: str) -> int | None:
    """Chuyển chuỗi thời gian 'MM:SS' hoặc 'HH:MM:SS' thành tổng số giây. Trả về None nếu không hợp lệ."""
    if not time_str or not time_str.strip():
        return None
    parts = time_str.strip().split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def get_remaining_time_text(page) -> str | None:
    """Đọc text timer còn lại trên trang (vd: '12:34' hoặc '00:12:34') bằng JS để tức thì và không bị nghẽn (non-blocking)."""
    if not XPATH_TIMER:
        return None
    try:
        txt = page.evaluate(f"""() => {{
            const el = document.evaluate('{XPATH_TIMER}', document, null, 9, null).singleNodeValue;
            return el ? el.innerText.trim() : null;
        }}""")
        return txt or None
    except Exception:
        return None


def do_auto_submit(page) -> bool:
    """Click nút Submit. Trả về True nếu thành công."""
    if not XPATH_BTN_SUBMIT:
        print("  ⚠️  Không có XPATH_BTN_SUBMIT – không thể tự nộp bài.")
        return False
    try:
        success = page.evaluate(f"""() => {{
            const el = document.evaluate('{XPATH_BTN_SUBMIT}', document, null, 9, null).singleNodeValue;
            if (!el) return false;
            el.click();
            return true;
        }}""")
        return bool(success)
    except Exception as e:
        print(f"  ⚠️  Lỗi khi nhấn Submit: {e}")
        return False


def find_matching_question(page_question_text: str, question_index: list[tuple[str, dict]]) -> dict | None:
    """Tìm câu hỏi khớp nhất. Luôn quét hết rồi chọn điểm cao nhất."""
    norm_page = normalize(page_question_text)
    best_match = None
    best_score = 0.0

    for norm_q, item in question_index:
        if norm_page == norm_q:
            return item
        if norm_q in norm_page or norm_page in norm_q:
            score = max(SequenceMatcher(None, norm_page, norm_q).ratio(), 0.95)
        else:
            score = SequenceMatcher(None, norm_page, norm_q).ratio()
        if score > best_score:
            best_score = score
            best_match = item

    if best_score >= FUZZY_MATCH_THRESHOLD:
        return best_match

    return None


def validate_config():
    """Kiểm tra cấu hình trước khi chạy."""
    missing = []
    if not LOGIN_URL:    missing.append("LOGIN_URL")
    if not USERNAME:     missing.append("USERNAME")
    if not PASSWORD:     missing.append("PASSWORD")
    if not XPATH_USERNAME:   missing.append("XPATH_USERNAME")
    if not XPATH_PASSWORD:   missing.append("XPATH_PASSWORD")
    if not XPATH_BTN_LOGIN:  missing.append("XPATH_BTN_LOGIN")
    if not XPATH_QUESTION_TEXT: missing.append("XPATH_QUESTION_TEXT")
    if not XPATH_OPTION_TEXT:   missing.append("XPATH_OPTION_TEXT")

    if missing:
        print("❌ Thiếu cấu hình bắt buộc:")
        for m in missing:
            print(f"   • {m}")
        sys.exit(1)


def do_login(page):
    """Bước 2 – Đăng nhập."""
    print("\n🔐 Đang đăng nhập...")

    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)

    username_el = page.locator(f"xpath={XPATH_USERNAME}")
    username_el.wait_for(state="visible", timeout=10000)
    username_el.fill(USERNAME)

    password_el = page.locator(f"xpath={XPATH_PASSWORD}")
    password_el.wait_for(state="visible", timeout=10000)
    password_el.fill(PASSWORD)

    login_btn = page.locator(f"xpath={XPATH_BTN_LOGIN}")
    login_btn.wait_for(state="visible", timeout=10000)
    login_btn.click()

    page.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
    page.wait_for_timeout(500)

    if LOGIN_URL.rstrip("/") == page.url.rstrip("/"):
        print("⚠️  URL không thay đổi – kiểm tra credentials nếu cần.")
    else:
        print(f"✅ Đăng nhập thành công! → {page.url}")


def navigate_to_quiz(page):
    """Bước 3 – Điều hướng đến trang kiểm tra."""
    if QUIZ_URL:
        print(f"\n📝 Điều hướng đến trang kiểm tra: {QUIZ_URL}")
        page.goto(QUIZ_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        page.wait_for_timeout(500)

    if XPATH_BTN_START:
        try:
            start_btn = page.locator(f"xpath={XPATH_BTN_START}")
            if start_btn.is_visible(timeout=3000):
                print("▶️  Click nút Bắt đầu...")
                start_btn.click()
                page.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
                page.wait_for_timeout(500)
        except Exception:
            pass


def click_next_button(page) -> bool:
    """Click nút Next bằng 100% JS (siêu nhanh, không bị độ trễ check DOM của Playwright). Trả về True nếu thành công."""
    if not XPATH_BTN_NEXT:
        return False
    try:
        success = page.evaluate(f"""() => {{
            const el = document.evaluate('{XPATH_BTN_NEXT}', document, null, 9, null).singleNodeValue;
            if (!el) return false;
            
            const btn_text = (el.textContent || el.innerText || "").trim().toLowerCase();
            if (btn_text.includes('submit') || btn_text.includes('nộp') || btn_text.includes('hoàn thành') || btn_text.includes('kết thúc')) {{
                return false;
            }}
            
            el.click();
            return true;
        }}""")
        
        if not success:
            print(f"     ⏹️  Phát hiện nút Submit (hoặc không thấy nút Next) – DỪNG")
            return False
            
        if DELAY_BETWEEN_ACTIONS_MS > 0:
            page.wait_for_timeout(DELAY_BETWEEN_ACTIONS_MS)
        return True
    except Exception:
        return False


def answer_all_questions(page, questions: list) -> dict:
    """
    Bước 4 – Trả lời tuần tự từng câu.

    Trang web hiển thị text tất cả câu trong DOM nhưng chỉ hiện
    đáp án của câu hiện tại. Sau khi chọn đáp án → bấm Next →
    đáp án câu kế tiếp mới xuất hiện.

    Luồng: đọc câu q_idx → chọn đáp án → Next → q_idx += 1 → lặp lại.
    """
    q_index = build_question_index(questions)
    print(f"\n📋 Bắt đầu trả lời (data có {len(questions)} câu, đề thi có thể ít hơn)...\n")

    results = {
        "total_in_data": len(questions),
        "answered": 0,
        "skipped": [],
    }
    answered_set: set = set()

    for q_idx in range(1, MAX_QUESTIONS_PER_PAGE + 1):
        print(f"\n{'─' * 50}")
        print(f"  📌 Câu {q_idx}/{MAX_QUESTIONS_PER_PAGE}")
        print(f"{'─' * 50}")

        # ── Đọc text câu hỏi bằng JS ngay lập tức ──
        q_xpath = XPATH_QUESTION_TEXT.replace("{q}", str(q_idx))
        try:
            page_question_text = page.evaluate("""async (xpath) => {
                const sleep = ms => new Promise(r => setTimeout(r, ms));
                for(let i=0; i<6; i++) { // Chờ tối đa 300ms nếu web tải chậm
                    const el = document.evaluate(xpath, document, null, 9, null).singleNodeValue;
                    if (el && (el.textContent || "").trim().length > 0) {
                        try { if (el.scrollIntoViewIfNeeded) el.scrollIntoViewIfNeeded(); } catch(e){}
                        return (el.textContent || "").trim();
                    }
                    await sleep(50);
                }
                return null;
            }""", q_xpath)
        except Exception:
            page_question_text = None

        if not page_question_text:
            print(f"     ℹ️  Không tìm thấy câu hỏi – kết thúc.")
            break

        if not page_question_text:
            if not click_next_button(page):
                break
            continue

        q_short = page_question_text[:70] + ("..." if len(page_question_text) > 70 else "")
        print(f"     {q_short}")

        # ── Tìm câu hỏi khớp trong data ──
        matched_item = find_matching_question(page_question_text, q_index)

        if not matched_item:
            print(f"     ❌ Không tìm thấy trong data – BỎ QUA")
            results["skipped"].append(page_question_text)
            if not click_next_button(page):
                break
            continue

        expected_answer = matched_item.get("answer", "").strip()
        q_key = matched_item.get("question", "")

        if q_key in answered_set:
            print(f"     ✔️  Đã trả lời trước đó – bỏ qua")
            if not click_next_button(page):
                break
            continue

        norm_answer = normalize(expected_answer)
        print(f"     🔍 Đáp án cần tìm: \"{expected_answer[:60]}{'...' if len(expected_answer) > 60 else ''}\"")

        # ── Đọc tất cả đáp án siêu nhanh bằng JS Asynchronous loop ──
        js_xpaths = [
            XPATH_OPTION_TEXT.replace("{q}", str(q_idx)).replace("{a}", str(i))
            for i in range(1, MAX_OPTIONS + 1)
        ]
        
        try:
            option_texts = page.evaluate("""async (xpaths) => {
                const sleep = ms => new Promise(r => setTimeout(r, ms));
                for(let i=0; i<10; i++) { // Thử retry tối đa 500ms
                    let texts = xpaths.map(xp => {
                        const el = document.evaluate(xp, document, null, 9, null).singleNodeValue;
                        return el ? (el.textContent || el.innerText || "").trim() : "";
                    });
                    if (texts.some(t => t.length > 0)) return texts;
                    await sleep(50);
                }
                return [];
            }""", js_xpaths)
        except Exception:
            option_texts = []
            
        if not any(option_texts):
            print(f"     ❌ Đáp án trống (web chưa trả về) – BỎ QUA")
            results["skipped"].append(page_question_text)
            if not click_next_button(page):
                break
            continue

        # ── So khớp: ưu tiên exact → contains → fuzzy, chọn score cao nhất ──
        best_a_idx = -1
        best_a_score = 0.0

        for i, option_text in enumerate(option_texts):
            if not option_text:
                continue
            a_idx = i + 1
            norm_opt = normalize(option_text)

            if norm_opt == norm_answer:
                score = 1.0
            elif norm_answer in norm_opt or norm_opt in norm_answer:
                score = 0.95
            else:
                score = SequenceMatcher(None, norm_opt, norm_answer).ratio()

            opt_short = option_text[:50] + ("..." if len(option_text) > 50 else "")
            print(f"       [{a_idx}] \"{opt_short}\" (match: {score:.0%})")

            if score > best_a_score:
                best_a_score = score
                best_a_idx = a_idx

            if best_a_score == 1.0:
                break # Tìm thấy chuẩn xác 100%, thoát vòng lặp so sánh ngay để tăng vòng đời

        found = False
        if best_a_idx > 0 and best_a_score >= FUZZY_MATCH_THRESHOLD:
            if XPATH_OPTION_CLICK:
                click_xpath = XPATH_OPTION_CLICK.replace("{q}", str(q_idx)).replace("{a}", str(best_a_idx))
            else:
                click_xpath = XPATH_OPTION_TEXT.replace("{q}", str(q_idx)).replace("{a}", str(best_a_idx))

            try:
                # Dùng thuộc tính JS click để qua mặt Playwright pipeline click -> Không có độ trễ hiển thị
                page.evaluate(f"""(xpath) => {{
                    const el = document.evaluate(xpath, document, null, 9, null).singleNodeValue;
                    if (el) el.click();
                }}""", click_xpath)
                found = True
                answered_set.add(q_key)
                print(f"     ✅ Đã chọn đáp án [{best_a_idx}] (score: {best_a_score:.0%})")
            except Exception as e:
                print(f"     ⚠️  Lỗi click: {e}")

        if not found:
            print(f"     ❌ Không khớp đáp án nào – BỎ QUA")
            results["skipped"].append(page_question_text)
        else:
            results["answered"] += 1

        # ── Bấm Next để sang câu kế tiếp (trừ câu cuối) ──
        if q_idx < MAX_QUESTIONS_PER_PAGE:
            if not click_next_button(page):
                print(f"\n  ℹ️  Không tìm thấy nút Next – kết thúc.")
                break

    return results


def print_report(results: dict):
    """Bước 5 – In báo cáo kết quả."""
    skipped_count = len(results["skipped"])
    total_on_exam = results["answered"] + skipped_count

    print("\n")
    print("  ✅ Hoàn tất tự động trả lời")
    print("  ══════════════════════════════════════")
    print(f"  Tổng câu trong data     : {results['total_in_data']}")
    print(f"  Câu hỏi xuất hiện trên đề: {total_on_exam}")
    print(f"  Đã trả lời thành công   : {results['answered']}")
    print(f"  Không có trong data/đáp án: {skipped_count}")

    if results["skipped"]:
        print(f"  Câu bị bỏ qua           :")
        for sq in results["skipped"]:
            sq_short = sq[:70] + ("..." if len(sq) > 70 else "")
            print(f"    • {sq_short}")

    print("  ══════════════════════════════════════")


def main():
    """Hàm chính."""
    print("╔══════════════════════════════════════════╗")
    print("║   AUTO QUIZ – Playwright Automation      ║")
    print("╚══════════════════════════════════════════╝\n")

    validate_config()
    questions = load_questions()
    print(f"📊 Tổng số câu hỏi: {len(questions)}")

    with sync_playwright() as pw:
        print("\n🌐 Khởi động trình duyệt...")
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="vi-VN",
        )
        page = context.new_page()
        page.set_default_timeout(15000)

        try:
            do_login(page)
            navigate_to_quiz(page)
            results = answer_all_questions(page, questions)
            print_report(results)

            print("  💡 Trình duyệt đang mở để bạn kiểm tra lại đáp án.")

            # ── Tính toán mốc auto-submit ──
            auto_submit_seconds = parse_time_to_seconds(AUTO_SUBMIT_AT)
            if auto_submit_seconds is not None:
                print(f"  ⏱️  Auto-submit được BẬT: sẽ tự nộp bài khi timer còn ≤ {AUTO_SUBMIT_AT}")
            else:
                print("  ⏳ Auto-submit TẮT. Vui lòng tự nhấn 'Submit/Nộp bài' khi sẵn sàng.")
            
            last_time = None
            is_submitted = False
            
            try:
                while True:
                    try:
                        if page.is_closed():
                            break
                        
                        current_time = get_remaining_time_text(page)
                        if current_time:
                            last_time = current_time

                            # ── Kiểm tra auto-submit ──
                            if not is_submitted and auto_submit_seconds is not None:
                                remaining_secs = parse_time_to_seconds(current_time)
                                if remaining_secs is not None and remaining_secs <= auto_submit_seconds:
                                    print(f"\n  ⏰ Timer còn {current_time} (≤ {AUTO_SUBMIT_AT}) → TỰ ĐỘNG NỘP BÀI!")
                                    if do_auto_submit(page):
                                        print("  ✅ Đã nhấn nút Submit thành công!")
                                        is_submitted = True
                                        # Chờ trang xử lý
                                        try:
                                            page.wait_for_load_state("domcontentloaded", timeout=10000)
                                        except Exception:
                                            pass
                                    else:
                                        print("  ❌ Không nhấn được nút Submit – thử lại sau 2 giây...")
                                        time.sleep(2)
                                        continue
                        else:
                            # Không thấy timer nữa
                            if not is_submitted and last_time:
                                print(f"\n  🚀 ĐÃ NỘP BÀI! Thời gian hệ thống ghi nhận lúc nộp: {last_time}")
                                is_submitted = True
                    except Exception as loop_e:
                        if "Target closed" in str(loop_e) or "Browser.close" in str(loop_e) or "Target page, context" in str(loop_e):
                            break
                        
                    time.sleep(0.5)
            except KeyboardInterrupt:
                print("\n  👋 Đang đóng trình duyệt...")

        except Exception as e:
            # Ngăn lỗi lộn xộn đỏ màn hình khi người dùng đóng trình duyệt bằng tay bằng (nút X)
            if "Target closed" in str(e) or "Browser.close" in str(e) or "Target page, context" in str(e) or "Connection closed" in str(e):
                print("\n  👋 Bạn đã đóng trình duyệt.")
            else:
                print(f"\n❌ LỖI: {e}")
                import traceback
                traceback.print_exc()
                print("\n  Trình duyệt vẫn mở để kiểm tra.")
                try:
                    input("  Nhấn Enter để đóng...")
                except (KeyboardInterrupt, EOFError):
                    pass

        finally:
            context.close()
            browser.close()
            print("  🏁 Đã đóng. Tạm biệt!")


if __name__ == "__main__":
    main()
