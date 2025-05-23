import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from datetime import datetime, timedelta
import random
import re
import json

# --- SELECTORS (No change from last version) ---
SELECTORS = {
    "username_field": 'input[name="emailOrUsername"]',
    "password_field": 'input[name="pass"]',
    "login_button": 'button[type="submit"].login',
    "login_success_indicator": '.rcx-sidebar',
    "login_error_indicator": '.rcx-toastbar--error, div[role="alert"]',
    "channel_list_container": '.rcx-sidebar--main .rcx-sidebar-item',
    "channel_name_in_item": '.rcx-sidebar-item__name',
    "message_list_ul": '.messages-box .wrapper ul.messages-list',
    "message_item_li": 'li.message',
    "message_sender": '.user-card-message__user-name',
    "message_text": '.message-body-wrapper .body',
    "message_timestamp": '.message-timestamp',
    "room_title_header": 'header .rcx-room-header__name',
    "scrollable_message_container": '.messages-box .wrapper',
}

playwright_instance = None
browser = None

async def log_update(queue, message_type, content):
    """Helper to put structured updates onto the queue."""
    if queue:
        try:
            queue.put_nowait({"type": message_type, "content": content})
        except asyncio.QueueFull:
            print(f"[WARN] Log queue full, message dropped: {content}")
    print(f"[{message_type.upper()}] {content}")

# --- init_browser and close_browser remain the same ---
async def init_browser(queue=None):
    global playwright_instance, browser
    if not playwright_instance:
        await log_update(queue, "info", "Starting Playwright...")
        playwright_instance = await async_playwright().start()
    if not browser or not browser.is_connected():
        await log_update(queue, "info", "Launching browser...")
        browser = await playwright_instance.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
    return browser

async def close_browser():
    global playwright_instance, browser
    if browser and browser.is_connected():
        await browser.close()
        browser = None
    if playwright_instance:
        await playwright_instance.stop()
        playwright_instance = None
    print("Playwright closed.")

async def get_page(queue=None):
    global browser
    b = await init_browser(queue)
    await log_update(queue, "dev", "Creating new browser context...")
    context = await b.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
        viewport={'width': 1280, 'height': 800},
    )
    await log_update(queue, "dev", "Opening new page...")
    page = await context.new_page()
    await page.set_default_timeout(30000) # Default timeout
    return page

