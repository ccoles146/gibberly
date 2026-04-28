#!/usr/bin/env python3
"""
Operator console dev server.

Serves the operator/ directory over HTTP on OPERATOR_PORT (default 9000).
Edit operator/config.js to set GIBBERLY_BACKEND before starting.

Usage:
  cd ~/gibberly/operator
  python3 serve.py
"""
import http.server

port = 9000

print(f"Serving operator console at http://localhost:{port}")
print("Edit operator/config.js to change GIBBERLY_BACKEND.")
http.server.test(
    HandlerClass=http.server.SimpleHTTPRequestHandler,
    port=port,
    bind="localhost",
)
