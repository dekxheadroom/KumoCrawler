// static/script.js

document.addEventListener('DOMContentLoaded', () => {
    // ... (Get all the elements as before) ...
    const loginForm = document.getElementById('loginForm');
    const connectButton = document.getElementById('connectButton');
    const channelSelectionSection = document.getElementById('channelSelectionSection');
    const channelListDiv = document.getElementById('channelList');
    const refreshChannelsButton = document.getElementById('refreshChannelsButton');
    const scrapeButton = document.getElementById('scrapeButton');
    const depthEntireRadio = document.getElementById('depthEntire');
    const depth3MonthsRadio = document.getElementById('depth3Months');
    const statusLog = document.getElementById('statusLog');
    const downloadSection = document.getElementById('downloadSection');
    const downloadLink = document.getElementById('downloadLink');
    const clearLogButton = document.getElementById('clearLogButton');
    const devLogToggle = document.getElementById('devLogToggle'); // Ensure you have this

    let siteCredentials = {};
    let eventSource = null;

    function logStatus(message, type = 'info') {
        const time = new Date().toLocaleTimeString();
        const logEntry = document.createElement('div');
        logEntry.textContent = `[${time}] ${message}`;
        logEntry.dataset.type = type;

        if (type === 'dev' && !devLogToggle.checked) {
            logEntry.style.display = 'none';
        }

        switch(type) {
            case 'error': logEntry.style.color = 'red'; break;
            case 'success': logEntry.style.color = 'lime'; break;
            case 'warn': logEntry.style.color = 'orange'; break;
            case 'dev': logEntry.style.color = '#888'; logEntry.textContent = `[${time}] [DEV] ${message}`; break;
            case 'info': default: logEntry.style.color = '#0f0'; break;
        }
        statusLog.appendChild(logEntry);
        statusLog.scrollTop = statusLog.scrollHeight;
    }

    // ... (devLogToggle listener and clearLogs function as before) ...
    devLogToggle.addEventListener('change', () => {
        const allLogs = statusLog.querySelectorAll('div');
        allLogs.forEach(log => {
            if (log.dataset.type === 'dev') {
                log.style.display = devLogToggle.checked ? 'block' : 'none';
            }
        });
        statusLog.scrollTop = statusLog.scrollHeight;
    });

     clearLogButton.addEventListener('click', () => {
        statusLog.innerHTML = '';
     });


    function startEventStream(taskId) {
        if (eventSource) { eventSource.close(); }
        logStatus(`Starting log stream for task ID: ${taskId}...`);
        eventSource = new EventSource(`/stream/${taskId}`);

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const messageType = data.type || 'dev';
                const messageContent = data.content || JSON.stringify(data);

                switch (messageType) {
                    case 'info': case 'error': case 'success': case 'warn': case 'dev':
                        logStatus(messageContent, messageType);
                        break;
                    case 'channels':
                        logStatus('Successfully enumerated channels.', 'success');
                        displayChannels(messageContent);
                        channelSelectionSection.style.display = 'block';
                        scrapeButton.style.display = 'block'; // Show scrape button
                        refreshChannelsButton.style.display = 'inline-block';
                        connectButton.disabled = false; // Re-enable after enumeration
                        connectButton.textContent = 'Connect & List Channels';
                        break;
                    // --- NEW: Handle Download Ready ---
                    case 'download_ready':
                        logStatus(`Scraping complete. Download ready for task ID: ${messageContent}`, 'success');
                        downloadLink.href = `/download/${messageContent}`;
                        downloadSection.style.display = 'block';
                        scrapeButton.disabled = false; // Re-enable scrape button
                        scrapeButton.textContent = 'Start Scraping';
                        break;
                    case 'all_done': // Just log, 'download_ready' handles UI
                         logStatus('All scraping tasks have finished processing.', 'info');
                         break;
                    case 'end_stream':
                        logStatus(`Stream ended: ${messageContent}`, 'info');
                        eventSource.close();
                        // Re-enable buttons if not already done
                        connectButton.disabled = false;
                        connectButton.textContent = 'Connect & List Channels';
                        refreshChannelsButton.disabled = false;
                        scrapeButton.disabled = false; // Ensure scrape button is enabled
                        scrapeButton.textContent = 'Start Scraping';
                        break;
                    default:
                        logStatus(`Unknown message type: ${JSON.stringify(data)}`, 'warn');
                }
            } catch (error) {
                logStatus(`Error parsing server message: ${event.data}`, 'error');
                console.error("Parse Error:", error);
            }
        };

        eventSource.onerror = (error) => {
            logStatus('EventSource encountered an error. Connection closed.', 'error');
            console.error("EventSource error:", error);
            if (eventSource) eventSource.close();
            connectButton.disabled = false;
            connectButton.textContent = 'Connect & List Channels';
            refreshChannelsButton.disabled = false;
            scrapeButton.disabled = false;
            scrapeButton.textContent = 'Start Scraping';
        };
    }

    loginForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        connectButton.disabled = true;
        connectButton.textContent = 'Connecting...';
        clearLogs();
        logStatus('Submitting connection request...');
        channelSelectionSection.style.display = 'none';
        channelListDiv.innerHTML = '';
        downloadSection.style.display = 'none';
        refreshChannelsButton.disabled = true;
        scrapeButton.style.display = 'none'; // Hide scrape button initially

        siteCredentials = {
            url: document.getElementById('rcUrl').value,
            username: document.getElementById('rcUsername').value,
            password: document.getElementById('rcPassword').value,
        };

        try {
            const response = await fetch('/connect_and_enumerate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(siteCredentials),
            });
            const result = await response.json();
            if (result.success && result.task_id) {
                logStatus(`Backend enumeration task started. Task ID: ${result.task_id}`);
                startEventStream(result.task_id);
            } else {
                logStatus(`Error starting task: ${result.error || 'Unknown error.'}`, 'error');
                connectButton.disabled = false;
                connectButton.textContent = 'Connect & List Channels';
            }
        } catch (error) {
            logStatus(`Client-side error: ${error}`, 'error');
            connectButton.disabled = false;
            connectButton.textContent = 'Connect & List Channels';
        }
    });

    refreshChannelsButton.addEventListener('click', () => {
         loginForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    });

    // --- UPDATED scrapeButton listener ---
    scrapeButton.addEventListener('click', async () => {
        const selectedCheckboxes = Array.from(
            channelListDiv.querySelectorAll('input[name="selectedChannels"]:checked')
        );

        if (selectedCheckboxes.length === 0) {
            logStatus("Please select at least one channel to scrape.", "warn");
            return;
        }

        const selectedChannels = selectedCheckboxes.map(cb => JSON.parse(cb.value));
        const depth = depthEntireRadio.checked ? "entire_history" : "3months";

        logStatus(`Starting scrape for ${selectedChannels.length} channel(s) with depth: ${depth}...`);
        scrapeButton.disabled = true;
        scrapeButton.textContent = 'Scraping...';
        downloadSection.style.display = 'none'; // Hide old download link

        const payload = {
            ...siteCredentials, // Use stored credentials
            channels: selectedChannels,
            depth: depth,
        };

        try {
            const response = await fetch('/scrape', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (result.success && result.task_id) {
                logStatus(`Backend scrape task started. Task ID: ${result.task_id}`);
                startEventStream(result.task_id); // Start streaming logs for this new task
            } else {
                logStatus(`Error starting scrape task: ${result.error || 'Unknown error.'}`, 'error');
                scrapeButton.disabled = false;
                scrapeButton.textContent = 'Start Scraping';
            }
        } catch (error) {
            logStatus(`Client-side error during scrape submission: ${error}`, 'error');
            scrapeButton.disabled = false;
            scrapeButton.textContent = 'Start Scraping';
        }
    });

    // ... (displayChannels and updateChannelSelectionLimits as before) ...
    function displayChannels(channels) {
        channelListDiv.innerHTML = '';
        if (channels.length === 0) {
            channelListDiv.innerHTML = '<p>No channels found or accessible.</p>';
            return;
        }
        channels.forEach(channel => {
            const div = document.createElement('div');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = `ch_${channel.id.replace(/[^a-zA-Z0-9]/g, "")}`;
            checkbox.name = 'selectedChannels';
            // Store both name and ID (which is the full URL now)
            checkbox.value = JSON.stringify({name: channel.name, id: channel.id});
            const label = document.createElement('label');
            label.htmlFor = checkbox.id;
            label.textContent = `${channel.name}`; // Show just name
            div.appendChild(checkbox);
            div.appendChild(label);
            channelListDiv.appendChild(div);
        });
        updateChannelSelectionLimits();
    }

    [depthEntireRadio, depth3MonthsRadio].forEach(radio => {
        radio.addEventListener('change', updateChannelSelectionLimits);
    });
    channelListDiv.addEventListener('change', (event) => {
        if (event.target.name === 'selectedChannels') {
            updateChannelSelectionLimits();
        }
    });

    function updateChannelSelectionLimits() {
        const checkboxes = channelListDiv.querySelectorAll('input[name="selectedChannels"]');
        const selectedCheckboxes = Array.from(checkboxes).filter(cb => cb.checked);
        let maxChannels = depthEntireRadio.checked ? 1 : 3;
        checkboxes.forEach(cb => {
            cb.disabled = !cb.checked && selectedCheckboxes.length >= maxChannels;
        });
        // Enable/Disable scrape button based on selection
        scrapeButton.disabled = selectedCheckboxes.length === 0;
    }

});