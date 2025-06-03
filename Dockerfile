# Use an official Python runtime as a parent image
FROM python:3.11-slim-buster

# Set the working directory in the container
WORKDIR /app

# Install system dependencies, including ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    # You can add these if you run into audio issues on Render
    # libopus0 \
    # libsodium-dev \
    # libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed Python packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Define environment variable for the bot token
# This is a placeholder. On Render, you'll set this securely in the dashboard.
ENV DISCORD_BOT_TOKEN="your_bot_token_placeholder"

# Run main.py when the container launches
CMD ["python", "main.py"]
