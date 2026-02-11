import os
import subprocess
import multiprocessing
import time
import fcntl
import sys
from datetime import datetime
import random
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
    print(f"Starting monitor for: {url}")

    # XPath to find the live room link
    click_xpath = (
        "/html/body/div[2]/div[1]/div[4]/div[2]/div/div/div/div[2]/div[1]/div/a"
    )

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
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-gpu',
                    ]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                )
                page = context.new_page()

                # Navigate to the URL
                page.goto(url, wait_until="domcontentloaded")

                # Wait for dynamic content to load (增加到10秒)
                page.wait_for_timeout(10000)

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
                    print(f"  -> Warning: Could not create directory {account_name}: {e}")
                
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
                                print(f"  -> [DEBUG] Detected potential stream: {request.url}")

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

                                    # Wait for stream URL to be captured
                                    # We poll for a bit (e.g., 45 seconds)
                                    for _ in range(45):
                                        if captured_url:
                                            break
                                        time.sleep(20)
                                else:
                                    print(
                                        "  -> Live link element has no href attribute."
                                    )
                            else:
                                print("  -> Live link element not found.")

                        except Exception as e:
                            print(f"  -> Error during navigation/wait: {e}")

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
            
            print(f"  -> Executing download script for {filename}...")
            try:
                # Execute: ./copyStream.sh {stream url} {account_name+DateTime}
                # Block this thread until recording finishes
                print("  -> Recording started (blocking)...")
                subprocess.run(["./copyStream.sh", stream_url, filename])
                print("  -> Recording finished.")
            except Exception as e:
                print(f"  -> Error running recording script: {e}")

            # Sleep before checking again
            time.sleep(60 + random.randint(0, 10))

        elif is_live and not stream_url:
            # Live but failed to get URL
            print("  -> Live detected but stream URL not found. Retrying in 1 minute.")
            time.sleep(50 + random.randint(0, 10))
        else:
            # Not live, sleep 5 minutes
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
    status_xpath = "/html/body/div[2]/div[1]/div[4]/div[2]/div/div/div/div[2]/div[1]/div/a/div/div/span/span[1]"

    # The XPath provided for name
    name_xpath = "/html/body/div[2]/div[1]/div[4]/div[2]/div/div/div/div[2]/div[2]/div[1]/h1/span/span/span/span/span/span"

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
