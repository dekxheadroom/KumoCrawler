# scraper_logic.py

import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from datetime import datetime, timedelta
import random
import re
import json
import traceback # For explicit traceback printing

# --- SELECTORS (Consolidated and Updated based on your HTML inspections) ---
SELECTORS = {
    # Login Page
    "username_field": 'input[name="usernameOrEmail"]',
    "password_field": 'input[name="password"]',
    "login_button": 'button[type="submit"]',
    "login_error_indicator": '.rcx-toastbar--error, div[role="alert"]', # Verify if login fails

    # Homepage (After Login) / Channel List
    "login_success_indicator": '.rcx-sidebar',              # Main sidebar as success
    "channel_list_container": 'a.rcx-sidebar-item',         # Each channel item in the sidebar
    "channel_name_in_item": '.rcx-sidebar-item__title',     # Name of the channel in the sidebar item

    # Channel View (Message Area)
    "room_title_header": 'h1.rcx-css-15uaxsl',
    "scrollable_message_container": '.messages-box .rc-scrollbars-view',
    "message_list_ul": 'ul.messages-list',
    "message_item_li": 'div.rcx-message[role="listitem"]',
    "message_sender": '.rcx-message-header__name[data-qa-type="username"]',
    "message_text": 'div.rcx-message-body', # Python code will need to handle children
    "message_timestamp": '.rcx-message-header__time', # Timestamp in title attribute
    "loading_indicator": '.rcx-loading, .loading-animation', # Verify if it appears on scroll
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
        # Added --no-sandbox for Docker, might need to adjust based on your Docker setup
        browser = await playwright_instance.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage']
        )
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
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36', # Updated UA
            viewport={'width': 1280, 'height': 800},
            java_script_enabled=True,
            ignore_https_errors=True,
            bypass_csp=True # Can sometimes help with strict sites
        )
        await log_update(queue, "dev", "Opening new page...")
        page = await context.new_page()
        page.set_default_timeout(45000)
        await log_update(queue, "dev", "Page created.")
        return page
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
        await log_update(queue, "error", f"Navigation Error: {e}. URL: {url}")
        raise

    await log_update(queue, "dev", f"Attempting to fill username with selector: {SELECTORS['username_field']}")
    await page.fill(SELECTORS["username_field"], username, timeout=30000) # Increased timeout
    await page.wait_for_timeout(random.uniform(500, 1000))

    await log_update(queue, "dev", f"Attempting to fill password with selector: {SELECTORS['password_field']}")
    await page.fill(SELECTORS["password_field"], password, timeout=30000) # Increased timeout
    await page.wait_for_timeout(random.uniform(500, 1000))

    await log_update(queue, "info", f"Attempting to click login button with selector: {SELECTORS['login_button']}")
    await page.click(SELECTORS["login_button"], timeout=30000) # Increased timeout

    await log_update(queue, "dev", "Waiting for login outcome...")
    try:
        # Wait for either a success or an error indicator
        await page.wait_for_selector(
            f'{SELECTORS["login_success_indicator"]}, {SELECTORS["login_error_indicator"]}',
            state="visible",
            timeout=45000 # Increased timeout for post-login page load
        )
        # Check if the error indicator is present
        error_element = await page.query_selector(SELECTORS["login_error_indicator"])
        if error_element:
            error_text_list = await error_element.all_text_contents()
            error_text = " ".join(error_text_list).strip() if error_text_list else "Login Error element found, but could not get text."
            raise PlaywrightError(f"Login Failed: {error_text}. Check credentials or error indicator selector.")
        
        # If no error, check for success indicator to be sure
        await page.wait_for_selector(SELECTORS["login_success_indicator"], state="visible", timeout=15000)
        await log_update(queue, "success", "Login successful (success indicator found).")
        return True
    except PlaywrightTimeoutError:
        raise PlaywrightError("Login Timed Out: Could not confirm login success or failure. Check login_success_indicator and login_error_indicator selectors, and page load speed after login.")

