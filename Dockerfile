# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies needed by Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 wget && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (!!! IMPORTANT !!!)
RUN playwright install --with-deps chromium

# Copy the rest of your application's code into the container at /app
COPY . .

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Set environment variables (if any)
# ENV QUART_APP=app.py
# ENV QUART_ENV=production

# Define the command to run your app using Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000"]