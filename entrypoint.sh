#!/bin/bash
set -e

# Ensure data directories exist
# Note: If running as non-root, this script will try to create/fix permissions
# If permission denied, the app will handle it gracefully
mkdir -p /app/data/jobs 2>/dev/null || true

# Try to fix permissions if we have permission (we won't as appuser, but that's ok)
# The key is that the mounted volume should be writable by the container user
chmod 755 /app/data 2>/dev/null || true
chmod 755 /app/data/jobs 2>/dev/null || true

# Start the application
exec "$@"
