import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from datetime import datetime, timedelta
import random
import re

# IMPORTANT: These selectors are EXAMPLES and LIKELY NEED ADJUSTMENT
# for your specific Rocket.Chat instance. Inspect the target site's HTML.
SELECTORS = {
    "username_field": 'input[name="emailOrUsername"]', # Common, but might be different
    "password_field": 'input[name="pass"]',           # Common, but might be different
    "login_button": 'button[type="submit"].login',     # Check if '.login' class is present or just 'button[type="submit"]'
    "login_success_indicator": '.rcx-sidebar', # An element visible after login, like the main sidebar
    "channel_list_container": '.rcx-sidebar--main .rcx-sidebar-item', # Container for each channel item
    "channel_name_in_item": '.rcx-sidebar-item__name', # Element containing the channel name text
    # For message scraping within a channel:
    "message_list_ul": '.messages-box .wrapper ul.messages-list', # The UL element containing messages
    "message_item_li": 'li.message', # Each message LI element
    "message_sender": '.user-card-message__user-name', # Sender's name
    "message_text": '.message-body-wrapper .body', # Message text content (might vary)
    "message_timestamp": '.message-timestamp', # Timestamp element (often its 'title' attribute has full date)
    "room_title_header": 'header .rcx-room-header__name', # To confirm you are in the correct channel
    "scrollable_message_container": '.messages-box .wrapper', # The element that actually scrolls
}

# Global Playwright browser instance and context
# This is a simplified approach for managing the browser instance across requests.
# In a high-concurrency production app, a more sophisticated browser pool might be needed.
playwright_instance = None
browser = None
context = None
page_global = None # To hold the currently active page

async def init_browser():
    global playwright_instance, browser, context
    if not playwright_instance:
        playwright_instance = await async_playwright().start()
    if not browser:
        # --disable-blink-features=AutomationControlled helps to make Playwright less detectable
        browser = await playwright_instance.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
    if not context:
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
            viewport={'width': 1280, 'height': 800},
            # locale='en-US' # Can also set locale
        )
        # Optional: Add stealth measures (more advanced, might require external libraries or complex JS evaluations)
        # await context.add_init_script("() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }) }")

async def close_browser():
    global playwright_instance, browser, context, page_global
    if page_global and not page_global.is_closed():
        await page_global.close()
    if context:
        await context.close()
        context = None
    if browser:
        await browser.close()
        browser = None
    if playwright_instance:
        await playwright_instance.stop()
        playwright_instance = None
    page_global = None


async def get_page():
    global context, page_global
    if not context:
        await init_browser() # Ensure browser and context are initialized

    if page_global and not page_global.is_closed():
         # If a page exists and is open, decide if it should be reused or a new one created.
         # For simplicity here, we will close the old one if it exists and create a new one
         # to ensure a fresh state for new major operations like login.
         # For scraping multiple channels, one might reuse the page after login.
        try:
            await page_global.close()
        except Exception: # Ignore errors if page already closed
            pass

    page_global = await context.new_page()
    await page_global.set_default_timeout(30000) # 30 seconds default timeout for actions
    return page_global


async def login_to_rocketchat(url, username, password):
    page = await get_page() # Get a fresh page
    status_updates = []
    try:
        status_updates.append(f"Navigating to {url}...")
        await page.goto(url, wait_until='networkidle', timeout=60000) # Increased timeout for initial load
        await page.wait_for_timeout(random.uniform(1000, 2000))

        status_updates.append("Attempting to fill username...")
        await page.fill(SELECTORS["username_field"], username)
        await page.wait_for_timeout(random.uniform(500, 1000))

        status_updates.append("Attempting to fill password...")
        await page.fill(SELECTORS["password_field"], password)
        await page.wait_for_timeout(random.uniform(500, 1000))

        status_updates.append("Clicking login button...")
        async with page.expect_navigation(wait_until='networkidle', timeout=30000):
            await page.click(SELECTORS["login_button"])
        # await page.wait_for_load_state('networkidle', timeout=30000) # Alternative wait

        status_updates.append("Verifying login success...")
        await page.wait_for_selector(SELECTORS["login_success_indicator"], timeout=30000)
        status_updates.append("Login successful.")
        return True, status_updates, page # Return page for reuse in subsequent steps within the same overall operation
    except PlaywrightTimeoutError as e:
        error_message = f"Timeout during login: {str(e)}. Check URL and selectors, or site might be slow/blocking."
        status_updates.append(error_message)
        print(error_message) # Also print to server console for debugging
        # await page.screenshot(path="debug_login_timeout.png") # For debugging
        return False, status_updates, page
    except Exception as e:
        error_message = f"An error occurred during login: {str(e)}. Check selectors or network."
        status_updates.append(error_message)
        print(error_message)
        # await page.screenshot(path="debug_login_error.png") # For debugging
        return False, status_updates, page

