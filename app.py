from flask import Flask, render_template, request, jsonify, send_file
from dotenv import load_dotenv
import os
import json
import io
import scraper_logic
import asyncio
import nest_asyncio # Needed because Flask's default dev server runs in an event loop

# Apply nest_asyncio to allow running asyncio code within Flask's existing event loop
nest_asyncio.apply()

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24) # For session management, if needed later

# Global state for the Playwright page to potentially reuse after login
# This is a simplified approach. For production, consider a more robust way to manage browser state.
# Current scraper_logic.py creates a new page on get_page() if page_global exists, effectively not reusing.
# For true reuse across requests, scraper_logic.get_page() would need modification.
# For this version, login will happen, then enumeration. For scrape, it might re-auth if page isn't passed correctly.
# Let's ensure the page from login is passed to enumerate. For scrape, a new login might be simpler if state is tricky.

# Store the current page in a global-like manner (be careful with concurrency in real prod)
# This is simplified. A proper app might use a session or a browser pool.
active_page_store = {"page": None, "base_url": None}


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/connect_and_enumerate', methods=['POST'])
async def connect_and_enumerate_channels_route():
    data = request.get_json()
    url = data.get('url')
    username = data.get('username')
    password = data.get('password')

    if not all([url, username, password]):
        return jsonify({"success": False, "error": "Missing URL, username, or password.", "status_updates": []}), 400

    status_updates = []
    try:
        # Ensure any previous browser instances are closed before starting a new one
        # This is a blunt way; ideally, manage context better.
        if active_page_store["page"] and not active_page_store["page"].is_closed():
             await active_page_store["page"].context.close() # Close context which closes page
        active_page_store["page"] = None
        active_page_store["base_url"] = None


        await scraper_logic.init_browser() # Initialize browser if not already
        
        login_success, login_updates, page = await scraper_logic.login_to_rocketchat(url, username, password)
        status_updates.extend(login_updates)
        active_page_store["page"] = page # Store the page for potential reuse

        if not login_success:
            # await scraper_logic.close_browser() # Close browser on failure
            return jsonify({"success": False, "error": "Login failed.", "status_updates": status_updates})

        # Store base_url from the successfully navigated page URL
        page_url_match = re.match(r"^(https://[^/]+)", page.url)
        if page_url_match:
            active_page_store["base_url"] = page_url_match.group(1)
        else:
            active_page_store["base_url"] = url # Fallback


        channels, enum_updates = await scraper_logic.enumerate_channels(page)
        status_updates.extend(enum_updates)

        if not channels:
            # await scraper_logic.close_browser() # Close browser if enumeration fails
            return jsonify({"success": False, "error": "Channel enumeration failed or no channels found.", "status_updates": status_updates})
        
        # Don't close browser here, keep page in active_page_store["page"] for scraping

        return jsonify({"success": True, "channels": channels, "status_updates": status_updates})

    except Exception as e:
        error_msg = f"An unexpected error occurred: {str(e)}"
        status_updates.append(error_msg)
        # await scraper_logic.close_browser() # Ensure browser is closed on major error
        active_page_store["page"] = None # Clear stored page
        active_page_store["base_url"] = None
        return jsonify({"success": False, "error": error_msg, "status_updates": status_updates}), 500


