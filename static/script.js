document.addEventListener('DOMContentLoaded', () => {
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

    let siteCredentials = {}; // To store URL, username, password for reuse

    function logStatus(message, isError = false) {
        const time = new Date().toLocaleTimeString();
        const logEntry = document.createElement('div');
        logEntry.textContent = `[${time}] ${message}`;
        if (isError) {
            logEntry.style.color = 'red';
        }
        statusLog.appendChild(logEntry);
        statusLog.scrollTop = statusLog.scrollHeight; // Auto-scroll
    }

    loginForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        connectButton.disabled = true;
        connectButton.textContent = 'Connecting...';
        logStatus('Attempting to connect and list channels...');
        channelSelectionSection.style.display = 'none';
        channelListDiv.innerHTML = ''; // Clear previous list
        downloadSection.style.display = 'none';

        siteCredentials = {
            url: document.getElementById('rcUrl').value,
            username: document.getElementById('rcUsername').value,
            password: document.getElementById('rcPassword').value,
        };

        await fetchChannels();
        
        connectButton.disabled = false;
        connectButton.textContent = 'Connect & List Channels';
    });

    async function fetchChannels() {
        try {
            const response = await fetch('/connect_and_enumerate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(siteCredentials),
            });

            const result = await response.json();
            (result.status_updates || []).forEach(update => logStatus(update));

            if (result.success && result.channels) {
                logStatus('Successfully enumerated channels.');
                displayChannels(result.channels);
                channelSelectionSection.style.display = 'block';
                scrapeButton.style.display = 'block';
                refreshChannelsButton.style.display = 'inline-block';
            } else {
                logStatus(`Error: ${result.error || 'Failed to list channels.'}`, true);
                channelSelectionSection.style.display = 'none';
            }
        } catch (error) {
            logStatus(`Client-side error during channel enumeration: ${error}`, true);
            channelSelectionSection.style.display = 'none';
        }
    }
    
    refreshChannelsButton.addEventListener('click', async () => {
        logStatus('Refreshing channel list...');
        refreshChannelsButton.disabled = true;
        await fetchChannels();
        refreshChannelsButton.disabled = false;
    });


    function displayChannels(channels) {
        channelListDiv.innerHTML = ''; // Clear previous
        if (channels.length === 0) {
            channelListDiv.innerHTML = '<p>No channels found or accessible.</p>';
            return;
        }
        channels.forEach(channel => {
            const div = document.createElement('div');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = `ch_${channel.id.replace(/[^a-zA-Z0-9]/g, "")}`; // Sanitize ID
            checkbox.name = 'selectedChannels';
            checkbox.value = JSON.stringify({name: channel.name, id: channel.id}); // Store name and nav ID
            
            const label = document.createElement('label');
            label.htmlFor = checkbox.id;
            label.textContent = channel.name;

            div.appendChild(checkbox);
            div.appendChild(label);
            channelListDiv.appendChild(div);
        });
        updateChannelSelectionLimits(); // Apply limits initially
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
        
        let maxChannels;
        if (depthEntireRadio.checked) {
            maxChannels = 1;
        } else { // depth3MonthsRadio.checked
            maxChannels = 3;
        }

        if (selectedCheckboxes.length >= maxChannels) {
            checkboxes.forEach(cb => {
                if (!cb.checked) {
                    cb.disabled = true;
                }
            });
        } else {
            checkboxes.forEach(cb => {
                cb.disabled = false;
            });
        }
    }

    scrapeButton.addEventListener('click', async () => {
        const selectedCheckboxes = Array.from(channelListDiv.querySelectorAll('input[name="selectedChannels"]:checked'));
        if (selectedCheckboxes.length === 0) {
            logStatus('No channels selected for scraping.', true);
            return;
        }

        const channelsToScrape = selectedCheckboxes.map(cb => JSON.parse(cb.value));
        const scrapeDepth = document.querySelector('input[name="scrapeDepth"]:checked').value;

        logStatus(`Starting scraping for ${channelsToScrape.length} channel(s) with depth: ${scrapeDepth}...`);
        scrapeButton.disabled = true;
        scrapeButton.textContent = 'Scraping...';
        downloadSection.style.display = 'none';

        try {
            const payload = {
                ...siteCredentials, // Include original URL and credentials for re-login if backend needs it
                channels: channelsToScrape,
                depth: scrapeDepth,
            };
            const response = await fetch('/scrape', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            // Server will send status updates via JSON if it's an error,
            // or a file if it's successful.
            if (response.ok && response.headers.get('content-type')?.includes('application/json')) {
                 // It might be a JSON response for the file content itself or an error
                const disposition = response.headers.get('content-disposition');
                if (disposition && disposition.indexOf('attachment') !== -1) {
                    // Handle file download
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    downloadLink.href = url;
                    
                    // Extract filename from content-disposition header
                    let filename = "rocketchat_scrape.json"; // Default
                    const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                    let matches = filenameRegex.exec(disposition);
                    if (matches != null && matches[1]) { 
                        filename = matches[1].replace(/['"]/g, '');
                    }
                    downloadLink.download = filename;

                    downloadSection.style.display = 'block';
                    logStatus('Scraping complete. Download link available.');
                } else { // It's a JSON error message from the /scrape endpoint
                    const result = await response.json();
                    (result.status_updates || []).forEach(update => logStatus(update));
                    logStatus(`Scraping error: ${result.error || 'Unknown error during scraping.'}`, true);
                }
            } else if (!response.ok) { // Other HTTP error
                 try {
                    const errorResult = await response.json(); // Try to parse JSON error
                    (errorResult.status_updates || []).forEach(update => logStatus(update));
                    logStatus(`Scraping failed: ${errorResult.error || response.statusText}`, true);
                } catch (e) {
                    logStatus(`Scraping failed: ${response.statusText}`, true);
                }
            } else {
                // This case might not be hit if all successful scrapes send 'application/json' with attachment.
                // If successful response is not JSON, means it's likely the file stream directly.
                logStatus('Unexpected response type from server during scrape.', true);
            }

        } catch (error) {
            logStatus(`Client-side error during scraping: ${error}`, true);
        } finally {
            scrapeButton.disabled = false;
            scrapeButton.textContent = 'Start Scraping';
        }
    });
});