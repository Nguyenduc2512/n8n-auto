#!/bin/sh

echo "📦 Running DB migration..."
n8n migrate:run

echo "🚀 Starting n8n..."
exec n8n start
