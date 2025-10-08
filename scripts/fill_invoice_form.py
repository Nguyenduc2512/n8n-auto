import sys, json, time, base64, io, requests
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image, ImageOps, ImageFilter
from selenium.webdriver.common.keys import Keys


# ===== CONFIG =====
CHROME_BIN = "/usr/bin/chromium-browser"
CHROMEDRIVER_PATH = "/usr/lib/chromium/chromedriver"
OUTPUT_DIR = Path("/data/outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Anti-Captcha API
ANTICAPTCHA_API_KEY = "2b4c2dd644eae9861b5c77c662bbc8ff"
ANTICAPTCHA_CREATE_URL = "https://api.anti-captcha.com/createTask"
ANTICAPTCHA_RESULT_URL = "https://api.anti-captcha.com/getTaskResult"

def clear_and_type(element, text):
    element.click()
    element.send_keys(Keys.CONTROL + "a")
    element.send_keys(Keys.BACKSPACE)
    element.send_keys(str(text))
    
# ===== UTILS =====
MAX_RETRIES = 3

def is_captcha_error_popup(driver):
    try:
        popup = driver.find_element(By.CLASS_NAME, "ant-notification-notice-message")
        return "captcha không đúng" in popup.text.lower()
    except:
        return False

def click_reload_captcha_button(driver):
    try:
        reload_btn = driver.find_element(By.CSS_SELECTOR, "button.ant-btn-icon-only")
        reload_btn.click()
        print("🔁 Reload captcha clicked")
    except Exception as e:
        print(f"⚠️ Không tìm thấy nút reload captcha: {e}")

def delete_captcha_image(invoice_number):
    try:
        path = OUTPUT_DIR / f"{invoice_number}_captcha.png"
        path.unlink(missing_ok=True)
        print(f"🗑️ Đã xóa captcha cũ: {path}")
    except Exception as e:
        print(f"⚠️ Không thể xóa ảnh captcha: {e}", file=sys.stderr)

def read_invoices():
    """Đọc JSON từ stdin (n8n gửi vào)."""
    if '--b64' in sys.argv:
        b64 = sys.argv[sys.argv.index('--b64') + 1]
        invoices = json.loads(base64.b64decode(b64).decode('utf-8'))
    else:
        invoices = json.load(sys.stdin)

    return invoices

def fullpage_screenshot(driver, file_path):
    import base64
    total_height = driver.execute_script("return document.body.scrollHeight")
    driver.set_window_size(1920, 1000)
    screenshot = driver.execute_cdp_cmd("Page.captureScreenshot", {
        "fromSurface": True,
        "captureBeyondViewport": True
    })
    with open(file_path, "wb") as f:
        f.write(base64.b64decode(screenshot['data']))

def capture_captcha(driver, invoice_number):
    img_el = WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'img[alt="captcha"]'))
    )
    captcha_path = OUTPUT_DIR / f"{invoice_number}_captcha.png"
    img_el.screenshot(str(captcha_path))
    return Image.open(captcha_path)

def preprocess_for_anticaptcha(pil_img):
    """Resize & enhance image before sending to AntiCaptcha"""
    pil_img = pil_img.resize((pil_img.width*3, pil_img.height*3), Image.LANCZOS)
    pil_img = pil_img.convert("L")
    pil_img = ImageOps.autocontrast(pil_img)
    pil_img = pil_img.filter(ImageFilter.MedianFilter(size=3))
    return pil_img