async def login_and_enumerate_task(url, username, password, log_queue):
    page = None
    try:
        await init_browser(log_queue)
        page = await get_page(log_queue)

        # --- Setup Event Handlers ---
        async def handle_console(msg):
            browser_msg_type = msg.type().lower()
            log_type = "dev"
            if browser_msg_type == 'error': log_type = 'warn'
            elif browser_msg_type == 'warning': log_type = 'warn'
            await log_update(log_queue, log_type, f"Browser: [{msg.type()}] {msg.text()}")
        page.on("console", handle_console)

        async def handle_response(response):
            # Log 4xx and 5xx errors
            if response.status >= 400:
                log_level = "error" if response.status >= 500 else "warn"
                await log_update(log_queue, log_level, f"HTTP {response.status}: {response.request.method} {response.url}")
        page.on("response", handle_response)
        await log_update(log_queue, "dev", "Browser & Network logging enabled.")
        # --- End Event Handlers ---

        # --- Navigation with Error Handling ---
        await log_update(log_queue, "info", f"Navigating to {url}...")
        try:
            response = await page.goto(url, wait_until='networkidle', timeout=60000) # Increased timeout
            # Check response status explicitly (though handle_response also does)
            if response and not response.ok:
                await log_update(log_queue, "error", f"Navigation Failed: Received HTTP {response.status} for {url}")
                await log_update(log_queue, "end_stream", "Process failed (Navigation Error).")
                return
        except PlaywrightTimeoutError:
            await log_update(log_queue, "error", f"Navigation Timed Out: Page {url} took too long to load.")
            await log_update(log_queue, "end_stream", "Process failed (Navigation Timeout).")
            return
        except PlaywrightError as e: # Catch other potential Playwright errors during goto
            await log_update(log_queue, "error", f"Navigation Error: Could not load {url}. Details: {e}")
            await log_update(log_queue, "end_stream", "Process failed (Navigation Error).")
            return
        await page.wait_for_timeout(random.uniform(1000, 2000))
        # --- End Navigation ---

        # --- Filling forms (Add try/except for robustness) ---
        try:
            await log_update(log_queue, "dev", "Filling username...")
            await page.fill(SELECTORS["username_field"], username, timeout=15000)
            await page.wait_for_timeout(random.uniform(500, 1000))

            await log_update(log_queue, "dev", "Filling password...")
            await page.fill(SELECTORS["password_field"], password, timeout=15000)
            await page.wait_for_timeout(random.uniform(500, 1000))

            await log_update(log_queue, "info", "Clicking login button...")
            await page.click(SELECTORS["login_button"], timeout=15000)
            await log_update(log_queue, "dev", "Login button clicked. Waiting for outcome...")

        except PlaywrightTimeoutError as e:
            await log_update(log_queue, "error", f"Timeout Error: Could not find or fill form fields. Check selectors ({e}).")
            await log_update(log_queue, "end_stream", "Process failed (Form Error).")
            return
        # --- End Filling forms ---

        # --- Check for Login Success OR Failure (Enhanced) ---
        try:
            await log_update(log_queue, "dev", f"Waiting for success ('{SELECTORS['login_success_indicator']}') OR error ('{SELECTORS['login_error_indicator']}')")
            await page.wait_for_selector(
                f'{SELECTORS["login_success_indicator"]}, {SELECTORS["login_error_indicator"]}',
                state="visible",
                timeout=25000
            )

            error_element = await page.query_selector(SELECTORS["login_error_indicator"])
            if error_element:
                try:
                    error_text = await error_element.inner_text()
                except Exception:
                    error_text = "Login Error element found, but could not get text."
                await log_update(log_queue, "error", f"Login Failed: {error_text.strip()}. Please check your username and password.")
                await log_update(log_queue, "end_stream", "Process failed (Login Error).")
                return

            success_element = await page.query_selector(SELECTORS["login_success_indicator"])
            if success_element:
                 await log_update(log_queue, "success", "Login successful.")
            else:
                await log_update(log_queue, "error", "Login outcome unclear: Neither success nor error indicator found after wait.")
                await log_update(log_queue, "end_stream", "Process failed (Login Outcome Unclear).")
                return

        except PlaywrightTimeoutError:
             await log_update(log_queue, "error", "Login Timed Out: Page didn't show success or error after clicking login. Check credentials, selectors, or site availability.")
             await log_update(log_queue, "end_stream", "Process failed (Login Timeout).")
             return
        # --- End Login Check ---

        # --- Enumerate Channels (with added try/except) ---
        try:
            await log_update(log_queue, "info", "Enumerating channels...")
            channels_data = []
            await page.wait_for_selector(SELECTORS["channel_list_container"], state="visible", timeout=20000)
            channel_elements = await page.query_selector_all(SELECTORS["channel_list_container"])

            if not channel_elements:
                await log_update(log_queue, "error", "No channel elements found. Check selector.")
                await log_update(log_queue, "end_stream", "Enumeration failed.")
                return

            base_url_match = re.match(r"^(https://[^/]+)", page.url)
            base_url = base_url_match.group(1) if base_url_match else url

            for el in channel_elements:
                name_el = await el.query_selector(SELECTORS["channel_name_in_item"])
                if name_el:
                    name = (await name_el.inner_text()).strip()
                    href = await el.get_attribute('href')
                    if not href:
                        link_tag = await el.query_selector('a')
                        href = await link_tag.get_attribute('href') if link_tag else None

                    if name and href:
                        nav_id = base_url + href if href.startswith('/') else href
                        channels_data.append({"name": name, "id": nav_id})
                        await log_update(log_queue, "dev", f"Found channel: {name}")
                await page.wait_for_timeout(random.uniform(50, 100))

            if channels_data:
                await log_update(log_queue, "info", f"Found {len(channels_data)} channels.")
                await log_update(log_queue, "channels", channels_data)
            else:
                await log_update(log_queue, "error", "Could not find channel names or links.")

            await log_update(log_queue, "end_stream", "Connection and enumeration complete.")

        except PlaywrightTimeoutError:
            await log_update(log_queue, "error", "Timeout Error: Could not find channel list. Check selectors.")
            await log_update(log_queue, "end_stream", "Process failed (Channel Enum Timeout).")
            return
        # --- End Enumerate Channels ---

    except PlaywrightError as e: # Catch more general Playwright errors
        error_message = f"A Playwright error occurred: {str(e)}."
        await log_update(log_queue, "error", error_message)
        await log_update(log_queue, "end_stream", "Process failed.")
    
    except Exception as e: # Catch any other unexpected errors
        error_message = f"An unexpected error occurred: {str(e)}."
        
        # --- ADD THESE LINES TO PRINT THE FULL TRACEBACK TO DOCKER LOGS ---
        print(f"\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"!!! UNEXPECTED ERROR IN login_and_enumerate_task: {str(e)}")
        import traceback
        traceback.print_exc() # This prints the full stack trace
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        # --- END OF ADDED LINES ---
        
        await log_update(log_queue, "error", error_message)
        await log_update(log_queue, "end_stream", "Process failed.")
    finally:
        if page and not page.is_closed():
            await log_update(log_queue, "dev", "Closing page for this task...")
            try:
                await page.context.close()
            except Exception as e:
                await log_update(log_queue, "warn", f"Could not close page context: {e}")
