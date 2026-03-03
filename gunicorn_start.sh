#!/bin/bash
cd ~/webhook_converter
source venv/bin/activate
echo "Starting Webhook Converter Service..."
echo "Service will run on: http://0.0.0.0:8080"
echo "Health check: curl http://localhost:8080/health"
echo "Press Ctrl+C to stop the service"
gunicorn --bind 0.0.0.0:8080 --workers 2 app:app
