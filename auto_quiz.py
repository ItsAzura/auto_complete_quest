"""
auto_quiz.py – Tự động hoá trắc nghiệm nội bộ bằng Playwright (Python, Sync API)

Hướng dẫn:
  1. Cài đặt:  pip install playwright && python -m playwright install chromium
  2. Điền thông tin cấu hình bên dưới (URL, tài khoản, XPath, dữ liệu câu hỏi)
  3. Chạy:     python auto_quiz.py
  4. Script sẽ DỪNG sau khi trả lời xong – KHÔNG tự động submit.

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
XPATH_BTN_SUBMIT  = "/html/body/div[1]/div[3]/form/div[4]/div/div[3]/input"  # KHÔNG click
XPATH_BTN_START   = ""  # Nút Bắt đầu (để trống nếu không có)
XPATH_TIMER       = "/html/body/div[1]/div[3]/div[1]/div[2]/div/span"  # Timer đếm ngược (nếu có)

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
DELAY_BETWEEN_ACTIONS_MS = 50    # Thời gian chờ giữa các thao tác (ms)
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


def get_remaining_time_text(page) -> str | None:
    """Đọc text timer còn lại trên trang (vd: '12:34' hoặc '00:12:34')."""
    if not XPATH_TIMER:
        return None
    try:
        el = page.locator(f"xpath={XPATH_TIMER}").first
        if el.count() == 0:
            return None
        txt = el.inner_text().strip()
        return txt or None
    except Exception:
        return None


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
    """Click nút Next. Trả về True nếu thành công, False nếu không có / là nút Submit."""
    if not XPATH_BTN_NEXT:
        return False
    try:
        next_btn = page.locator(f"xpath={XPATH_BTN_NEXT}")
        if next_btn.count() == 0 or not next_btn.first.is_visible(timeout=800):
            return False

        btn_text = next_btn.first.inner_text().strip().lower()
        if any(kw in btn_text for kw in ["submit", "nộp", "hoàn thành", "kết thúc"]):
            print(f"     ⏹️  Phát hiện nút Submit – DỪNG")
            return False

        next_btn.first.click(force=True)
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

        # ── Đọc text câu hỏi ──
        q_xpath = XPATH_QUESTION_TEXT.replace("{q}", str(q_idx))
        try:
            q_el = page.locator(f"xpath={q_xpath}")
            if q_el.count() == 0:
                print(f"     ℹ️  Không tìm thấy câu hỏi – kết thúc.")
                break
            q_el = q_el.first
            try:
                q_el.scroll_into_view_if_needed()
            except Exception:
                pass
            page_question_text = q_el.inner_text().strip()
        except Exception:
            print(f"     ℹ️  Không đọc được câu hỏi – bỏ qua.")
            if not click_next_button(page):
                break
            continue

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

        # ── Đợi đáp án đầu tiên hiện ra ──
        first_opt_xpath = XPATH_OPTION_TEXT.replace("{q}", str(q_idx)).replace("{a}", "1")
        try:
            page.locator(f"xpath={first_opt_xpath}").first.wait_for(state="visible", timeout=3000)
        except Exception:
            print(f"     ❌ Đáp án chưa hiện – BỎ QUA")
            results["skipped"].append(page_question_text)
            if not click_next_button(page):
                break
            continue

        # ── Đọc tất cả đáp án 1 lần duy nhất bằng JS (nhanh hơn 3 lần gọi riêng) ──
        js_xpaths = [
            XPATH_OPTION_TEXT.replace("{q}", str(q_idx)).replace("{a}", str(i))
            for i in range(1, MAX_OPTIONS + 1)
        ]
        option_texts = page.evaluate("""(xpaths) => {
            return xpaths.map(xp => {
                const el = document.evaluate(xp, document, null, 9, null).singleNodeValue;
                return el ? el.innerText.trim() : "";
            });
        }""", js_xpaths)

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

        found = False
        if best_a_idx > 0 and best_a_score >= FUZZY_MATCH_THRESHOLD:
            if XPATH_OPTION_CLICK:
                click_xpath = XPATH_OPTION_CLICK.replace("{q}", str(q_idx)).replace("{a}", str(best_a_idx))
                click_el = page.locator(f"xpath={click_xpath}")
            else:
                click_el = page.locator(
                    f"xpath={XPATH_OPTION_TEXT.replace('{q}', str(q_idx)).replace('{a}', str(best_a_idx))}"
                )

            try:
                click_el.first.click(force=True)
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


def print_report(results: dict, remaining_time: str | None = None):
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
    if remaining_time:
        print(f"  ⏱️  Thời gian còn lại     : {remaining_time}")

    if results["skipped"]:
        print(f"  Câu bị bỏ qua           :")
        for sq in results["skipped"]:
            sq_short = sq[:70] + ("..." if len(sq) > 70 else "")
            print(f"    • {sq_short}")

    print("  ══════════════════════════════════════")
    print("  ⏳ Vui lòng kiểm tra lại và nhấn Submit khi sẵn sàng.")
    print("  🔴 Đóng trình duyệt hoặc nhấn Ctrl+C để thoát.\n")


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
            remaining_time = get_remaining_time_text(page)
            print_report(results, remaining_time=remaining_time)

            print("  💡 Trình duyệt đang mở. Nhấn Ctrl+C để thoát.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n  👋 Đang đóng trình duyệt...")

        except Exception as e:
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