async def login_and_enumerate_task(url, username, password, log_queue):
    page = None
    try:
        page = await get_page(log_queue)
        await perform_login(page, url, username, password, log_queue)

        await log_update(log_queue, "info", "Enumerating channels...")
        channels_data = []
        # Wait for the container that holds channel items
        await page.wait_for_selector(SELECTORS["channel_list_container"], state="visible", timeout=30000)
        channel_elements = await page.query_selector_all(SELECTORS["channel_list_container"])

        if not channel_elements:
            await log_update(log_queue, "error", f"No channel elements found using selector: {SELECTORS['channel_list_container']}")
        else:
            await log_update(log_queue, "dev", f"Found {len(channel_elements)} potential channel elements.")
            base_url_match = re.match(r"^(https://[^/]+)", page.url)
            base_url = base_url_match.group(1) if base_url_match else url.rstrip('/')

            for el in channel_elements:
                name_el = await el.query_selector(SELECTORS["channel_name_in_item"])
                if name_el:
                    name = (await name_el.inner_text()).strip()
                    href = await el.get_attribute('href') # 'a.rcx-sidebar-item' means el is the 'a' tag
                    
                    if name and href:
                        nav_id = href if href.startswith('http') else base_url + (href if href.startswith('/') else '/' + href)
                        channels_data.append({"name": name, "id": nav_id})
                        await log_update(log_queue, "dev", f"Found channel: {name} ({nav_id})")
                    else:
                        await log_update(log_queue, "warn", f"Channel element found, but missing name or href. Name el: {name_el}, Href: {href}")
                else:
                    await log_update(log_queue, "warn", f"Channel name element not found in item using selector: {SELECTORS['channel_name_in_item']}")


        if channels_data:
            await log_update(log_queue, "info", f"Successfully enumerated {len(channels_data)} channels.")
            await log_update(log_queue, "channels", channels_data)
        else:
            await log_update(log_queue, "warn", "Could not find any channels. (Check selectors or ensure channels are visible)")

        await log_update(log_queue, "end_stream", "Enumeration complete.")

    except (PlaywrightError, PlaywrightTimeoutError) as e:
        error_message = f"A Playwright error occurred: {str(e)}"
        print(f"!!! PLAYWRIGHT ERROR in login_and_enumerate_task: {str(e)}"); traceback.print_exc()
        await log_update(log_queue, "error", error_message)
        await log_update(log_queue, "end_stream", "Process failed (Playwright Error).")
    except Exception as e:
        error_message = f"An unexpected error occurred in login_and_enumerate_task: {str(e)}."
        print(f"!!! UNEXPECTED ERROR in login_and_enumerate_task: {str(e)}"); traceback.print_exc()
        await log_update(log_queue, "error", error_message)
        await log_update(log_queue, "end_stream", "Process failed (Unexpected Error).")
    finally:
        if page and not page.is_closed():
            try:
                await page.context.close() # Closing context also closes the page
            except Exception as e_close:
                await log_update(log_queue, "warn", f"Error closing page context: {e_close}")

