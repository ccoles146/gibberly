#!/bin/bash
# This script starts the Caddy web server to serve the operator console.
# Move to the directory where the script is located
cd "$(dirname "$0")"

echo "Starting Caddy..."
echo "Serving Operator page at 🌐http://localhost:9000"
# This assumes the caddy binary and Caddyfile are in the same folder as this script
# .command file must be executable - chmod +x start-operator.command
./caddy-mac run --config ./Caddyfile
