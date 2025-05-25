# scraper_logic.py

import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from datetime import datetime, timedelta
import random
import re
import json
import traceback # For explicit traceback printing

# --- SELECTORS (Ensure these match your target site) ---
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
    "message_timestamp": '.message-timestamp', # Added for scraping
    "room_title_header": 'header .rcx-room-header__name',
    "scrollable_message_container": '.messages-box .wrapper', # Used for scrolling
    "loading_indicator": '.rcx-loading, .loading-animation', # Example - adjust if needed
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
        await log_update(None, "dev", "Closing browser...")
        await browser.close()
        browser = None
    if playwright_instance:
        await log_update(None, "dev", "Stopping Playwright instance...")
        await playwright_instance.stop()
        playwright_instance = None
    print("Playwright closed.")

async def get_page(queue=None):
    """Gets a new page within a new context, reusing the global browser."""
    b = await init_browser(queue)
    context = None
    page = None
    try:
        await log_update(queue, "dev", "Creating new browser context...")
        context = await b.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800},
            java_script_enabled=True, # Ensure JS is enabled
            ignore_https_errors=True, # Can sometimes help with self-signed certs
        )
        await log_update(queue, "dev", "Opening new page...")
        page = await context.new_page()
        page.set_default_timeout(45000) # Increased default timeout
        await log_update(queue, "dev", "Page created.")
        return page # Returns page, context stays with it. Page closure will close context.
    except Exception as e:
        print(f"\n!!! CRITICAL ERROR IN get_page: {str(e)}")
        traceback.print_exc()
        await log_update(queue, "error", f"Critical error during page creation: {e}")
        if page: await page.close()
        if context: await context.close()
        raise

async def perform_login(page, url, username, password, queue):
    """Handles the login process on a given page."""
    await log_update(queue, "info", f"Navigating to {url}...")
    try:
        await page.goto(url, wait_until='networkidle', timeout=60000)
    except PlaywrightError as e:
        await log_update(queue, "error", f"Navigation Error: {e}")
        raise # Re-raise to be caught by caller

    await log_update(queue, "dev", "Filling username...")
    await page.fill(SELECTORS["username_field"], username, timeout=20000)
    await page.wait_for_timeout(random.uniform(500, 1000))
    await log_update(queue, "dev", "Filling password...")
    await page.fill(SELECTORS["password_field"], password, timeout=20000)
    await page.wait_for_timeout(random.uniform(500, 1000))
    await log_update(queue, "info", "Clicking login button...")
    await page.click(SELECTORS["login_button"], timeout=20000)

    await log_update(queue, "dev", "Waiting for login outcome...")
    try:
        await page.wait_for_selector(
            f'{SELECTORS["login_success_indicator"]}, {SELECTORS["login_error_indicator"]}',
            state="visible",
            timeout=30000
        )
        error_element = await page.query_selector(SELECTORS["login_error_indicator"])
        if error_element:
            raise PlaywrightError("Login Failed: Check credentials or error indicator selector.")

        await log_update(queue, "success", "Login successful (during scrape).")
        return True
    except PlaywrightTimeoutError:
        raise PlaywrightError("Login Timed Out: Could not confirm login success or failure.")

# Modified login_and_enumerate_task - simplified as login is now separate
async def login_and_enumerate_task(url, username, password, log_queue):
    page = None
    try:
        page = await get_page(log_queue)
        await perform_login(page, url, username, password, log_queue) # Use the login helper

        await log_update(log_queue, "info", "Enumerating channels...")
        channels_data = []
        await page.wait_for_selector(SELECTORS["channel_list_container"], state="visible", timeout=20000)
        channel_elements = await page.query_selector_all(SELECTORS["channel_list_container"])

        if not channel_elements:
            await log_update(log_queue, "error", "No channel elements found.")
        else:
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
                        # Ensure we build a fully qualified URL for navigation
                        nav_id = href if href.startswith('http') else base_url + href
                        channels_data.append({"name": name, "id": nav_id}) # Use full URL as ID
                        await log_update(log_queue, "dev", f"Found channel: {name} ({nav_id})")

        if channels_data:
            await log_update(log_queue, "info", f"Found {len(channels_data)} channels.")
            await log_update(log_queue, "channels", channels_data)
        else:
            await log_update(log_queue, "warn", "Could not find any channels.")

        await log_update(log_queue, "end_stream", "Enumeration complete.")

    except (PlaywrightError, PlaywrightTimeoutError) as e:
        error_message = f"A Playwright error occurred: {str(e)}"
        print(f"!!! PLAYWRIGHT ERROR: {str(e)}"); traceback.print_exc()
        await log_update(log_queue, "error", error_message)
        await log_update(log_queue, "end_stream", "Process failed (Playwright Error).")
    except Exception as e:
        error_message = f"An unexpected error occurred: {str(e)}."
        print(f"!!! UNEXPECTED ERROR: {str(e)}"); traceback.print_exc()
        await log_update(log_queue, "error", error_message)
        await log_update(log_queue, "end_stream", "Process failed (Unexpected Error).")
    finally:
        if page: await page.context.close() # Close context/page

