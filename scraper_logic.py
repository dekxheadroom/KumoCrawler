import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from datetime import datetime, timedelta
import random
import re
import json
import traceback # For explicit traceback printing

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

async def init_browser(queue=None):
    global playwright_instance, browser
    try:
        if not playwright_instance:
            await log_update(queue, "info", "Starting Playwright...")
            playwright_instance = await async_playwright().start()
            if not playwright_instance:
                await log_update(queue, "error", "CRITICAL: async_playwright().start() returned None.")
                raise PlaywrightError("Playwright instance is None after start(). Cannot continue.")

        if not browser or not browser.is_connected():
            await log_update(queue, "info", "Launching browser...")
            if not playwright_instance: # Should be caught above, defensive check
                 raise PlaywrightError("Playwright instance became None before launching browser.")
            browser = await playwright_instance.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
            if not browser:
                await log_update(queue, "error", "CRITICAL: playwright_instance.chromium.launch() returned None.")
                raise PlaywrightError("Browser is None after launch. Cannot continue.")
            await log_update(queue, "dev", f"Browser launched: {browser.version}")
        return browser
    except Exception as e:
        # Log the error and full traceback here, as init_browser is critical
        print(f"\n!!! CRITICAL ERROR IN init_browser: {str(e)}")
        traceback.print_exc()
        print(f"!!!\n")
        await log_update(queue, "error", f"Critical error during browser initialization: {e}")
        raise # Re-raise to be caught by login_and_enumerate_task or stop the process

async def close_browser(): # Keep your existing close_browser function
    global playwright_instance, browser
    if browser and browser.is_connected():
        await log_update(None, "dev", "Attempting to close browser...") # No queue on shutdown typically
        await browser.close()
        browser = None
        await log_update(None, "dev", "Browser closed.")
    if playwright_instance:
        await log_update(None, "dev", "Attempting to stop Playwright instance...")
        await playwright_instance.stop()
        playwright_instance = None
        await log_update(None, "dev", "Playwright instance stopped.")
    print("Playwright closed (from close_browser function).")


async def get_page(queue=None):
    global browser # browser is global
    page_obj = None # Initialize to None
    context_obj = None # Initialize to None
    try:
        b = await init_browser(queue) # init_browser now raises on failure
        # 'b' should be a valid browser object here or an exception would have been raised

        await log_update(queue, "dev", "Creating new browser context...")
        context_obj = await b.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
            viewport={'width': 1280, 'height': 800},
        )
        if not context_obj:
            await log_update(queue, "error", "CRITICAL: browser.new_context() returned None.")
            raise PlaywrightError("Browser context is None after new_context(). Cannot continue.")

        await log_update(queue, "dev", "Opening new page...")
        page_obj = await context_obj.new_page()
        await log_update(queue, "dev", f"Value of page_obj after new_page(): {type(page_obj)}")

        if page_obj: # Only proceed if page_obj is not None itself
            await log_update(queue, "dev", f"Is 'set_default_timeout' an attribute of page_obj? {hasattr(page_obj, 'set_default_timeout')}")
            if hasattr(page_obj, 'set_default_timeout'):
                method_itself = page_obj.set_default_timeout
                await log_update(queue, "dev", f"Type of page_obj.set_default_timeout: {type(method_itself)}")
                if method_itself is None:
                    await log_update(queue, "error", "CRITICAL: page_obj.set_default_timeout IS LITERALLY None!")
                try:
                    # Call it, but don't await the direct result for logging if it's None
                    # This call itself might still need to be async if the method *is* async under the hood
                    # but our previous log showed its direct result was None.
                    # The line that causes the error will be the one below.
                    coroutine_obj_or_none = page_obj.set_default_timeout(30000) # Call it
                    await log_update(queue, "dev", f"Type of result from set_default_timeout(30000): {type(coroutine_obj_or_none)}")
                    if coroutine_obj_or_none is None:
                         await log_update(queue, "error", "CRITICAL: page_obj.set_default_timeout(30000) RETURNED None directly!")
                    # If it IS a coroutine, we would await it later. If it's None, awaiting it causes the error.
                except Exception as call_exc:
                    await log_update(queue, "error", f"Error just CALLING page_obj.set_default_timeout(30000): {call_exc}")
            else:
                await log_update(queue, "error", "CRITICAL: page_obj does NOT have 'set_default_timeout' attribute!")
                await log_update(queue, "dev", f"Attributes of page_obj: {dir(page_obj)}")
        
        if not page_obj:
            await log_update(queue, "error", "CRITICAL: context.new_page() returned None.")
            # Attempt to close context if page creation fails
            if context_obj: await context_obj.close()
            raise PlaywrightError("Page object is None after new_page(). Cannot continue.")

        await log_update(queue, "dev", "Attempting: page_obj.set_default_timeout(30000) (without await)")
        page_obj.set_default_timeout(30000) # <--- REMOVED 'await'
        await log_update(queue, "dev", "Successfully called set default timeout.") # Updated log
        return page_obj
    except Exception as e:
        # Log the error and full traceback here, as get_page is critical
        print(f"\n!!! CRITICAL ERROR IN get_page: {str(e)}")
        traceback.print_exc()
        print(f"!!!\n")
        await log_update(queue, "error", f"Critical error during page creation: {e}")
        # Attempt to clean up if context or page was partially created
        if page_obj and not page_obj.is_closed(): await page_obj.close()
        elif context_obj and not context_obj.is_closed(): await context_obj.close() # if page_obj is None but context existed
        raise # Re-raise


