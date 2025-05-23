from quart import Quart, render_template, request, jsonify, Response # Changed Flask to Quart
from dotenv import load_dotenv
import os
import json
import io
import scraper_logic # Keep existing import
import asyncio
from uuid import uuid4 # To generate unique task IDs
import atexit
import re

load_dotenv()

app = Quart(__name__) # Changed Flask to Quart
# app.secret_key = os.urandom(24) # Quart handles sessions differently, not strictly needed for this app's current state

tasks = {}

@app.route('/')
async def index(): # Quart routes can be async by default
    print("Serving index.html")
    return await render_template('index.html') # await render_template

async def run_login_task_wrapper(task_id, url, username, password):
    print(f"Task {task_id}: Wrapper started.")
    log_queue = tasks.get(task_id, {}).get('log_queue')
    if not log_queue:
        print(f"Error: Log queue not found for task {task_id}")
        return
    try:
        await scraper_logic.login_and_enumerate_task(url, username, password, log_queue)
    except Exception as e:
        print(f"Task {task_id}: FATAL ERROR in wrapper: {e}")
        try:
            await scraper_logic.log_update(log_queue, "error", f"Task wrapper error: {e}")
            await scraper_logic.log_update(log_queue, "end_stream", "Process failed abruptly.")
        except Exception:
            pass
    finally:
        print(f"Task {task_id}: Wrapper finished.")
        if task_id in tasks:
            tasks[task_id]['status'] = 'finished'
            print(f"Task {task_id} marked as finished.")

@app.route('/connect_and_enumerate', methods=['POST'])
async def connect_and_enumerate_channels_route():
    print("\n--- Received /connect_and_enumerate request ---")
    try:
        data = await request.get_json() # In Quart, get_json() is awaitable
        print(f"Request data: {data}")
        url = data.get('url')
        username = data.get('username')
        password = data.get('password')

        if not all([url, username, password]):
            print("Request missing data.")
            return jsonify({"success": False, "error": "Missing URL, username, or password."}), 400

        task_id = str(uuid4())
        print(f"Generated Task ID: {task_id}")
        log_queue = asyncio.Queue()
        tasks[task_id] = {
            'url': url, 'username': username, 'password': password,
            'log_queue': log_queue, 'status': 'starting'
        }
        print(f"Starting background task for {task_id}...")
        asyncio.create_task(run_login_task_wrapper(task_id, url, username, password))
        tasks[task_id]['status'] = 'running'
        print(f"Returning task ID {task_id} to client.")
        return jsonify({"success": True, "task_id": task_id})
    except Exception as e:
        print(f"!!! ERROR in /connect_and_enumerate: {e}")
        return jsonify({"success": False, "error": f"Internal server error: {e}"}), 500

@app.route('/stream/<task_id>')
async def stream_logs(task_id):
    print(f"\n--- Received /stream request for task ID: {task_id} ---")
    if task_id not in tasks:
        print(f"Task ID {task_id} not found for streaming.")
        return Response("Task ID not found.", status=404, mimetype='text/plain')

    log_queue = tasks[task_id]['log_queue']
    print(f"Task {task_id}: Starting SSE stream.")

    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'info', 'content': 'Log stream connected.'})}\n\n"
            print(f"Task {task_id}: Yielded 'connected' message.")
            while True:
                log_entry = await log_queue.get()
                print(f"Task {task_id}: Got log from queue: {log_entry}")
                log_queue.task_done()
                yield f"data: {json.dumps(log_entry)}\n\n"
                print(f"Task {task_id}: Yielded log entry.")
                if log_entry.get("type") == "end_stream":
                    print(f"Task {task_id}: End stream received.")
                    break
        except asyncio.CancelledError:
            print(f"Stream for task {task_id} cancelled by client.")
        except Exception as e:
            print(f"!!! ERROR in stream for {task_id}: {e}")
            try:
                yield f"data: {json.dumps({'type': 'error', 'content': f'Streaming error: {e}'})}\n\n"
            except Exception: pass # Avoid error in error reporting
        finally:
            print(f"Closing stream for task {task_id}.")
            tasks.pop(task_id, None)
    
    # Quart handles async generators in Response naturally
    response = Response(event_generator(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no' # Useful for proxies like Nginx
    return response

# --- /scrape route would also need similar Quart updates ---
@app.route('/scrape', methods=['POST'])
async def scrape_channels_route():
    print("--- Received /scrape request (NEEDS UPDATE for Quart) ---")
    return jsonify({"success": False, "error": "Scraping function not fully updated for Quart."}), 501

# --- Shutdown logic for Playwright ---
def shutdown_playwright_sync():
    print("App is shutting down. Closing Playwright browser...")
    try:
        # asyncio.run() can cause issues if an event loop is already running or expected by Quart on shutdown
        # A simpler approach if Quart manages the main loop:
        # Create a new loop just for this shutdown task if needed,
        # but often playwright.stop() can be called directly if it handles its own cleanup.
        # For now, let's try direct, if issues arise, more complex loop handling might be needed.
        # loop = asyncio.new_event_loop()
        # loop.run_until_complete(scraper_logic.close_browser())
        # loop.close()
        # The above is tricky. Let's revert to a simpler asyncio.run with caution or make close_browser sync.
        # Given that close_browser is async:
        asyncio.run(scraper_logic.close_browser())
    except RuntimeError as e:
        print(f"RuntimeError during Playwright shutdown (may be okay if loop is managed by Quart): {e}")
    except Exception as e:
        print(f"Error during Playwright shutdown: {e}")

atexit.register(shutdown_playwright_sync)

if __name__ == '__main__':
    # Uvicorn will be started via CMD in Dockerfile, not by app.run()
    # For local development without Docker, you'd run:
    # uvicorn app:app --reload
    print("To run locally without Docker: uvicorn app:app --host 0.0.0.0 --port 5000 --reload")
    # app.run(host="0.0.0.0", port=5000, debug=True) # This is Flask's run, Quart uses uvicorn