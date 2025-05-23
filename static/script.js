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
    const clearLogButton = document.getElementById('clearLogButton'); // Assuming you added this

    // Add a checkbox for toggling dev logs
    const devLogToggle = document.createElement('input');
    devLogToggle.type = 'checkbox';
    devLogToggle.id = 'devLogToggle';
    devLogToggle.checked = true; // Show dev logs by default
    const devLogLabel = document.createElement('label');
    devLogLabel.htmlFor = 'devLogToggle';
    devLogLabel.textContent = 'Show Developer Logs';
    devLogLabel.style.marginLeft = '10px';
    devLogLabel.style.fontSize = '0.8em';
    devLogLabel.style.fontWeight = 'normal';

    const statusHeader = document.querySelector('#statusSection h2');
    statusHeader.appendChild(devLogToggle);
    statusHeader.appendChild(devLogLabel);

    let siteCredentials = {};
    let eventSource = null;

    function logStatus(message, type = 'info') {
        const time = new Date().toLocaleTimeString();
        const logEntry = document.createElement('div');
        logEntry.textContent = `[${time}] ${message}`;
        logEntry.dataset.type = type; // Add data attribute for filtering

        // Check if dev logs should be hidden
        if (type === 'dev' && !devLogToggle.checked) {
            logEntry.style.display = 'none';
        }

        switch(type) {
            case 'error':
                logEntry.style.color = 'red';
                break;
            case 'success':
                logEntry.style.color = 'lime';
                break;
            case 'warn':
                 logEntry.style.color = 'orange';
                 break;
            case 'dev':
                 logEntry.style.color = '#888'; // Grey for dev logs
                 logEntry.textContent = `[${time}] [DEV] ${message}`; // Add prefix
                 break;
            case 'info':
            default:
                logEntry.style.color = '#0f0';
                break;
        }

        statusLog.appendChild(logEntry);
        statusLog.scrollTop = statusLog.scrollHeight;
    }

    // Add event listener for the toggle
    devLogToggle.addEventListener('change', () => {
        const allLogs = statusLog.querySelectorAll('div');
        allLogs.forEach(log => {
            if (log.dataset.type === 'dev') {
                log.style.display = devLogToggle.checked ? 'block' : 'none';
            }
        });
        statusLog.scrollTop = statusLog.scrollHeight; // Scroll to bottom after toggle
    });

    function clearLogs() {
        statusLog.innerHTML = '';
    }
    clearLogButton.addEventListener('click', clearLogs);

    function startEventStream(taskId) {
        if (eventSource) {
            eventSource.close();
        }

        logStatus(`Starting log stream for task ID: ${taskId}...`);
        eventSource = new EventSource(`/stream/${taskId}`);

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                // Check if 'type' exists, otherwise log as generic dev message
                const messageType = data.type || 'dev';
                const messageContent = data.content || JSON.stringify(data); // Fallback

                switch (messageType) {
                    case 'info':
                    case 'error':
                    case 'success':
                    case 'warn':
                    case 'dev':
                        logStatus(messageContent, messageType);
                        break;
                    case 'log': // Treat 'log' as 'info'
                        logStatus(messageContent, 'info');
                        break;
                    case 'channels':
                        logStatus('Successfully enumerated channels (via stream).', 'success');
                        displayChannels(messageContent);
                        channelSelectionSection.style.display = 'block';
                        scrapeButton.style.display = 'block';
                        refreshChannelsButton.style.display = 'inline-block';
                        break;
                    case 'end_stream':
                        logStatus(`Stream ended: ${messageContent}`, 'info');
                        eventSource.close();
                        connectButton.disabled = false;
                        connectButton.textContent = 'Connect & List Channels';
                        refreshChannelsButton.disabled = false;
                        break;
                    default:
                        logStatus(`Unknown message type: ${JSON.stringify(data)}`, 'warn');
                }
            } catch (error) {
                logStatus(`Error parsing server message: ${event.data}`, 'error');
            }
        };

        eventSource.onerror = (error) => {
            logStatus('EventSource encountered an error. Connection closed.', 'error');
            console.error("EventSource error:", error);
            if (eventSource) eventSource.close();
            connectButton.disabled = false;
            connectButton.textContent = 'Connect & List Channels';
            refreshChannelsButton.disabled = false;
        };
    }

    // --- loginForm submit, refreshChannelsButton, displayChannels, ---
    // --- updateChannelSelectionLimits, and scrapeButton logic remain the same ---
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
                logStatus(`Backend task started. Task ID: ${result.task_id}`);
                startEventStream(result.task_id);
            } else {
                logStatus(`Error starting task: ${result.error || 'Failed to start task.'}`, 'error'); // Use 'error' type
                connectButton.disabled = false;
                connectButton.textContent = 'Connect & List Channels';
            }
        } catch (error) {
            logStatus(`Client-side error during connection submission: ${error}`, 'error'); // Use 'error' type
            connectButton.disabled = false;
            connectButton.textContent = 'Connect & List Channels';
        }
    });

    refreshChannelsButton.addEventListener('click', () => {
         loginForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    });

    function displayChannels(channels) { /* ... as before ... */ }
    [depthEntireRadio, depth3MonthsRadio].forEach(radio => {
        radio.addEventListener('change', updateChannelSelectionLimits);
    });
    channelListDiv.addEventListener('change', (event) => {
        if (event.target.name === 'selectedChannels') {
            updateChannelSelectionLimits();
        }
    });
    function updateChannelSelectionLimits() { /* ... as before ... */ }
    scrapeButton.addEventListener('click', () => { 
        logStatus("Scraping needs to be updated for streaming.", 'warn');
    });

    // Helper for updateChannelSelectionLimits (if it's not already global)
    function updateChannelSelectionLimits() {
        const checkboxes = channelListDiv.querySelectorAll('input[name="selectedChannels"]');
        const selectedCheckboxes = Array.from(checkboxes).filter(cb => cb.checked);
        let maxChannels = depthEntireRadio.checked ? 1 : 3;
        checkboxes.forEach(cb => {
            cb.disabled = !cb.checked && selectedCheckboxes.length >= maxChannels;
        });
    }

    // Helper for displayChannels (if it's not already global)
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
            checkbox.value = JSON.stringify({name: channel.name, id: channel.id});
            const label = document.createElement('label');
            label.htmlFor = checkbox.id;
            label.textContent = channel.name;
            div.appendChild(checkbox);
            div.appendChild(label);
            channelListDiv.appendChild(div);
        });
        updateChannelSelectionLimits();
    }
});