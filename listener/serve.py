#!/usr/bin/env python3
"""
Listener page server.

Serves the listener/ directory over HTTP on port 8080.

Usage:
  cd ~/gibberly/listener
  python3 serve.py
"""
import http.server

port = 8080

print(f"Serving listener page at http://localhost:{port}")
http.server.test(
    HandlerClass=http.server.SimpleHTTPRequestHandler,
    port=port,
    bind="localhost",
)
