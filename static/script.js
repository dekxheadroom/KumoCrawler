document.addEventListener('DOMContentLoaded', () => {
    // Get all the elements from the DOM
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
    const statusHeader = document.querySelector('#statusSection h2');

    // --- FIX: Create devLogToggle, don't try to get it ---
    const devLogToggle = document.createElement('input');
    devLogToggle.type = 'checkbox';
    devLogToggle.id = 'devLogToggle';
    devLogToggle.checked = false; // Default to OFF for less clutter
    const devLogLabel = document.createElement('label');
    devLogLabel.htmlFor = 'devLogToggle';
    devLogLabel.textContent = 'Show Dev Logs';
    devLogLabel.style.marginLeft = '10px';
    devLogLabel.style.fontSize = '0.8em';
    devLogLabel.style.fontWeight = 'normal';

    // --- FIX: Check if statusHeader exists before appending ---
    if (statusHeader) {
        statusHeader.appendChild(devLogToggle);
        statusHeader.appendChild(devLogLabel);
    } else {
        console.error("Status header (h2) not found! Cannot add dev log toggle.");
    }
    // --- END FIX ---

    let siteCredentials = {};
    let eventSource = null;

    function logStatus(message, type = 'info') {
        const time = new Date().toLocaleTimeString();
        const logEntry = document.createElement('div');
        logEntry.textContent = `[${time}] ${message}`;
        logEntry.dataset.type = type;

        // Check if dev logs should be hidden (ensure devLogToggle exists)
        if (devLogToggle && type === 'dev' && !devLogToggle.checked) {
            logEntry.style.display = 'none';
        }

        switch(type) {
            case 'error': logEntry.style.color = 'red'; break;
            case 'success': logEntry.style.color = 'lime'; break;
            case 'warn': logEntry.style.color = 'orange'; break;
            case 'dev': logEntry.style.color = '#888'; logEntry.textContent = `[${time}] [DEV] ${message}`; break;
            case 'info': default: logEntry.style.color = '#0f0'; break;
        }

        // Check if statusLog exists before appending
        if (statusLog) {
            statusLog.appendChild(logEntry);
            statusLog.scrollTop = statusLog.scrollHeight;
        } else {
            console.error("Status log element not found!");
        }
    }

    // Add event listener for the toggle (it exists now)
    devLogToggle.addEventListener('change', () => {
        const allLogs = statusLog.querySelectorAll('div');
        allLogs.forEach(log => {
            if (log.dataset.type === 'dev') {
                log.style.display = devLogToggle.checked ? 'block' : 'none';
            }
        });
        if(statusLog) statusLog.scrollTop = statusLog.scrollHeight;
    });

    function clearLogs() {
        if(statusLog) statusLog.innerHTML = '';
    }

    // --- FIX: Check if clearLogButton exists before adding listener ---
    if (clearLogButton) {
        clearLogButton.addEventListener('click', clearLogs);
    } else {
        console.warn("Clear Log Button not found, cannot add listener.");
    }
    // --- END FIX ---

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
                        if(channelSelectionSection) channelSelectionSection.style.display = 'block';
                        if(scrapeButton) scrapeButton.style.display = 'block'; // Show scrape button
                        if(refreshChannelsButton) refreshChannelsButton.style.display = 'inline-block';
                        if(connectButton) {
                           connectButton.disabled = false; // Re-enable after enumeration
                           connectButton.textContent = 'Connect & List Channels';
                        }
                        break;
                    case 'download_ready':
                        logStatus(`Scraping complete. Download ready for task ID: ${messageContent}`, 'success');
                        if(downloadLink) downloadLink.href = `/download/${messageContent}`;
                        if(downloadSection) downloadSection.style.display = 'block';
                        if(scrapeButton) {
                            scrapeButton.disabled = false; // Re-enable scrape button
                            scrapeButton.textContent = 'Start Scraping';
                        }
                        break;
                    case 'all_done':
                         logStatus('All scraping tasks have finished processing.', 'info');
                         break;
                    case 'end_stream':
                        logStatus(`Stream ended: ${messageContent}`, 'info');
                        eventSource.close();
                        if(connectButton) {
                            connectButton.disabled = false;
                            connectButton.textContent = 'Connect & List Channels';
                        }
                        if(refreshChannelsButton) refreshChannelsButton.disabled = false;
                        if(scrapeButton) {
                            scrapeButton.disabled = false;
                            scrapeButton.textContent = 'Start Scraping';
                        }
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
            if(connectButton) {
                connectButton.disabled = false;
                connectButton.textContent = 'Connect & List Channels';
            }
            if(refreshChannelsButton) refreshChannelsButton.disabled = false;
            if(scrapeButton) {
                 scrapeButton.disabled = false;
                 scrapeButton.textContent = 'Start Scraping';
            }
        };
    }

    if (loginForm) {
        loginForm.addEventListener('submit', async (event) => {
            event.preventDefault(); // This is VITAL!
            if(connectButton) {
                connectButton.disabled = true;
                connectButton.textContent = 'Connecting...';
            }
            clearLogs();
            logStatus('Submitting connection request...');
            if(channelSelectionSection) channelSelectionSection.style.display = 'none';
            if(channelListDiv) channelListDiv.innerHTML = '';
            if(downloadSection) downloadSection.style.display = 'none';
            if(refreshChannelsButton) refreshChannelsButton.disabled = true;
            if(scrapeButton) scrapeButton.style.display = 'none';

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
                    if(connectButton) {
                       connectButton.disabled = false;
                       connectButton.textContent = 'Connect & List Channels';
                    }
                }
            } catch (error) {
                logStatus(`Client-side error: ${error}`, 'error');
                if(connectButton) {
                    connectButton.disabled = false;
                    connectButton.textContent = 'Connect & List Channels';
                }
            }
        });
    } else {
        console.error("Login Form not found!");
    }

    if (refreshChannelsButton) {
        refreshChannelsButton.addEventListener('click', () => {
             if(loginForm) loginForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
        });
    }

    if (scrapeButton) {
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
            if(downloadSection) downloadSection.style.display = 'none';

            const payload = {
                ...siteCredentials,
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
                    startEventStream(result.task_id);
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
    }


    function displayChannels(channels) {
        if(!channelListDiv) return;
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
            label.textContent = `${channel.name}`;
            div.appendChild(checkbox);
            div.appendChild(label);
            channelListDiv.appendChild(div);
        });
        updateChannelSelectionLimits();
    }

    [depthEntireRadio, depth3MonthsRadio].forEach(radio => {
        if(radio) radio.addEventListener('change', updateChannelSelectionLimits);
    });

    if (channelListDiv) {
        channelListDiv.addEventListener('change', (event) => {
            if (event.target.name === 'selectedChannels') {
                updateChannelSelectionLimits();
            }
        });
    }

    function updateChannelSelectionLimits() {
        if(!channelListDiv) return;
        const checkboxes = channelListDiv.querySelectorAll('input[name="selectedChannels"]');
        const selectedCheckboxes = Array.from(checkboxes).filter(cb => cb.checked);
        let maxChannels = depthEntireRadio.checked ? 1 : 3;
        checkboxes.forEach(cb => {
            cb.disabled = !cb.checked && selectedCheckboxes.length >= maxChannels;
        });
        if(scrapeButton) scrapeButton.disabled = selectedCheckboxes.length === 0;
    }

}); // End of DOMContentLoaded