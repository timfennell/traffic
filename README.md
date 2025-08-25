Of course. Creating a high-quality README is a crucial step for sharing your project. It serves as the front door, manual, and technical brief all in one.

Based on our entire development journey, here is a detailed, professional README file written in Markdown. You can copy and paste this directly into a README.md file in the root of your GitHub repository.

Autonomous AI Traffic Logger

An open-source, portable, low-power device for autonomous traffic monitoring and data collection. Built on a Raspberry Pi 5 with a Hailo-8L AI accelerator, it is designed for field deployment to log vehicles, cyclists, and pedestrians with detailed metadata.

![alt text](placeholder.jpg)

(Suggestion: Replace this with a real photo of your device)

Table of Contents

Project Goals

Key Features

Hardware Architecture

Software Architecture

Setup and Installation

Usage Workflow

Key Learnings & Technical Deep Dive

Future Development (Roadmap)

License

Project Goals

The primary goal of this project is to create a fully autonomous, low-power, "set it and forget it" device for traffic analysis. Traditional traffic counting methods can be expensive, require manual operation, or lack the ability to classify objects and gather rich metadata. This project aims to solve these issues by providing a cost-effective, open-source solution.

Primary Objectives:

Autonomy: Operate unattended for extended periods (~20 hours) on a portable USB-C battery pack.

Intelligence: Distinguish between object classes (vehicles, cyclists, pedestrians) using on-device AI.

Rich Data: Record the speed (km/h), cardinal direction of travel, and location (e.g., road, sidewalk) for each detected object.

Field Usability: Allow for on-site configuration via a Wi-Fi hotspot and a simple web interface, with no need for a dedicated monitor or keyboard.

Structured Output: Log all collected data to a removable USB drive in a clean, analysis-ready CSV format.

Key Features

AI-Powered Object Detection: Utilizes a Hailo-8L AI accelerator for efficient, low-power neural network inference.

Radar-Triggered System: A Doppler radar acts as a low-power "tripwire," only activating the camera and AI when motion is detected to maximize battery life.

Multi-Object Counting: Capable of detecting and logging multiple objects from a single trigger event.

"Conditional Two-Shot" Logic: An intelligent capture system that performs a second, quick-succession photo only when needed to calculate direction, saving power for stationary or pedestrian targets.

Per-Class Cooldowns: A smart cooldown system prevents double-counting the same slow-moving object while remaining ready to detect objects of a different class.

Web-Based UI for Setup: A mobile-friendly web interface for positioning the camera, painting detection zones, and inputting deployment metadata.

Robust System Management: Managed by a systemd service for automatic startup on boot and reliable operation.

Hardware Architecture

This project is built on a specific set of hardware designed to balance performance and power consumption.

Component	Model	Role & Connection
Compute	Raspberry Pi 5 (2GB)	Main processor running the application.
AI Accelerator	Raspberry Pi AI Hat+ (Hailo-8L)	Handles all neural network inference.
Vision Sensor	Raspberry Pi Camera Module 3 Wide Noir	Captures high-resolution images, day or night.
Motion Sensor	OmniPreSense OPS243-A Doppler Radar	Low-power "tripwire" for speed/motion detection (USB).
Networking	Onboard Wi-Fi (wlan0)	Creates the private traffic hotspot for setup.
Storage	USB Flash Drive (FAT32/exFAT)	Sole storage for all logged data and configuration.
Power	50Wh USB-C Battery Pack	Provides power for extended field deployment.
Software Architecture

The system is managed by a run.sh script, which is started on boot by a systemd service. It operates in two distinct modes.

1. Setup Mode (Default)

On boot, the run.sh script launches a Gunicorn/Flask web server. This creates the traffic Wi-Fi hotspot at 192.168.4.1. A user connects to this hotspot and navigates to http://traffic.local:5000 to access the setup UI. The UI allows for camera aiming, painting detection/ignore zones, and setting metadata before starting a logging session.

2. Logger Mode

When a logging session is started from the UI, the Flask application writes a state file (/tmp/traffic_state.json) and restarts the systemd service. On restart, run.sh detects the state file, bypasses the web server, and directly executes the main.py script to begin the autonomous logging process.

Data Flow (Logger Mode)

Trigger: The main.py script continuously listens for data from the radar.

Hand-off: When a valid speed reading is received, it is passed to the LowPowerStrategy class in detection_logic.py.

Triage: The strategy checks the speed against configured thresholds to decide between a high-speed or low-speed event.

Capture & Inference: The camera is triggered, and the captured image is processed by the HailoModel class, which handles the complex Hailo API interactions.

Logic & Counting: The strategy processes the list of AI detections, associates speed/direction, and logs a separate CSV row for each valid object not in an "ignore" zone.

Output: All data is written to the USB drive.

Data Output Structure

A new timestamped folder is created on the USB drive for each session, containing:

traffic_data.csv: The main data log.

