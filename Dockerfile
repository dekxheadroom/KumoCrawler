# Base image with Playwright and Python pre-installed
FROM mcr.microsoft.com/playwright/python:v1.53.0-jammy

# Set working directory
WORKDIR /app

# Copy application files
COPY . .

# Install Python dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# The Playwright base image already runs `playwright install --with-deps chromium`
# If you needed other browsers, you could add:
# RUN playwright install firefox webkit --with-deps

# Environment variables (can be overridden at runtime)
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5000

# Expose port Flask will run on
EXPOSE 5000

# Command to run the application
# Using Gunicorn for a more production-ready WSGI server is recommended for actual production,
# but for simplicity with async Flask and to keep dependencies minimal, we'll use Flask's built-in server.
# For Gunicorn with Uvicorn workers for async: CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "app:app", "-b", "0.0.0.0:5000"]
CMD ["python", "-m", "flask", "run"]