async def scrape_messages_task(url, username, password, channel_url, depth, log_queue):
    page = None
    scraped_data = []
    try:
        page = await get_page(log_queue)
        # Perform login (even if theoretically logged in from enumeration, a new context/page needs it)
        await perform_login(page, url, username, password, log_queue)

        await log_update(log_queue, "info", f"Navigating to channel: {channel_url}")
        await page.goto(channel_url, wait_until='networkidle', timeout=60000)
        
        await page.wait_for_selector(SELECTORS["room_title_header"], timeout=30000)
        channel_name_handle = await page.query_selector(SELECTORS["room_title_header"])
        channel_name = await channel_name_handle.inner_text() if channel_name_handle else "Unknown Channel"
        await log_update(log_queue, "success", f"Entered channel: {channel_name.strip()}")
        await page.wait_for_timeout(random.uniform(2000, 3000)) # Wait for messages to load

        await log_update(log_queue, "info", "Starting message scraping...")
        await page.wait_for_selector(SELECTORS["scrollable_message_container"], state="visible", timeout=30000)
        
        three_months_ago = datetime.now() - timedelta(days=90)
        seen_message_ids = set()
        keep_scrolling = True
        consecutive_no_new_messages_passes = 0
        scroll_attempts_at_top = 0

        while keep_scrolling:
            await log_update(log_queue, "dev", "Looking for messages...")
            messages_found_this_pass = 0
            # Ensure message items are loaded
            try:
                await page.wait_for_selector(SELECTORS["message_item_li"], state="attached", timeout=10000)
            except PlaywrightTimeoutError:
                await log_update(log_queue, "warn", f"No message items attached after waiting (selector: {SELECTORS['message_item_li']}). Trying to scroll.")
                # Try a scroll if no messages are initially visible or attached
                current_scroll_top = await page.evaluate(f'document.querySelector("{SELECTORS["scrollable_message_container"]}").scrollTop')
                await page.evaluate(f'document.querySelector("{SELECTORS["scrollable_message_container"]}").scrollTop = 0')
                await page.wait_for_timeout(random.uniform(3000, 5000)) # Longer wait after scroll
                new_scroll_top = await page.evaluate(f'document.querySelector("{SELECTORS["scrollable_message_container"]}").scrollTop')
                if new_scroll_top == current_scroll_top and current_scroll_top == 0: # if scroll didn't change and we are at top
                     scroll_attempts_at_top +=1
                     if scroll_attempts_at_top > 2:
                        await log_update(log_queue, "info", "Appears to be at the top and no messages. Stopping.")
                        keep_scrolling = False
                        break
                else:
                    scroll_attempts_at_top = 0 # Reset if scroll happened or not at top

            message_elements = await page.query_selector_all(SELECTORS["message_item_li"])

            if not message_elements:
                 consecutive_no_new_messages_passes += 1
                 await log_update(log_queue, "warn", f"No message elements found on pass {consecutive_no_new_messages_passes} (selector: {SELECTORS['message_item_li']}).")
                 if consecutive_no_new_messages_passes > 3: # Give up after a few tries
                     await log_update(log_queue, "warn", "No messages found for several passes. Stopping scroll for this channel.")
                     keep_scrolling = False
                 await page.wait_for_timeout(3000) # Wait a bit before retrying or scrolling
                 # Attempt to scroll to load messages if none are found
                 await page.evaluate(f'document.querySelector("{SELECTORS["scrollable_message_container"]}").scrollTop = 0')
                 await page.wait_for_timeout(random.uniform(2500, 4000))
                 continue
            
            consecutive_no_new_messages_passes = 0 # Reset if elements were found

            for msg_element in reversed(message_elements): # Process oldest visible first
                msg_id = await msg_element.get_attribute('id')
                if not msg_id or msg_id in seen_message_ids:
                    continue
                seen_message_ids.add(msg_id)
                
                try:
                    sender_el = await msg_element.query_selector(SELECTORS["message_sender"])
                    text_container_el = await msg_element.query_selector(SELECTORS["message_text"])
                    ts_el = await msg_element.query_selector(SELECTORS["message_timestamp"])

                    sender = (await sender_el.inner_text()).strip() if sender_el else "Unknown Sender"
                    
                    # Extract text: handle direct text, or look for common patterns within message_body
                    text_content = []
                    if text_container_el:
                        # Try to get direct text from children, skipping complex structures if needed
                        children_texts = await text_container_el.query_selector_all('div > *, span > *') # more specific
                        if not children_texts: # Fallback to all direct children text nodes
                            all_text = await text_container_el.all_inner_texts()
                            text_content = [t.strip() for t in all_text if t.strip()]
                        else:
                           for child in children_texts:
                                text_content.append((await child.inner_text()).strip())
                    text = " ".join(filter(None, text_content))
                    if not text and text_container_el : # If still no text, try inner_text of the body itself
                        text = (await text_container_el.inner_text()).strip()


                    ts_text_title = await ts_el.get_attribute('title') if ts_el else ""
                    
                    msg_time = None
                    if ts_text_title:
                        try: # Format like: "May 21, 2025 10:47 PM"
                           msg_time = datetime.strptime(ts_text_title, '%b %d, %Y %I:%M %p')
                        except ValueError:
                            try: # Format like: "10:00 PM, August 23, 2023"
                                msg_time = datetime.strptime(ts_text_title, '%I:%M %p, %B %d, %Y')
                            except ValueError:
                               await log_update(log_queue, "dev", f"Could not parse timestamp '{ts_text_title}' with known formats. Storing as text.")
                    
                    scraped_data.append({
                        "id": msg_id, "sender": sender, "text": text,
                        "timestamp_raw": ts_text_title, "timestamp_dt": msg_time.isoformat() if msg_time else None
                    })
                    messages_found_this_pass += 1

                    if depth == "3months" and msg_time and msg_time < three_months_ago:
                        await log_update(log_queue, "info", "Reached 3-month depth limit. Stopping scroll.")
                        keep_scrolling = False
                        break 
                except Exception as parse_err:
                    await log_update(log_queue, "warn", f"Could not parse message details for ID {msg_id or 'UNKNOWN'}: {parse_err}")

            if not keep_scrolling: break # Exit outer while loop if depth limit reached

            if messages_found_this_pass == 0 and len(message_elements) > 0:
                scroll_attempts_at_top += 1
                await log_update(log_queue, "info", f"No *new* messages found this pass, though {len(message_elements)} elements exist. Scroll attempts at top: {scroll_attempts_at_top}/3.")
                if scroll_attempts_at_top >= 3:
                    await log_update(log_queue, "info", "Likely at the top of the channel history with no new messages. Stopping scroll.")
                    break
            else:
                scroll_attempts_at_top = 0 # Reset if we found new messages

            if not keep_scrolling: break

            await log_update(log_queue, "dev", f"Scraped {len(scraped_data)} total messages. Scrolling up in {SELECTORS['scrollable_message_container']}...")
            try:
                scroll_container_handle = await page.query_selector(SELECTORS["scrollable_message_container"])
                if not scroll_container_handle:
                    await log_update(log_queue, "error", "Scrollable message container not found. Stopping scroll.")
                    break
                
                # Get current scroll height before scrolling
                # prev_scroll_height = await scroll_container_handle.evaluate('node => node.scrollHeight')
                await scroll_container_handle.evaluate('node => node.scrollTop = 0')
                await page.wait_for_timeout(random.uniform(3000, 5000)) # Wait for content to load
                
                # Optional: Check if loading indicator appeared/disappeared
                try:
                    loading_el = await page.query_selector(SELECTORS["loading_indicator"])
                    if loading_el:
                        await page.wait_for_selector(SELECTORS["loading_indicator"], state='visible', timeout=1500)
                        await page.wait_for_selector(SELECTORS["loading_indicator"], state='hidden', timeout=15000)
                except PlaywrightTimeoutError:
                    await log_update(log_queue, "dev", "Loading indicator state change not detected as expected, or no indicator.")
                
                # Check if we're stuck at the top
                # current_scroll_height = await scroll_container_handle.evaluate('node => node.scrollHeight')
                # if current_scroll_height == prev_scroll_height and await scroll_container_handle.evaluate('node => node.scrollTop') == 0:
                #     scroll_attempts_at_top +=1
                #     if scroll_attempts_at_top > 2:
                #          await log_update(log_queue, "info", "Scroll height hasn't changed and at top. Assuming end of messages.")
                #          keep_scrolling = False
                # else:
                #     scroll_attempts_at_top = 0


            except Exception as scroll_err:
                 await log_update(log_queue, "error", f"Error during scrolling: {scroll_err}. Stopping.")
                 keep_scrolling = False
        
        await log_update(log_queue, "success", f"Scraping finished for '{channel_name.strip()}'. Found {len(scraped_data)} messages.")
        await log_update(log_queue, "scrape_result", {"channel_name": channel_name.strip(), "messages": scraped_data})
        # "end_stream" for the *entire operation* is handled in app.py after all scrape tasks complete.

    except (PlaywrightError, PlaywrightTimeoutError) as e:
        error_message = f"A Playwright error occurred during scraping for {channel_url}: {str(e)}"
        print(f"!!! PLAYWRIGHT ERROR during scraping: {str(e)}"); traceback.print_exc()
        await log_update(log_queue, "error", error_message)
        # Let app.py handle end_stream for multi-channel scrapes
    except Exception as e:
        error_message = f"An unexpected error occurred during scraping for {channel_url}: {str(e)}."
        print(f"!!! UNEXPECTED ERROR during scraping: {str(e)}"); traceback.print_exc()
        await log_update(log_queue, "error", error_message)
    finally:
        if page and not page.is_closed():
            try:
                await page.context.close()
            except Exception as e_close:
                await log_update(log_queue, "warn", f"Error closing page context after scraping {channel_url}: {e_close}")