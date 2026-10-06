#!/bin/bash
# Start plugin_tool using its venv (recreate it with python3 install.py).
cd "$(dirname "$0")"
exec venv/bin/python -u code/plugin_tools.py "$@"
