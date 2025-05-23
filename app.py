from flask import Flask, render_template, request, jsonify, Response, send_file
from dotenv import load_dotenv
import os
import json
import io
import scraper_logic # Keep existing import
import asyncio
from uuid import uuid4 # To generate unique task IDs
import atexit
import re # Make sure re is imported

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Global dictionary to store task status and log queues
tasks = {}

@app.route('/')
def index():
    print("Serving index.html")
    return render_template('index.html')

async def run_login_task_wrapper(task_id, url, username, password):
    """Wrapper to run the task and handle its completion."""
    print(f"Task {task_id}: Wrapper started.")
    log_queue = tasks.get(task_id, {}).get('log_queue')
    if not log_queue:
        print(f"Error: Log queue not found for task {task_id}")
        return

    try:
        # --- ENSURE THIS CALLS THE CORRECT FUNCTION ---
        await scraper_logic.login_and_enumerate_task(url, username, password, log_queue)
    except Exception as e:
        print(f"Task {task_id}: FATAL ERROR in wrapper: {e}")
        try:
            await scraper_logic.log_update(log_queue, "error", f"Task wrapper error: {e}")
            await scraper_logic.log_update(log_queue, "end_stream", "Process failed abruptly.")
        except Exception:
            pass # Avoid errors during error logging
    finally:
        print(f"Task {task_id}: Wrapper finished.")
        if task_id in tasks:
            tasks[task_id]['status'] = 'finished'
            print(f"Task {task_id} marked as finished.")

@app.route('/connect_and_enumerate', methods=['POST'])
async def connect_and_enumerate_channels_route():
    print("\n--- Received /connect_and_enumerate request ---")
    try:
        data = request.get_json() # REMOVED await here
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
            'url': url,
            'username': username,
            'password': password,
            'log_queue': log_queue,
            'status': 'starting'
        }

        print(f"Starting background task for {task_id}...")
        asyncio.create_task(run_login_task_wrapper(task_id, url, username, password))
        tasks[task_id]['status'] = 'running'

        print(f"Returning task ID {task_id} to client.")
        return jsonify({"success": True, "task_id": task_id})
    except Exception as e:
        print(f"!!! ERROR in /connect_and_enumerate: {e}")
        # Make sure to return JSON here so JS doesn't get SyntaxError
        return jsonify({"success": False, "error": f"Internal server error: {e}"}), 500


@app.route('/stream/<task_id>')
async def stream_logs(task_id):
    print(f"\n--- Received /stream request for task ID: {task_id} ---")
    if task_id not in tasks:
        print(f"Task ID {task_id} not found for streaming.")
        return Response("Task ID not found.", status=404)

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
            yield f"data: {json.dumps({'type': 'error', 'content': f'Streaming error: {e}'})}\n\n"
        finally:
            print(f"Closing stream for task {task_id}.")
            tasks.pop(task_id, None)

    return Response(event_generator(), mimetype='text/event-stream')


# --- Scraping route needs to be updated or temporarily disabled ---
@app.route('/scrape', methods=['POST'])
async def scrape_channels_route():
    print("--- Received /scrape request (NEEDS UPDATE) ---")
    # This route still uses the old 'await request.get_json()' and needs
    # to be converted to the task/stream pattern if you want live logs.
    # For now, let's just return a placeholder or an error.
    return jsonify({"success": False, "error": "Scraping function needs update for streaming."}), 501

# --- Shutdown logic remains important ---
import atexit

def shutdown_playwright():
    print("Flask app is shutting down. Closing Playwright browser...")
    try:
        # Since the main loop is gone, just run it simply.
        # This might not run perfectly on Ctrl+C, but should run on clean shutdown.
        asyncio.run(scraper_logic.close_browser())
    except Exception as e:
        print(f"Error during Playwright shutdown: {e}")

atexit.register(shutdown_playwright)

if __name__ == '__main__':
    port = int(os.environ.get("FLASK_RUN_PORT", 5000))
    host = os.environ.get("FLASK_RUN_HOST", "0.0.0.0") # Changed default for local dev
    app.run(host=host, port=port, debug=(os.getenv('FLASK_DEBUG') == '1' or os.getenv('FLASK_ENV') == 'development'))