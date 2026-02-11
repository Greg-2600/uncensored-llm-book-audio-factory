#!/bin/bash
# Setup script to prepare the environment for Docker Compose deployment
# Run this script before `docker-compose up`

set -e

echo "📚 Setting up Uncensored LLM Book + Audio Factory..."

# Create data directory if it doesn't exist
mkdir -p data

# Set proper permissions for the data directory
# The container runs as uid 1000 (appuser), so the directory must be writable
chmod 777 data

echo "✅ Environment setup complete!"
echo "You can now run: docker-compose up -d --build"
