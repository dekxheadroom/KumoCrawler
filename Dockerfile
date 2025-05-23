# Base image with Playwright and Python pre-installed
FROM mcr.microsoft.com/playwright/python:v1.52.0-jammy

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
ENV FLASK_ENV=development
ENV FLASK_DEBUG=1
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5000

# Expose port Flask will run on
EXPOSE 5000

# Command to run the application using Uvicorn and the a2wsgi adapter
CMD ["uvicorn", "asgi:asgi_app", "--host", "0.0.0.0", "--port", "5000"]