debug.log: A verbose log of system operations for troubleshooting.

deployment_info.json: Metadata from the setup UI (GPS, notes, etc.).

zone_map.json: The user-painted detection zones.

reference_photo.jpg: A still image from the moment of setup.

Setup and Installation

This setup process has been tuned to create a stable, conflict-free environment. It is highly recommended to start with a fresh SD card image.

Flash OS: Flash a new SD card with Raspberry Pi OS Lite (64-bit).

Initial Config: Boot the Pi, run sudo raspi-config and:

Set up your user (traffic) and password.

Enable SSH and connect to the Pi.

Under "Advanced Options", enable Glamor graphics acceleration.

Under "Interface Options", enable the Legacy Camera support.

Install All Dependencies: Run this single, comprehensive command to install the Hailo drivers, Python libraries, and all application dependencies globally. Using the system's package manager avoids conflicts with the Hailo SDK.

code
Bash
download
content_copy
expand_less

sudo apt-get update
sudo apt-get install -y hailo-all python3-hailo-sdk python3-flask python3-opencv python3-numpy python3-serial gunicorn jq

Clone the Repository:

code
Bash
download
content_copy
expand_less
IGNORE_WHEN_COPYING_START
IGNORE_WHEN_COPYING_END
git clone https://github.com/your-username/your-repo-name.git /home/traffic/traffic
cd /home/traffic/traffic

Set up the Systemd Service:

Copy the service file to the system directory:

code
Bash
download
content_copy
expand_less
IGNORE_WHEN_COPYING_START
IGNORE_WHEN_COPYING_END
sudo cp /home/traffic/traffic/traffic.service /etc/systemd/system/

Enable and start the service:

code
Bash
download
content_copy
expand_less
IGNORE_WHEN_COPYING_START
IGNORE_WHEN_COPYING_END
sudo systemctl enable traffic.service
sudo systemctl start traffic.service

Reboot:

code
Bash
download
content_copy
expand_less
IGNORE_WHEN_COPYING_START
IGNORE_WHEN_COPYING_END
sudo reboot

The device should now boot up, and the traffic Wi-Fi hotspot should become available within a minute or two.

Usage Workflow

Power On: Connect the device to a USB-C power source.

Connect: Wait 1-2 minutes. On your phone or laptop, connect to the Wi-Fi network named traffic (password: traffic_logger).

Access UI: Open a web browser and navigate to http://traffic.local:5000 or http://192.168.4.1:5000.

Configure:

Use the live camera feed to aim the device.

Select a brush ("Road", "Sidewalk") and paint over the grid to define your detection zones. Paint areas you don't care about as "Ignore Area".

Fill in the metadata: GPS, camera bearing, and any relevant notes.

Deploy:

Click "Save New Settings". This creates a new session folder on the USB drive.

Click "Start Logging with these New Settings". The UI will become unresponsive, which is the correct behavior as the device switches to the headless logger mode.

Retrieve Data: To end a session, simply power down the device. You can then remove the USB drive and access the session folder containing the traffic_data.csv file on your computer.

Key Learnings & Technical Deep Dive

This project involved overcoming several significant technical hurdles. The solutions are documented here for others who may work with this hardware stack.

Hailo SDK Environment: The most stable environment was achieved by abandoning Python virtual environments and installing all dependencies globally using apt. This resolves conflicts between the application libraries and the low-level drivers expected by the pyhailort module.

Hailo API Workflow: The correct sequence for inference on the Pi AI Hat+ is non-obvious. The final, working pattern is: VDevice() -> .configure(HEF) -> with .activate() as activated_network: -> activated_network.get_..._vstreams() -> .write()/.read().

Radar Configuration: The OmniPreSense radar requires specific serial commands upon initialization (O1, S9, OU) to turn on its transmitter, set sensitivity, and output a continuous stream of data in the desired format. Without these commands, it may remain silent or send unparsable data.

Systemd and Permissions: Running the master systemd service as the traffic user provides a good security baseline, while specific sudo calls within the Python script handle privileged operations like mounting the USB drive and setting the system time.

Future Development (Roadmap)

This project provides a solid foundation for many future enhancements:

[ ] "Always On" Video Mode: Implement a second detection strategy that processes a continuous video stream instead of still images. This would be suitable for deployments where the device can be connected to mains power.

[ ] UI Enhancements: Add fields to the web UI to allow for on-site tuning of detection parameters (e.g., speed thresholds, cooldown timers) which are then saved to deployment_info.json.

[ ] Advanced Object Tracking: Evolve the per-class cooldown system into a more robust tracker that can follow individual objects through the frame to prevent re-counting if they stop and start moving again.

[ ] Data Analysis Tools: Create a companion set of Python scripts and/or a Jupyter Notebook for easy analysis and visualization of the generated traffic_data.csv files.

License

This project is licensed under the MIT License. See the LICENSE file for details.