# Your login_and_enumerate_task function (ensure the final except block has traceback.print_exc() as provided before)
async def login_and_enumerate_task(url, username, password, log_queue):
    page = None # Initialize page to None
    try:
        # init_browser is called by get_page
        page = await get_page(log_queue) # Line 76 from your traceback

        # --- Setup Event Handlers ---
        # (This section should be fine as it was, ensure 'page' is valid before this)
        async def handle_console(msg):
            browser_msg_type = msg.type.lower()
            log_type = "dev"
            if browser_msg_type == 'error': log_type = 'warn'
            elif browser_msg_type == 'warning': log_type = 'warn'
            await log_update(log_queue, log_type, f"Browser: [{msg.type.upper()}] {msg.text()}")
        page.on("console", handle_console)

        async def handle_response(response):
            if response.status >= 400:
                log_level = "error" if response.status >= 500 else "warn"
                await log_update(log_queue, log_level, f"HTTP {response.status}: {response.request.method} {response.url}")
        page.on("response", handle_response)
        await log_update(log_queue, "dev", "Browser & Network logging enabled.")
        # --- End Event Handlers ---

        # --- Navigation with Error Handling ---
        await log_update(log_queue, "info", f"Navigating to {url}...")
        # ... (rest of your navigation, form filling, login check, enumeration logic) ...
        # ... (ensure it's the version with detailed try/except blocks we developed) ...
        # For example, the navigation block:
        try:
            response = await page.goto(url, wait_until='networkidle', timeout=60000)
            if response and not response.ok:
                await log_update(log_queue, "error", f"Navigation Failed: Received HTTP {response.status} for {url}")
                await log_update(log_queue, "end_stream", "Process failed (Navigation Error).")
                return
        except PlaywrightTimeoutError:
            await log_update(log_queue, "error", f"Navigation Timed Out: Page {url} took too long to load.")
            await log_update(log_queue, "end_stream", "Process failed (Navigation Timeout).")
            return
        except PlaywrightError as e: 
            await log_update(log_queue, "error", f"Navigation Error (Playwright): Could not load {url}. Is URL correct? Details: {e}")
            await log_update(log_queue, "end_stream", "Process failed (Navigation Error).")
            return
        except Exception as e: 
            await log_update(log_queue, "error", f"Unexpected Navigation Error for {url}. Details: {e}")
            await log_update(log_queue, "end_stream", "Process failed (Navigation Error).")
            return
        await page.wait_for_timeout(random.uniform(1000, 2000))
        
        # IMPORTANT: Continue with the rest of the form filling, login check, etc.
        # This has been truncated for brevity, use your full existing logic here.
        await log_update(log_queue, "info", "Dummy step: If navigation succeeds, other actions follow.")
        # ...

        await log_update(log_queue, "end_stream", "Process nominally complete (or failed earlier).")


    except PlaywrightError as e: 
        error_message = f"A Playwright initialization or page creation error occurred: {str(e)}."
        print(f"\n!!! PLAYWRIGHT SETUP ERROR IN login_and_enumerate_task: {str(e)}")
        traceback.print_exc() # Print traceback for these critical errors
        print(f"!!!\n")
        await log_update(log_queue, "error", error_message)
        await log_update(log_queue, "end_stream", "Process failed (Playwright Setup).")
    
    except Exception as e: 
        error_message = f"An unexpected error occurred in login_and_enumerate_task: {str(e)}."
        print(f"\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"!!! UNEXPECTED ERROR IN login_and_enumerate_task: {str(e)}")
        traceback.print_exc() # This was the one you added, ensure it's here
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        await log_update(log_queue, "error", error_message)
        await log_update(log_queue, "end_stream", "Process failed.")
    finally:
        if page and not page.is_closed():
            await log_update(log_queue, "dev", "Closing page context for this task (finally block)...")
            try:
                await page.context.close()
            except Exception as e:
                await log_update(log_queue, "warn", f"Error closing page context in finally: {e}")
        else:
            await log_update(log_queue, "dev", "Page was None or already closed in finally block.")
