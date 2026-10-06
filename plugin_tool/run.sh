#!/bin/bash
# Start the program with its venv (made by Prepare in standalone_tools).
cd "$(dirname "$0")"
exec venv/bin/python -u code/plugin_tools.py "$@"