# --- NEW SCRAPING FUNCTION ---
async def scrape_messages_task(url, username, password, channel_url, depth, log_queue):
    page = None
    scraped_data = []
    try:
        page = await get_page(log_queue)
        await perform_login(page, url, username, password, log_queue)

        await log_update(log_queue, "info", f"Navigating to channel: {channel_url}")
        await page.goto(channel_url, wait_until='networkidle', timeout=60000)
        await page.wait_for_selector(SELECTORS["room_title_header"], timeout=30000)
        channel_name = await page.inner_text(SELECTORS["room_title_header"])
        await log_update(log_queue, "success", f"Entered channel: {channel_name.strip()}")
        await page.wait_for_timeout(2000) # Wait for messages to maybe load

        await log_update(log_queue, "info", "Starting message scraping...")
        await page.wait_for_selector(SELECTORS["scrollable_message_container"], state="visible", timeout=20000)
        scroll_container = page.locator(SELECTORS["scrollable_message_container"])

        three_months_ago = datetime.now() - timedelta(days=90)
        seen_message_ids = set()
        keep_scrolling = True
        consecutive_no_new_messages = 0

        while keep_scrolling:
            await log_update(log_queue, "dev", "Looking for messages...")
            messages_found_this_pass = 0
            message_elements = await page.query_selector_all(SELECTORS["message_item_li"])

            if not message_elements:
                 await log_update(log_queue, "warn", "No message elements found on this pass.")
                 consecutive_no_new_messages += 1
                 if consecutive_no_new_messages > 5: # Stop if nothing found 5 times
                     await log_update(log_queue, "warn", "No messages found for several scrolls. Stopping.")
                     break
                 await page.wait_for_timeout(3000) # Wait a bit longer
                 continue

            consecutive_no_new_messages = 0 # Reset if we found *any* elements

            for msg_element in reversed(message_elements): # Process oldest first in view
                msg_id = await msg_element.get_attribute('id')
                if not msg_id or msg_id in seen_message_ids:
                    continue # Skip if no ID or already seen

                seen_message_ids.add(msg_id)
                messages_found_this_pass += 1

                try:
                    sender_el = await msg_element.query_selector(SELECTORS["message_sender"])
                    text_el = await msg_element.query_selector(SELECTORS["message_text"])
                    ts_el = await msg_element.query_selector(SELECTORS["message_timestamp"])

                    sender = await sender_el.inner_text() if sender_el else "Unknown Sender"
                    text = await text_el.inner_text() if text_el else ""
                    ts_text = await ts_el.get_attribute('title') if ts_el else "" # Title often has full date

                    # --- Timestamp Parsing (Crucial & Needs Adjustment) ---
                    msg_time = None
                    if ts_text:
                        try:
                           # Try a common format, *ADJUST THIS* based on your site's HTML
                           msg_time = datetime.strptime(ts_text, '%I:%M %p, %B %d, %Y')
                        except ValueError:
                           await log_update(log_queue, "dev", f"Could not parse timestamp '{ts_text}' with default format. Storing as text.")

                    scraped_data.append({
                        "id": msg_id,
                        "sender": sender.strip(),
                        "text": text.strip(),
                        "timestamp_raw": ts_text,
                        "timestamp_dt": msg_time.isoformat() if msg_time else None
                    })

                    # --- Check Depth ---
                    if depth == "3months" and msg_time and msg_time < three_months_ago:
                        await log_update(log_queue, "info", "Reached 3-month limit. Stopping scroll.")
                        keep_scrolling = False
                        break # Exit inner loop

                except Exception as parse_err:
                    await log_update(log_queue, "warn", f"Could not parse message ID {msg_id}: {parse_err}")

            if not keep_scrolling: break # Exit outer loop if limit reached

            if messages_found_this_pass == 0 and len(message_elements) > 0:
                await log_update(log_queue, "info", "No *new* messages found, might be at the top. Stopping scroll.")
                break

            await log_update(log_queue, "dev", f"Scraped {len(scraped_data)} total messages. Scrolling up...")

            # --- Scrolling Logic ---
            try:
                await page.evaluate(f'document.querySelector("{SELECTORS["scrollable_message_container"]}").scrollTop = 0')
                await page.wait_for_timeout(random.uniform(2500, 4000)) # Wait longer for content to load

                # Check if a loading indicator appeared/disappeared (optional but good)
                try:
                    await page.wait_for_selector(SELECTORS["loading_indicator"], state='visible', timeout=1000)
                    await page.wait_for_selector(SELECTORS["loading_indicator"], state='hidden', timeout=15000)
                except PlaywrightTimeoutError:
                    await log_update(log_queue, "dev", "Loading indicator didn't appear/disappear as expected, continuing.")

                # Add a check: If scroll position doesn't change after scroll, we're likely at top
                # (More complex JS might be needed for perfect check)

            except Exception as scroll_err:
                 await log_update(log_queue, "error", f"Error during scrolling: {scroll_err}. Stopping.")
                 keep_scrolling = False

        await log_update(log_queue, "success", f"Scraping finished. Found {len(scraped_data)} messages.")
        await log_update(log_queue, "scrape_result", {"channel_name": channel_name.strip(), "messages": scraped_data})
        await log_update(log_queue, "end_stream", "Scraping complete.")

    except (PlaywrightError, PlaywrightTimeoutError) as e:
        error_message = f"A Playwright error occurred during scraping: {str(e)}"
        print(f"!!! PLAYWRIGHT ERROR: {str(e)}"); traceback.print_exc()
        await log_update(log_queue, "error", error_message)
        await log_update(log_queue, "end_stream", "Scraping failed (Playwright Error).")
    except Exception as e:
        error_message = f"An unexpected error occurred during scraping: {str(e)}."
        print(f"!!! UNEXPECTED ERROR: {str(e)}"); traceback.print_exc()
        await log_update(log_queue, "error", error_message)
        await log_update(log_queue, "end_stream", "Scraping failed (Unexpected Error).")
    finally:
        if page: await page.context.close()