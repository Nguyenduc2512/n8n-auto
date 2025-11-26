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

MAX_RETRIES = 5


# ===== UTILS =====
def clear_and_type(element, text):
    element.click()
    element.send_keys(Keys.CONTROL + "a")
    element.send_keys(Keys.BACKSPACE)
    element.send_keys(str(text))


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
    except:
        print("⚠️ Không tìm thấy nút reload captcha")


def read_invoices():
    if '--b64' in sys.argv:
        b64 = sys.argv[sys.argv.index('--b64') + 1]
        return json.loads(base64.b64decode(b64).decode('utf-8'))
    return json.load(sys.stdin)


def fullpage_screenshot(driver, file_path):
    import base64
    driver.set_window_size(1920, 1000)
    screenshot = driver.execute_cdp_cmd("Page.captureScreenshot", {
        "fromSurface": True,
        "captureBeyondViewport": True
    })
    with open(file_path, "wb") as f:
        f.write(base64.b64decode(screenshot['data']))


def capture_captcha(driver, invoice_number):
    img_el = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'img[alt="captcha"]'))
    )
    captcha_path = OUTPUT_DIR / f"{invoice_number}_captcha.png"
    img_el.screenshot(str(captcha_path))
    return Image.open(captcha_path)


def preprocess_for_anticaptcha(pil_img):
    pil_img = pil_img.resize((pil_img.width * 3, pil_img.height * 3), Image.LANCZOS)
    pil_img = pil_img.convert("L")
    pil_img = ImageOps.autocontrast(pil_img)
    pil_img = pil_img.filter(ImageFilter.MedianFilter(size=3))
    return pil_img


def solve_captcha_anticaptcha(pil_img):
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    encoded_image = base64.b64encode(buf.getvalue()).decode("utf-8")

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
            return ""
    except:
        return ""

    for _ in range(20):
        time.sleep(2)
        try:
            res = requests.post(ANTICAPTCHA_RESULT_URL, json={
                "clientKey": ANTICAPTCHA_API_KEY,
                "taskId": task_id
            }, timeout=30)

            res.raise_for_status()
            result = res.json()

            if result.get("status") == "ready":
                text = result["solution"]["text"]
                return ''.join(c for c in text if c.isalnum()).strip().upper()

        except:
            return ""

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

        try:
            driver.find_element(By.CLASS_NAME, "ant-modal-close").click()
            time.sleep(1)
        except:
            pass

        # ======================
        # PROCESS FULL LIST
        # ======================
        for inv in invoices:
            invoice_number = str(inv.get("invoiceNumber", ""))
            amount = str(inv.get("amount", ""))
            invoice_code = str(inv.get("invoiceCode", ""))
            tax_id = str(inv.get("taxId", ""))

            print(f"➡️ Processing invoice {invoice_number}...", flush=True)

            invoice_result = {
                "invoice": invoice_number,
                "captcha": None,
                "status": "error",
                "message": None,
                "screenshot": None,
            }

            success = False
            last_error = "Unknown Error"

            # ========= RETRY LOOP =========
            for attempt in range(MAX_RETRIES):

                try:
                    # Fill form
                    clear_and_type(driver.find_element(By.ID, "shdon"), invoice_number)
                    clear_and_type(driver.find_element(By.ID, "tgtttbso"), amount)
                    clear_and_type(driver.find_element(By.ID, "khhdon"), invoice_code)
                    clear_and_type(driver.find_element(By.ID, "nbmst"), tax_id)

                    # Capture captcha
                    captcha_img = capture_captcha(driver, invoice_number)
                    clean_img = preprocess_for_anticaptcha(captcha_img)
                    captcha_text = solve_captcha_anticaptcha(clean_img)

                    if not captcha_text:
                        last_error = "AntiCaptcha không trả về captcha"
                        raise Exception(last_error)

                    print(f"🔐 Captcha solved attempt {attempt+1}: {captcha_text}")
                    invoice_result["captcha"] = captcha_text

                    captcha_input = driver.find_element(By.ID, "cvalue")
                    captcha_input.clear()
                    captcha_input.send_keys(captcha_text)

                    submit_btn = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']//span[text()='Tìm kiếm']/.."))
                    )
                    submit_btn.click()
                    time.sleep(2)

                    # ===== CAPTCHA WRONG =====
                    if is_captcha_error_popup(driver):
                        print("❌ Captcha sai → retry")
                        click_reload_captcha_button(driver)

                        try:
                            (OUTPUT_DIR / f"{invoice_number}_captcha.png").unlink(missing_ok=True)
                        except:
                            pass

                        last_error = "Captcha sai"
                        continue  # retry tiếp

                    # ===== INVOICE NOT FOUND =====
                    try:
                        no_invoice_msg = driver.find_element(By.XPATH,
                            "//p[contains(text(),'Không tồn tại hóa đơn có thông tin trùng khớp')]"
                        )
                        msg = no_invoice_msg.text.strip()

                        error_file = OUTPUT_DIR / f"{invoice_number}-{invoice_code}.error.png"
                        try:
    # chờ spinner biến mất
                            WebDriverWait(driver, 20).until_not(
                                EC.presence_of_element_located((By.CLASS_NAME, "ant-spin-dot"))
                            )
                        except:
                            print("⚠️ Loader không biến mất – fallback check...")

                        try:
                            WebDriverWait(driver, 20).until(
                                EC.presence_of_element_located(
                                    (By.XPATH, "//p[contains(text(),'Tồn tại hóa đơn')]")
                                )
                            )
                        except:
                            print("⚠️ Không tìm thấy text xác nhận, có thể vẫn OK")

                        fullpage_screenshot(driver, str(error_file))

                        invoice_result["status"] = "not_found"
                        invoice_result["message"] = msg
                        invoice_result["screenshot"] = str(error_file)

                        try:
                            (OUTPUT_DIR / f"{invoice_number}_captcha.png").unlink(missing_ok=True)
                        except:
                            pass

                        success = False
                        break

                    except:
                        pass

                    # ===== SUCCESS =====
                    out_file = OUTPUT_DIR / f"{invoice_number}-{invoice_code}.png"
                    fullpage_screenshot(driver, str(out_file))

                    invoice_result["status"] = "ok"
                    invoice_result["screenshot"] = str(out_file)
                    success = True

                    try:
                        (OUTPUT_DIR / f"{invoice_number}_captcha.png").unlink(missing_ok=True)
                    except:
                        pass

                    break  # success → thoát retry

                except Exception as e:
                    last_error = str(e)
                    print(f"❌ Error on attempt {attempt+1} for {invoice_number}: {last_error}")
                    continue  # chỉ retry, không đánh dấu lỗi ở đây

            # ====== SAU KHI THOÁT RETRY LOOP ======
            if not success:
                error_file = OUTPUT_DIR / f"{invoice_number}-{invoice_code}.error.png"

                try:
                    fullpage_screenshot(driver, str(error_file))
                except:
                    pass

                invoice_result["status"] = "error"
                invoice_result["message"] = last_error
                invoice_result["screenshot"] = str(error_file)

                try:
                    (OUTPUT_DIR / f"{invoice_number}_captcha.png").unlink(missing_ok=True)
                except:
                    pass

            results.append(invoice_result)

        print(json.dumps({"status": "done", "results": results}))

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