def solve_captcha_anticaptcha(pil_img):
    """Gửi ảnh tới AntiCaptcha và trả về văn bản."""
    # Convert image to base64
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    encoded_image = base64.b64encode(buf.getvalue()).decode("utf-8")

    # Step 1: Create task
    create_payload = {
        "clientKey": ANTICAPTCHA_API_KEY,
        "task": {
            "type": "ImageToTextTask",
            "body": encoded_image
        }
    }

    try:
        r = requests.post(ANTICAPTCHA_CREATE_URL, json=create_payload, timeout=30)
        r.raise_for_status()
        task_id = r.json().get("taskId")
        if not task_id:
            print("❌ Không tạo được task AntiCaptcha:", r.json(), file=sys.stderr)
            return ""
    except Exception as e:
        print("❌ Lỗi khi tạo task AntiCaptcha:", e, file=sys.stderr)
        return ""

    # Step 2: Poll result
    for _ in range(20):
        time.sleep(2)
        result_payload = {
            "clientKey": ANTICAPTCHA_API_KEY,
            "taskId": task_id
        }
        try:
            res = requests.post(ANTICAPTCHA_RESULT_URL, json=result_payload, timeout=30)
            res.raise_for_status()
            result = res.json()
            if result.get("status") == "ready":
                text = result["solution"]["text"]
                return ''.join(c for c in text if c.isalnum()).strip().upper()
        except Exception as e:
            print("❌ Lỗi khi lấy kết quả AntiCaptcha:", e, file=sys.stderr)
            return ""
    print("❌ Hết thời gian chờ AntiCaptcha", file=sys.stderr)
    return ""

# ===== MAIN =====
def main():
    invoices = read_invoices()
    if not invoices:
        print(json.dumps({"status": "error", "message": "No invoices provided"}))
        return

    options = Options()
    options.binary_location = CHROME_BIN
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)

    results = []

    try:
        driver.get("https://hoadondientu.gdt.gov.vn")
        time.sleep(2)

        # Close popup nếu có
        try:
            close_btn = driver.find_element(By.CLASS_NAME, "ant-modal-close")
            close_btn.click()
            time.sleep(1)
        except:
            pass

        for inv in invoices:
            invoice_number = str(inv.get("invoiceNumber", ""))
            amount = str(inv.get("amount", ""))
            invoice_code = str(inv.get("invoiceCode", ""))
            tax_id = str(inv.get("taxId", ""))

            print(f"➡️ Processing invoice {invoice_number}...", flush=True)

            try:

                # Điền lại form
                clear_and_type(driver.find_element(By.ID, "shdon"), invoice_number)
                clear_and_type(driver.find_element(By.ID, "tgtttbso"), amount)
                clear_and_type(driver.find_element(By.ID, "khhdon"), invoice_code)
                clear_and_type(driver.find_element(By.ID, "nbmst"), tax_id)

                captcha_img = capture_captcha(driver, invoice_number)
                captcha_path = OUTPUT_DIR / f"{invoice_number}_captcha.png"
                captcha_img.save(captcha_path)

                clean_img = preprocess_for_anticaptcha(captcha_img)
                captcha_text = solve_captcha_anticaptcha(clean_img)

                print("🔐 Captcha solved:", captcha_text)

                captcha_input = driver.find_element(By.ID, "cvalue")
                captcha_input.clear()
                captcha_input.send_keys(captcha_text)

                submit_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']//span[text()='Tìm kiếm']/.."))
                )
                submit_btn.click()
                time.sleep(2)

                try:
                    captcha_path.unlink(missing_ok=True)
                except Exception as e:
                    print(f"⚠️ Không thể xoá captcha {captcha_path}: {e}", file=sys.stderr)

                # === KIỂM TRA THÔNG BÁO KHÔNG TỒN TẠI ===
                try:
                    no_invoice_msg = driver.find_element(By.XPATH, "//p[contains(text(),'Không tồn tại hóa đơn có thông tin trùng khớp')]")
                    if no_invoice_msg:
                        message = no_invoice_msg.text.strip()
                        print(json.dumps({
                            "status": "error",
                            "message": message,
                            "results": []
                        }))
                        return  # ❌ DỪNG TOÀN BỘ CHƯƠNG TRÌNH
                except:
                    pass
                out_file = OUTPUT_DIR / f"{invoice_number}-{invoice_code}.png"
                fullpage_screenshot(driver, str(out_file))

                results.append({
                    "invoice": invoice_number,
                    "captcha": captcha_text,
                    "screenshot": str(out_file),
                    "status": "ok"
                })
            except Exception as e:
                print(f"❌ Error on invoice {invoice_number}:", e, file=sys.stderr)
                results.append({
                    "invoice": invoice_number,
                    "captcha": None,
                    "status": "error",
                    "message": str(e)
                })

        print(json.dumps({"status": "done", "results": results}))
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
