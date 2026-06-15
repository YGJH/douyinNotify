import fcntl
import multiprocessing
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from tkinter.constants import FALSE

import requests
from playwright.sync_api import sync_playwright


def send_telegram(msg: str):
    try:
        BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN_WHISPER"]
    except KeyError:
        print("❌ TELEGRAM_BOT_TOKEN_WHISPER not set")
        return

    CHAT_ID = "6166024220"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg}
    try:
        r = requests.post(url, data=payload)
        if not r.ok:
            print("❌ 發送失敗：", r.text)
    except Exception as e:
        print(f"❌ 發送失敗 (Exception): {e}")


def check_live_status(url, status_xpath, name_xpath):
    """
    Checks if the specific element at the given xpath contains '直播中'.
    If live, extracts the live room URL and navigates to it to capture stream URL.
    """
    # 注意：這裡「不能」設定 RLIMIT_AS。RLIMIT_AS 會被 fork/exec 出來的子行程
    # 繼承，而 Playwright 啟動的 Chrome（V8 pointer-compression cage / sandbox）
    # 在啟動時會保留數 TB 的虛擬位址空間，一旦受到 3GB 的虛擬記憶體上限就會
    # 立刻以 SIGTRAP 崩潰，導致 "Target page, context or browser has been closed"。
    # Python 端的記憶體洩漏已改用「進房後最多等 60 秒 + 卸載 request 監聽器 +
    # 每輪關閉瀏覽器」來控制，不再依賴 RLIMIT_AS。

    print(f"Starting monitor for: {url}")

    # XPath to find the live room link
    click_xpath = '//*[@id="user_detail_element"]/div/div[2]/div[1]/div/a'
    # //*[@id="user_detail_element"]/div/div[2]/div[1]/div/a

    while True:
        is_live = False
        account_name = "未知主播"
        stream_url = None

        try:
            with sync_playwright() as p:
                # Launch browser - 使用系统的 Chrome 而不是 chromium headless shell
                browser = p.chromium.launch(
                    channel="chrome",  # 使用系统安装的 Chrome
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-gpu",
                    ],
                )
                import time

                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                )
                page = context.new_page()

                # Navigate to the URL
                page.goto(url, wait_until="domcontentloaded")

                # Wait for dynamic content to load (增加到10秒)
                page.wait_for_timeout(10000)
                # time.sleep(100)

                # 1. Get Account Name
                name_locator = page.locator(f"xpath={name_xpath}")
                if name_locator.count() > 0:
                    account_name = name_locator.first.inner_text()
                    last_account_name = account_name
                    print(f"  -> [{url}] Account Name: '{account_name}'")
                else:
                    print(f"  -> [{url}] Could not find account name element.")

                # Create directory for this account if not exists
                try:
                    if not os.path.exists(account_name):
                        os.mkdir(account_name)
                except OSError as e:
                    print(
                        f"  -> Warning: Could not create directory {account_name}: {e}"
                    )

                # 2. Check Live Status
                status_locator = page.locator(f"xpath={status_xpath}")

                if status_locator.count() > 0:
                    text = status_locator.first.inner_text()
                    # print(f"  -> [{account_name}] Found status text: '{text}'")

                    if "直播中" in text:
                        is_live = True
                        print(f"  >>> 🔴 {account_name} 直播中! (Live Now!)")

                        # Prepare to capture stream URL
                        captured_url = []

                        def handle_request(request):
                            # Look for FLV stream URL
                            # User example: https://pull-flv-q6.douyincdn.com/stage/stream-...

                            # Debug: Print all FLV/M3U8 requests to help debugging
                            if ".flv" in request.url or ".m3u8" in request.url:
                                print(
                                    f"  -> [DEBUG] Detected potential stream: {request.url}"
                                )

                            # Relaxed condition: Just check for .flv, removed "pull-flv" requirement
                            if ".flv" in request.url:
                                # Avoid duplicates or multiple qualities if possible, just take first
                                if not captured_url:
                                    print(f"  -> Found FLV stream: {request.url}")
                                    captured_url.append(request.url)

                        # Listen on context to catch requests from any page (current or new popup)
                        context.on("request", handle_request)

                        print("  -> Attempting to enter live room...")
                        try:
                            # Instead of clicking, get the href and navigate directly
                            # This avoids interception by login popups
                            link_locator = page.locator(f"xpath={click_xpath}")
                            if link_locator.count() > 0:
                                live_room_url = link_locator.first.get_attribute("href")
                                if live_room_url:
                                    print(f"  -> Found live room URL: {live_room_url}")

                                    # Handle protocol-relative URLs if necessary
                                    if live_room_url.startswith("//"):
                                        live_room_url = "https:" + live_room_url

                                    # Navigate directly to the live room
                                    page.goto(
                                        live_room_url, wait_until="domcontentloaded"
                                    )

                                    # Wait for stream URL to be captured.
                                    # FLV 請求通常在進房後幾秒內就會發出，
                                    # 這裡最多等 60 秒（30 x 2s）。原本等到
                                    # 900 秒會讓直播間影片在背景一直播放、
                                    # request 事件不斷累積，是記憶體暴衝的主因。
                                    for _ in range(30):
                                        if captured_url:
                                            break
                                        time.sleep(2)
                                else:
                                    print(
                                        "  -> Live link element has no href attribute."
                                    )
                            else:
                                print("  -> Live link element not found.")

                        except Exception as e:
                            print(f"  -> Error during navigation/wait: {e}")

                        # 卸載 request 監聽器，避免關閉前還在累積事件物件
                        try:
                            context.remove_listener("request", handle_request)
                        except Exception:
                            pass

                        if captured_url:
                            stream_url = captured_url[0]
                        else:
                            print("  -> Failed to capture stream URL within timeout.")

                    else:
                        print(f"  -> {account_name} is not currently live.")
                else:
                    print(
                        f"  -> Status element not found for {account_name} (User likely offline)."
                    )

                browser.close()

        except Exception as e:
            print(f"  -> An error occurred for {url}: {e}")

        if is_live and stream_url:
            send_telegram(f"🔴 {account_name} 主播正在直播中！正在錄製...\n{url}")

            # Format filename: account_name + DateTime
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Sanitize account name
            safe_name = "".join(
                [c for c in account_name if c.isalnum() or c in (" ", "-", "_")]
            ).strip()
            if not safe_name:
                safe_name = "unknown_user"

            filename = f"{safe_name}_{now_str}"
            filename = os.path.join(f"{account_name}", filename)
            cnt = 0
            while os.path.exists(filename + ".mkv"):
                filename += f"_{cnt}"
                cnt += 1

            # 分段錄製的限制設定
            MAX_SIZE_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB
            MAX_DURATION_SECONDS = 1 * 60 * 60  # 1 小時

            base_filename = filename  # 沿用上方產生的基礎檔名
            part = 1
            consecutive_errors = 0  # 新增：記錄連續異常錯誤次數
            max_retries = 5  # 新增：設定最大重試次數上限

            print(f"  -> 準備執行錄製腳本，基礎檔名: {base_filename}...")
            try:
                while True:  # 利用迴圈來處理分段重啟與錯誤重試
                    current_filename = f"{base_filename}_part{part}"

                    # 確保分段檔名不會覆蓋舊檔案
                    cnt = 0
                    while os.path.exists(current_filename + ".mkv"):
                        current_filename = f"{base_filename}_part{part}_{cnt}"
                        cnt += 1

                    print(f"  -> 正在開始錄製分段: {current_filename}.mkv ...")

                    # 改用 Popen，讓程式可以在背景執行並被監控
                    process = subprocess.Popen(
                        ["./copyStream.sh", stream_url, current_filename]
                    )
                    start_time = time.time()
                    limit_reached = False

                    # 當 process 還在執行時 (poll() 為 None 代表還沒結束)
                    while process.poll() is None:
                        # 1. 檢查錄製時間
                        elapsed_time = time.time() - start_time
                        if elapsed_time >= MAX_DURATION_SECONDS:
                            print(
                                f"  -> 錄製時間達到限制 ({MAX_DURATION_SECONDS} 秒)，準備重啟錄製以釋放記憶體..."
                            )
                            limit_reached = True
                            break

                        # 2. 檢查檔案大小
                        file_path = current_filename + ".mkv"
                        if os.path.exists(file_path):
                            file_size = os.path.getsize(file_path)
                            if file_size >= MAX_SIZE_BYTES:
                                print(
                                    f"  -> 檔案大小達到限制 ({file_size / (1024**3):.2f} GB)，準備重啟錄製以釋放記憶體..."
                                )
                                limit_reached = True
                                break

                        # 每隔 5 秒檢查一次
                        time.sleep(
                            5
                        )  # 將原本的120秒隨機等待改短，確保能更快反應 FFmpeg 的崩潰

                    # 取得 FFmpeg 結束時的狀態碼
                    return_code = process.poll()

                    if limit_reached:
                        consecutive_errors = 0  # 成功錄製達標，重置錯誤計數
                        # 已經達標：發送中斷訊號給 ffmpeg
                        process.terminate()
                        try:
                            # 給它 10 秒鐘優雅地寫入影片檔尾部並關閉
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            # 如果卡死，強制獵殺
                            process.kill()
                            process.wait()

                        part += 1
                        print("  -> 已成功結束當前錄製，馬上開啟下一個分段...")
                        # 迴圈繼續，將馬上開啟 _part2, _part3...
                    else:
                        # 當 limit_reached 為 False 且跳出迴圈時，檢查是否為異常結束
                        if return_code != 0:
                            consecutive_errors += 1
                            print(
                                f"  -> ⚠️ FFmpeg 錄製異常結束 (錯誤代碼: {return_code})。連續錯誤次數: {consecutive_errors}/{max_retries}"
                            )

                            if consecutive_errors >= max_retries:
                                print(
                                    "  -> ❌ 連續錯誤次數過多，可能串流已失效，放棄當前串流，重新檢查直播狀態。"
                                )
                                break
                            else:
                                print("  -> 🔄 5秒後準備重試錄製...")
                                time.sleep(5)
                                part += 1  # 換下一個 part 檔名，保留可能錄到一半的壞檔
                        else:
                            # 自然結束：代表主播下播，或是串流正常結束
                            print("  -> 錄製自然正常結束（主播下播或串流中斷）。")
                            break

            except Exception as e:
                print(f"  -> 執行錄製腳本時發生錯誤: {e}")
            # Sleep before checking again
            import random
            import time

            time.sleep(random.randint(0, 10))

        elif is_live and not stream_url:
            import time

            # Live but failed to get URL
            print("  -> Live detected but stream URL not found. Retrying in 1 minute.")
            time.sleep(50 + random.randint(0, 10))
        else:
            # Not live, sleep 5 minutes
            import random
            import time

            time.sleep(20 * 60 + random.randint(0, 30))


