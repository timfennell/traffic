#!/bin/bash

# ==============================================================================
#  run.sh - FINAL INTELLIGENT Dispatcher
# ==============================================================================
# This script checks for a state file to decide whether to launch the
# setup web server or the autonomous logger process.
# ==============================================================================

# --- Ensure we are in the correct directory ---
cd /home/traffic/traffic || exit 1

# --- Define the path for our state file ---
STATE_FILE="/tmp/traffic_state.json"

# --- Main Dispatch Logic ---
if [ -f "$STATE_FILE" ]; then
    # STATE FILE EXISTS: We need to start the logger.
    echo "State file found. Attempting to start Logger Mode."

    # Safely read the deployment folder path from the JSON file using jq
    FOLDER_PATH=$(jq -r '.folder' "$STATE_FILE")

    if [ -d "$FOLDER_PATH" ]; then
        # The folder exists, proceed with logging.
        echo "Target deployment folder is valid: $FOLDER_PATH"
        
        # CRITICAL: Remove the state file NOW so the next reboot defaults to server mode.
        rm "$STATE_FILE"

        # Launch the python logger script directly, passing the folder as an argument.
        # Using absolute paths for maximum reliability in the systemd environment.
        /usr/bin/python3 /home/traffic/traffic/main.py --mode logger --folder "$FOLDER_PATH"

    else
        # The folder specified in the state file is invalid. This is an error condition.
        echo "ERROR: Folder '$FOLDER_PATH' from state file does not exist. Aborting logger."
        echo "Removing invalid state file and defaulting to Setup Server Mode."
        rm "$STATE_FILE"
        /usr/bin/gunicorn --workers 1 --bind 0.0.0.0:5000 --timeout 120 main:app
    fi

else
    # STATE FILE DOES NOT EXIST: This is the default case. Start the setup server.
    echo "No state file found. Starting Setup Server Mode."
    /usr/bin/gunicorn --workers 1 --bind 0.0.0.0:5000 --timeout 120 main:app
fi