async def enumerate_channels(page):
    status_updates = ["Enumerating channels..."]
    channels_data = []
    try:
        await page.wait_for_selector(SELECTORS["channel_list_container"], state="visible", timeout=20000)
        channel_elements = await page.query_selector_all(SELECTORS["channel_list_container"])
        
        if not channel_elements:
            status_updates.append("No channel elements found. Check channel_list_container selector.")
            return [], status_updates

        for el in channel_elements:
            name_el = await el.query_selector(SELECTORS["channel_name_in_item"])
            if name_el:
                name = await name_el.inner_text()
                name = name.strip()
                # Attempt to get a unique href or ID for the channel for navigation
                # This is highly dependent on Rocket.Chat's specific HTML structure
                href = await el.get_attribute('href')
                if not href: # If href is not directly on the item, try to find an 'a' tag within
                    link_tag = await el.query_selector('a')
                    if link_tag:
                        href = await link_tag.get_attribute('href')

                if name and href: # We need both name and a way to navigate (href)
                    # Construct full URL if href is relative
                    if href.startswith('/'):
                        base_url_match = re.match(r"^(https://[^/]+)", page.url)
                        if base_url_match:
                            base_url = base_url_match.group(1)
                            channel_id = base_url + href # This is the nav_id
                        else: # Fallback, less reliable
                            channel_id = href 
                    else: # Assuming it's already a full URL or a fragment that can be appended
                        channel_id = href
                    
                    channels_data.append({"name": name, "id": channel_id}) # Use href as 'id' for navigation
            await page.wait_for_timeout(random.uniform(50,100)) # Small delay

        if channels_data:
            status_updates.append(f"Found {len(channels_data)} channels.")
        else:
            status_updates.append("Could not find channel names or links. Check selectors.")
        return channels_data, status_updates
    except PlaywrightTimeoutError as e:
        error_message = f"Timeout during channel enumeration: {str(e)}. Check selectors."
        status_updates.append(error_message)
        # await page.screenshot(path="debug_channel_enum_timeout.png")
        return [], status_updates
    except Exception as e:
        error_message = f"Error enumerating channels: {str(e)}."
        status_updates.append(error_message)
        # await page.screenshot(path="debug_channel_enum_error.png")
        return [], status_updates