def main():
    # Ensure single instance
    lock_file = open("douyin_monitor.lock", "w")
    try:
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print("❌ Another instance is already running. Exiting.")
        sys.exit(1)

    urls = []
    try:
        with open("urls.txt", "r") as f:
            # Filter out empty lines
            urls = [line.strip() for line in f.read().split("\n") if line.strip()]
    except FileNotFoundError:
        print("Error: urls.txt not found.")
        return

    print(f"Loaded URLs: {urls}")

    # The XPath provided for status
    # status_xpath = "/html/body/div[2]/div[1]/div[4]/div[2]/div/div/div/div[2]/div[1]/div/a/div/div/span/span[1]"
    status_xpath = (
        "//*[@id='user_detail_element']/div/div[2]/div[1]/div/a/div/div/span/span"
    )
    # The XPath provided for name
    # name_xpath = "/html/body/div[2]/div[1]/div[4]/div[2]/div/div/div/div[2]/div[2]/div[1]/h1/span/span/span/span/span/span"
    # name_xpath = "/html/div/div[2]/div[2]/div[1]/h1/span/span/span/span/span/span"
    name_xpath = "//*[@id='user_detail_element']/div/div[2]/div[2]/div[1]/h1/span/span/span/span/span/span"
    print("Starting Douyin Live Monitor...")
    print("Press Ctrl+C to stop.")
    print("-" * 50)

    processes = []
    for url in urls:
        p = multiprocessing.Process(
            target=check_live_status, args=(url, status_xpath, name_xpath)
        )
        processes.append(p)
        p.start()

    for p in processes:
        p.join()


if __name__ == "__main__":
    main()
