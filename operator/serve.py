#!/usr/bin/env python3
"""
Operator console dev server.

Serves the operator/ directory over HTTP on OPERATOR_PORT (default 9000).
Edit operator/config.js to set GIBBERLY_BACKEND before starting.

Usage:
  cd ~/gibberly
  python3 operator/serve.py
"""
import http.server
import os
import pathlib

env_file = pathlib.Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

port = int(os.environ.get("OPERATOR_PORT", "9000"))

os.chdir(pathlib.Path(__file__).parent)
print(f"Serving operator console at http://localhost:{port}")
print("Edit operator/config.js to change GIBBERLY_BACKEND.")
http.server.test(
    HandlerClass=http.server.SimpleHTTPRequestHandler,
    port=port,
    bind="localhost",
)