async def scrape_channel_messages(page, channel_name, channel_nav_id, depth_option, base_url):
    messages = []
    status_updates = [f"Navigating to channel: {channel_name}..."]
    
    # Construct navigation URL. channel_nav_id might be a full URL or a relative path.
    nav_url = channel_nav_id
    if channel_nav_id.startswith('/'):
        nav_url = base_url + channel_nav_id

    try:
        await page.goto(nav_url, wait_until='networkidle', timeout=45000)
        await page.wait_for_timeout(random.uniform(2000, 4000)) # Allow channel to settle

        # Verify landed on correct channel (optional but good)
        try:
            header_title_el = await page.wait_for_selector(SELECTORS["room_title_header"], timeout=10000)
            header_title = await header_title_el.inner_text()
            if channel_name.lower() not in header_title.lower():
                status_updates.append(f"Warning: Channel title '{header_title}' does not match expected '{channel_name}'. Proceeding anyway.")
            else:
                 status_updates.append(f"Confirmed in channel '{header_title}'.")
        except Exception:
            status_updates.append(f"Could not verify channel title for {channel_name}. Check selector or page load.")


        status_updates.append(f"Starting message scraping for {channel_name} (Depth: {depth_option}). This may take time...")
        
        # Scrolling logic
        three_months_ago = datetime.now() - timedelta(days=90)
        keep_scrolling = True
        loaded_message_ids = set() # To avoid processing duplicates if any appear during scroll

        # Ensure the main message list container is visible
        await page.wait_for_selector(SELECTORS["message_list_ul"], state="visible", timeout=20000)
        scroll_container_selector = SELECTORS["scrollable_message_container"]

        # Get initial scroll height
        # For Rocket.Chat, scrolling usually happens by setting scrollTop of the scrollable container to 0
        # and letting it load older messages upwards.

        scroll_attempts = 0
        max_scroll_attempts_without_new_messages = 5 # Stop if N attempts yield no new messages

        while keep_scrolling and scroll_attempts < 1000: # Safety break for very long channels
            scroll_attempts += 1
            initial_message_count_on_page = len(await page.query_selector_all(f'{SELECTORS["message_list_ul"]} {SELECTORS["message_item_li"]}'))

            # Scroll to the top of the message container
            await page.evaluate(f'document.querySelector("{scroll_container_selector}").scrollTop = 0')
            await page.wait_for_timeout(random.uniform(2500, 4500)) # Wait for messages to load

            current_messages_on_page = await page.query_selector_all(f'{SELECTORS["message_list_ul"]} {SELECTORS["message_item_li"]}')
            
            if len(current_messages_on_page) == initial_message_count_on_page and scroll_attempts > 1:
                 max_scroll_attempts_without_new_messages -=1
                 if max_scroll_attempts_without_new_messages <= 0:
                    status_updates.append("No new messages loaded after several scroll attempts. Assuming end of history.")
                    keep_scrolling = False
                    break
            else: # Reset counter if new messages were loaded
                 max_scroll_attempts_without_new_messages = 5


            # Process messages visible now
            # Iterate in reverse (chronologically older to newer on typical UIs after scrolling up)
            # But since we are prepending, we can iterate normally.
            new_messages_found_this_scroll = 0
            for msg_el in current_messages_on_page:
                msg_id = await msg_el.get_attribute('id') # Assuming messages have unique IDs
                if not msg_id or msg_id in loaded_message_ids:
                    continue # Skip already processed or ID-less messages
                
                try:
                    sender_el = await msg_el.query_selector(SELECTORS["message_sender"])
                    text_el = await msg_el.query_selector(SELECTORS["message_text"])
                    timestamp_el = await msg_el.query_selector(SELECTORS["message_timestamp"])

                    sender = await sender_el.inner_text() if sender_el else "N/A"
                    text = await text_el.inner_text() if text_el else "" # Or inner_html() if you need markup
                    
                    timestamp_str = "N/A"
                    msg_datetime = None
                    if timestamp_el:
                        timestamp_title = await timestamp_el.get_attribute('title') # Often has parsable datetime
                        if timestamp_title:
                            timestamp_str = timestamp_title
                            try:
                                # Example: "May 23, 2025 11:50 AM" or ISO string. Adjust parsing as needed.
                                # Attempt common formats
                                for fmt in ("%b %d, %Y %I:%M %p", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
                                    try:
                                        msg_datetime = datetime.strptime(timestamp_title, fmt)
                                        break
                                    except ValueError:
                                        continue
                                if not msg_datetime: # Fallback to visible text if title parsing fails
                                    timestamp_str = await timestamp_el.inner_text()
                            except Exception:
                                timestamp_str = await timestamp_el.inner_text() # Fallback
                        else:
                            timestamp_str = await timestamp_el.inner_text()


                    if depth_option == "3months" and msg_datetime and msg_datetime < three_months_ago:
                        keep_scrolling = False # Stop scrolling for this channel
                        # Don't add this message, as it's older than 3 months
                        # And since messages are usually loaded chronologically, we can break inner loop
                        # However, if messages load out of order, we might need to continue parsing current view
                        # For simplicity, assume this message and older ones are not needed.
                        # A more robust way would be to parse all visible, then check, then decide to stop scrolling.
                        status_updates.append("Reached messages older than 3 months. Stopping for this channel.")
                        break # Break from processing messages in this batch

                    message_data = {
                        "timestamp": msg_datetime.isoformat() if msg_datetime else timestamp_str,
                        "sender": sender.strip(),
                        "text": text.strip()
                    }
                    messages.append(message_data) # Prepend to keep chronological order
                    loaded_message_ids.add(msg_id)
                    new_messages_found_this_scroll += 1

                except Exception as e_msg:
                    status_updates.append(f"Error parsing a message: {str(e_msg)}. Skipping it.")
                    continue
            
            status_updates.append(f"Scroll {scroll_attempts}: Processed {new_messages_found_this_scroll} new messages. Total: {len(messages)}")
            if not keep_scrolling: # If 3-month limit hit and broke inner loop
                break

            if depth_option == "entire_history" and new_messages_found_this_scroll == 0 and scroll_attempts > 5: # Heuristic to detect end of scroll
                status_updates.append("No new messages loaded after several scrolls. Assuming end of 'entire history'.")
                break
        
        status_updates.append(f"Finished scraping {channel_name}. Total messages: {len(messages)}.")

    except PlaywrightTimeoutError as e:
        error_message = f"Timeout scraping channel {channel_name}: {str(e)}"
        status_updates.append(error_message)
        # await page.screenshot(path=f"debug_scrape_{channel_name}_timeout.png")
    except Exception as e:
        error_message = f"Error scraping channel {channel_name}: {str(e)}"
        status_updates.append(error_message)
        # await page.screenshot(path=f"debug_scrape_{channel_name}_error.png")
    
    # Sort messages by timestamp (most recent first, if desired - depends on how they were added)
    # If prepended, they are already oldest to newest. If appended, sort.
    # Assuming timestamps are ISO strings or parsable
    try:
        messages.sort(key=lambda x: datetime.fromisoformat(x["timestamp"].replace("Z", "+00:00")) if isinstance(x["timestamp"], str) and "T" in x["timestamp"] else datetime.min, reverse=True)
    except Exception:
        status_updates.append("Note: Could not sort all messages by timestamp due to format variations.")

    return messages, status_updates