@app.route('/scrape', methods=['POST'])
async def scrape_channels_route():
    data = await request.get_json()
    url = data.get('url') # Original site URL
    username = data.get('username') # Credentials for re-login if needed
    password = data.get('password')
    selected_channels_info = data.get('channels') # List of {"name": "channel_name", "id": "channel_nav_id"}
    depth_option = data.get('depth')

    if not all([selected_channels_info, depth_option, url, username, password]):
        return jsonify({"success": False, "error": "Missing channels, depth option, or original credentials.", "status_updates": []}), 400

    status_updates = []
    scraped_data_all_channels = []
    
    current_page = active_page_store["page"]
    base_url = active_page_store["base_url"]

    try:
        # Check if page is still valid and logged in. If not, attempt re-login.
        # This is a basic check. A more robust check would be to try a small action that requires login.
        if not current_page or current_page.is_closed() or not base_url:
            status_updates.append("Session expired or page closed. Attempting to re-login...")
            login_success, login_updates, page = await scraper_logic.login_to_rocketchat(url, username, password)
            status_updates.extend(login_updates)
            if not login_success:
                return jsonify({"success": False, "error": "Re-login failed.", "status_updates": status_updates})
            current_page = page
            active_page_store["page"] = page # Update stored page

            page_url_match = re.match(r"^(https://[^/]+)", page.url) # Re-set base_url
            if page_url_match:
                base_url = page_url_match.group(1)
                active_page_store["base_url"] = base_url
            else: # Should not happen if login was successful and on the site
                 return jsonify({"success": False, "error": "Could not determine base URL after re-login.", "status_updates": status_updates})
        
        if not base_url: # Final check for base_url
            base_url_match = re.match(r"^(https://[^/]+)", url)
            if base_url_match: base_url = base_url_match.group(1)
            else: base_url = url # Less ideal fallback

        for channel_info in selected_channels_info:
            channel_name = channel_info["name"]
            channel_nav_id = channel_info["id"] # This should be the navigation link/ID
            
            messages, scrape_updates = await scraper_logic.scrape_channel_messages(current_page, channel_name, channel_nav_id, depth_option, base_url)
            status_updates.extend(scrape_updates)
            scraped_data_all_channels.append({
                "channel_name": channel_name,
                "messages": messages
            })

        final_json_output = {
            "site_url": url, # The original input URL
            "scraped_channels": scraped_data_all_channels,
            "scrape_timestamp": datetime.now().isoformat()
        }
        
        # Convert to JSON string then to BytesIO for sending as a file
        json_string = json.dumps(final_json_output, indent=2, ensure_ascii=False)
        bytes_io = io.BytesIO(json_string.encode('utf-8'))
        
        # Don't close browser here if user might do more scrapes, but for this flow, let's assume one scrape op per "connect"
        # await scraper_logic.close_browser()
        # active_page_store["page"] = None
        # active_page_store["base_url"] = None


        return send_file(
            bytes_io,
            mimetype='application/json',
            as_attachment=True,
            download_name=f"rocketchat_scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

    except Exception as e:
        error_msg = f"An unexpected error occurred during scraping: {str(e)}"
        status_updates.append(error_msg)
        # Consider closing browser on major error
        # await scraper_logic.close_browser()
        # active_page_store["page"] = None
        # active_page_store["base_url"] = None
        # Instead of JSON error for file download route, maybe an HTML error page or specific JSON error structure
        return jsonify({"success": False, "error": error_msg, "status_updates": status_updates}), 500

# Graceful shutdown of Playwright
import atexit
import re # Import re here as well if not already at top level from scraper_logic context

def shutdown_playwright():
    print("Flask app is shutting down. Closing Playwright browser...")
    # nest_asyncio allows running asyncio.run here even if loop is active
    try:
        # Check if an event loop is running, create one if not
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_running():
            # If loop is running (like in `flask run`), schedule close_browser
            # This can be tricky. For `flask run`, atexit might run in a separate thread
            # where the loop isn't the one Playwright used.
            # A simple way:
            async def close_task():
                await scraper_logic.close_browser()
            asyncio.ensure_future(close_task(), loop=loop) # Fire and forget
            # Or, if using nest_asyncio, this might just work:
            # asyncio.run(scraper_logic.close_browser())
        else:
            loop.run_until_complete(scraper_logic.close_browser())
            
    except Exception as e:
        print(f"Error during Playwright shutdown: {e}")

atexit.register(shutdown_playwright)


if __name__ == '__main__':
    # app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=5000)
    # The Dockerfile uses `flask run` which handles host/port via ENV vars.
    # For local execution without Docker:
    # Ensure FLASK_APP environment variable is set, e.g., `export FLASK_APP=app.py`
    # Then run `flask run --host=0.0.0.0 --port=5000`
    # Or from Python:
    port = int(os.environ.get("FLASK_RUN_PORT", 5000))
    host = os.environ.get("FLASK_RUN_HOST", "127.0.0.1" if os.getenv('FLASK_ENV') == 'development' else "0.0.0.0")
    app.run(host=host, port=port, debug=(os.getenv('FLASK_ENV') == 'development'))