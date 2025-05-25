# app.py

from quart import Quart, render_template, request, jsonify, Response, send_file # Added send_file
from dotenv import load_dotenv
import os
import json
import io
import scraper_logic
import asyncio
from uuid import uuid4
import atexit
import re

load_dotenv()

app = Quart(__name__)
tasks = {} # Stores task status and queues
results = {} # Stores scraping results

@app.route('/')
async def index():
    return await render_template('index.html')

# --- Wrapper for login/enumeration task ---
async def run_login_task_wrapper(task_id, url, username, password):
    log_queue = tasks.get(task_id, {}).get('log_queue')
    if not log_queue: return
    try:
        await scraper_logic.login_and_enumerate_task(url, username, password, log_queue)
    except Exception as e:
        await scraper_logic.log_update(log_queue, "error", f"Task wrapper error: {e}")
        await scraper_logic.log_update(log_queue, "end_stream", "Process failed abruptly.")
    finally:
        if task_id in tasks: tasks[task_id]['status'] = 'finished'

# --- Wrapper for scraping task ---
async def run_scrape_task_wrapper(task_id, url, username, password, channel_url, depth):
    log_queue = tasks.get(task_id, {}).get('log_queue')
    if not log_queue: return
    try:
        await scraper_logic.scrape_messages_task(url, username, password, channel_url, depth, log_queue)
    except Exception as e:
        await scraper_logic.log_update(log_queue, "error", f"Scrape Task wrapper error: {e}")
        await scraper_logic.log_update(log_queue, "end_stream", f"Scraping failed abruptly for {channel_url}.")
    finally:
         if task_id in tasks: tasks[task_id]['status'] = 'finished' # Mark individual task finished

@app.route('/connect_and_enumerate', methods=['POST'])
async def connect_and_enumerate_channels_route():
    data = await request.get_json()
    url, username, password = data.get('url'), data.get('username'), data.get('password')
    if not all([url, username, password]):
        return jsonify({"success": False, "error": "Missing data."}), 400

    task_id = str(uuid4())
    log_queue = asyncio.Queue()
    tasks[task_id] = {
        'type': 'enumerate',
        'url': url, 'username': username, 'password': password,
        'log_queue': log_queue, 'status': 'running'
    }
    asyncio.create_task(run_login_task_wrapper(task_id, url, username, password))
    return jsonify({"success": True, "task_id": task_id})

# --- UPDATED /scrape route ---
@app.route('/scrape', methods=['POST'])
async def scrape_channels_route():
    print("\n--- Received /scrape request ---")
    try:
        data = await request.get_json()
        print(f"Scrape request data: {data}")
        url = data.get('url')
        username = data.get('username')
        password = data.get('password')
        channels = data.get('channels') # List of {name: '...', id: '...'}
        depth = data.get('depth')

        if not all([url, username, password, channels, depth]):
            print("Scrape request missing data.")
            return jsonify({"success": False, "error": "Missing data for scraping."}), 400

        if not channels:
            return jsonify({"success": False, "error": "No channels selected."}), 400

        main_task_id = str(uuid4()) # One ID to rule the stream
        log_queue = asyncio.Queue()
        tasks[main_task_id] = {
            'type': 'scrape',
            'log_queue': log_queue,
            'status': 'starting',
            'sub_tasks': len(channels),
            'results_data': [] # To store results
        }
        print(f"Generated Main Scrape Task ID: {main_task_id}")

        async def run_all_scrapes():
            """Manages multiple scrape tasks under one main task ID."""
            await scraper_logic.log_update(log_queue, "info", f"Starting scrape for {len(channels)} channel(s)...")
            scrape_tasks = []
            for channel in channels:
                # We need a *separate* wrapper call for each channel.
                # They will *all* log to the *same* queue.
                channel_url = channel.get('id')
                channel_name = channel.get('name')
                await scraper_logic.log_update(log_queue, "info", f"Queueing scrape for: {channel_name}")
                # We pass the *main* task_id so the wrapper can find the queue
                scrape_tasks.append(
                    asyncio.create_task(
                        scraper_logic.scrape_messages_task(
                            url, username, password, channel_url, depth, log_queue
                        )
                    )
                )
            # Wait for all individual scraping tasks to complete
            await asyncio.gather(*scrape_tasks)
            # Once all are done, send a final 'all_done' message
            await scraper_logic.log_update(log_queue, "all_done", main_task_id)
            await scraper_logic.log_update(log_queue, "end_stream", "All scraping tasks finished.")

        # Start the manager task
        asyncio.create_task(run_all_scrapes())
        tasks[main_task_id]['status'] = 'running'
        print(f"Returning main task ID {main_task_id} to client.")
        return jsonify({"success": True, "task_id": main_task_id})

    except Exception as e:
        print(f"!!! ERROR in /scrape: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Internal server error: {e}"}), 500

@app.route('/stream/<task_id>')
async def stream_logs(task_id):
    if task_id not in tasks:
        return Response("Task ID not found.", status=404, mimetype='text/plain')

    log_queue = tasks[task_id]['log_queue']

    async def event_generator():
        yield f"data: {json.dumps({'type': 'info', 'content': 'Log stream connected.'})}\n\n"
        while True:
            log_entry = await log_queue.get()
            log_queue.task_done()

            # --- Handle Scrape Results ---
            if log_entry.get("type") == "scrape_result":
                tasks[task_id]['results_data'].append(log_entry.get("content"))
                yield f"data: {json.dumps({'type': 'info', 'content': f'Received results for {log_entry["content"]["channel_name"]}'})}\n\n"
                continue # Don't send full results down stream, just info

            # --- Handle 'All Done' for Scraping ---
            if log_entry.get("type") == "all_done":
                # Store results globally using the task_id
                results[task_id] = tasks[task_id]['results_data']
                yield f"data: {json.dumps({'type': 'download_ready', 'content': task_id})}\n\n"
                # Keep stream open until 'end_stream'

            yield f"data: {json.dumps(log_entry)}\n\n"
            if log_entry.get("type") == "end_stream":
                break
        # --- Cleanup ---
        print(f"Closing stream & cleaning task for {task_id}.")
        # Don't pop results, just the task metadata
        tasks.pop(task_id, None)

    response = Response(event_generator(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

# --- NEW /download route ---
@app.route('/download/<task_id>')
async def download_results(task_id):
    if task_id not in results:
        return "Results not found or expired.", 404

    data_to_download = results.get(task_id)
    if not data_to_download:
         return "No data found for this task ID.", 404

    # Create a JSON file in memory
    str_io = io.StringIO()
    json.dump(data_to_download, str_io, indent=4)
    mem_io = io.BytesIO(str_io.getvalue().encode('utf-8'))
    mem_io.seek(0)

    # Clean up the stored result after preparing download (optional)
    # results.pop(task_id, None)

    return await send_file(
        mem_io,
        mimetype='application/json',
        as_attachment=True,
        attachment_filename=f'kumocrawler_scrape_{task_id[:8]}.json'
    )

atexit.register(scraper_logic.close_browser) # Changed to call the sync wrapper

if __name__ == '__main__':
    print("To run locally without Docker: uvicorn app:app --host 0.0.0.0 --port 5000 --reload")