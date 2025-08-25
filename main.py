import os
import sys
import json
import logging
import csv
import time
import math
from datetime import datetime
import subprocess
import io
import argparse
import numpy as np
import signal

# --- OUR NEW LOGIC MODULE ---
from detection_logic import LowPowerStrategy

# --- HARDWARE IMPORTS ---
try:
    from flask import Flask, render_template, Response, request, jsonify
    FLASK_ENABLED = True
except ImportError:
    Flask, render_template, Response, request, jsonify = None, None, None, None, None; FLASK_ENABLED = False; print("CRITICAL WARNING: Flask not found.")

try:
    from picamera2 import Picamera2
    CAMERA_ENABLED = True
except ImportError:
    Picamera2 = None; CAMERA_ENABLED = False; print("CRITICAL WARNING: Picamera2 not found.")

try:
    from hailo_platform.pyhailort import pyhailort
    import cv2
    AI_ENABLED = True
except ImportError:
    pyhailort, cv2 = None, None; AI_ENABLED = False; print("CRITICAL WARNING: Hailo Platform or OpenCV not found.")

try:
    import serial
    RADAR_ENABLED = True
except ImportError:
    serial = None; RADAR_ENABLED = False; print("CRITICAL WARNING: PySerial not found.")

logging.getLogger("picamera2").setLevel(logging.WARNING)

# --- HAILO MODEL CLASS (DEFINITIVE VERSION) ---
class HailoModel:
    def __init__(self, hef_path):
        logging.info(f"Loading Hailo model from {hef_path}")
        self.is_loaded = False
        if not AI_ENABLED or not os.path.exists(hef_path):
            logging.error(f"FATAL: AI libraries missing or HEF file not found at {hef_path}"); return

        try:
            hef = pyhailort.HEF(hef_path)
            self.target = pyhailort.VDevice()
            
            # 1. Configure the HEF on the target to get the network group(s).
            configured_networks = self.target.configure(hef)
            if not configured_networks:
                raise RuntimeError("Failed to configure the HEF on the VDevice.")
            self.network_group = configured_networks[0]
            
            # 2. Get stream info from the network group itself BEFORE activation.
            self.input_vstream_infos = self.network_group.get_input_vstream_infos()
            if not self.input_vstream_infos:
                raise RuntimeError("No input vstreams found.")
            self.input_tensor_shape = self.input_vstream_infos[0].shape
            
            self.class_names = self._load_class_names()
            self.is_loaded = True
            logging.info("Hailo model loaded and configured successfully.")
        except Exception as e:
            logging.error(f"FATAL: Failed during Hailo model initialization: {e}", exc_info=True); self.is_loaded = False

    def _load_class_names(self):
        with open("coco_labels.txt", "r") as f: return [line.strip() for line in f.readlines()]

    def _preprocess(self, image_np):
        height, width, _ = self.input_tensor_shape
        return cv2.resize(image_np, (width, height), interpolation=cv2.INTER_LINEAR)

    def _postprocess(self, raw_results, original_shape):
        detections = []
        original_height, original_width, _ = original_shape
        # The result from read() is a raw numpy array.
        for box in raw_results:
            confidence = box[4]
            if confidence > 0.45:
                class_id = np.argmax(box[5:])
                detections.append({
                    "type": self.class_names[class_id],
                    "confidence": round(float(confidence), 2),
                    "box_center": {"x": int(box[0] * original_width), "y": int(box[1] * original_height)}
                })
        return detections

    def run_inference(self, image_np):
        if not self.is_loaded: return []
        try:
            input_data = self._preprocess(image_np)
            # 3. The correct way to run inference is with the activate() context manager.
            with self.network_group.activate() as activated_network:
                # 4. The activated_network yields the streams for this run.
                activated_network.get_input_vstreams()[0].write(input_data)
                raw_results_nd_array = activated_network.get_output_vstreams()[0].read()

            return self._postprocess(raw_results_nd_array, image_np.shape)
        except Exception as e:
            logging.error(f"Error during Hailo inference: {e}", exc_info=True); return []

    def find_best_detection(self, detections, capture_shape, strategy='center'):
        if not detections: return None
        if strategy == 'confidence': return max(detections, key=lambda d: d['confidence'])
        cx, cy = capture_shape[1] / 2, capture_shape[0] / 2
        return min(detections, key=lambda d: math.sqrt((d['box_center']['x'] - cx)**2 + (d['box_center']['y'] - cy)**2))

# --- Global Configuration & State ---
STATIC_MOUNT_POINT = "/media/usb_data_drive"; STATE_FILE = "/tmp/traffic_state.json"; GRID_COLS, GRID_ROWS = 32, 18
LOGGER_CAPTURE_WIDTH, LOGGER_CAPTURE_HEIGHT = 1536, 864
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__, template_folder='templates') if FLASK_ENABLED else None

# --- Core System Functions (Unchanged) ---
def verify_usb_drive():
    if not os.path.isdir(STATIC_MOUNT_POINT):
        try: os.makedirs(STATIC_MOUNT_POINT); subprocess.run(["sudo", "chown", "traffic:traffic", STATIC_MOUNT_POINT], check=True)
        except Exception as e: logging.error(f"Could not create mount point: {e}"); return None
    if os.path.ismount(STATIC_MOUNT_POINT): return STATIC_MOUNT_POINT
    logging.warning("Mount point not in use. Attempting to find and mount USB drive.")
    try:
        if not os.path.exists("/dev/sda1"): logging.error("Could not find /dev/sda1."); return None
        cmd = ["sudo", "mount", "-t", "vfat", "-o", "uid=traffic,gid=traffic", "/dev/sda1", STATIC_MOUNT_POINT]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            cmd[3] = "exfat"; res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0: logging.error(f"Mount failed: {res.stderr.strip()}"); return None
        logging.info("Successfully mounted USB drive."); return STATIC_MOUNT_POINT
    except Exception as e: logging.error(f"USB mount error: {e}", exc_info=True); return None

def run_logger_process(deployment_folder):
    log_file_path = os.path.join(deployment_folder, "debug.log")
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')); file_handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(file_handler)
    logging.info(f"--- LOGGER MODE: LOGGING TO {log_file_path} ---")

    picam2_logger, radar_serial, csv_file_handle = None, None, None
    try:
        with open(os.path.join(deployment_folder, 'deployment_info.json'), 'r') as f: deployment_info = json.load(f)
        with open(os.path.join(deployment_folder, 'zone_map.json'), 'r') as f: zone_map = json.load(f)
        logging.info("Configuration files loaded successfully.")

        logging.info("Initializing hardware...")
        picam2_logger = Picamera2(); config = picam2_logger.create_still_configuration(main={"size": (LOGGER_CAPTURE_WIDTH, LOGGER_CAPTURE_HEIGHT)}, controls={"FrameDurationLimits": (10000, 10000)}); picam2_logger.configure(config); picam2_logger.start(); time.sleep(2)
        
        radar_serial = serial.Serial(port='/dev/ttyACM0', baudrate=9600, timeout=1); time.sleep(1)
        logging.info("Sending radar configuration commands...")
        radar_serial.write(b'O1\r\n'); time.sleep(0.1)
        radar_serial.write(b'S9\r\n'); time.sleep(0.1)
        radar_serial.write(b'OU\r\n'); time.sleep(0.1)

        hailo_model = HailoModel('yolov8s.hef')
        if not hailo_model.is_loaded: raise RuntimeError("AI Model failed to load.")
        logging.info("All hardware initialized successfully.")

        csv_path = os.path.join(deployment_folder, "traffic_data.csv")
        csv_file_handle = open(csv_path, 'a', newline=''); csv_writer = csv.writer(csv_file_handle)
        if os.path.getsize(csv_path) == 0:
            csv_writer.writerow(['timestamp_utc', 'object_type', 'confidence', 'speed_kph', 'cardinal_direction', 'location_type', 'obj_center_x', 'obj_center_y']); csv_file_handle.flush()
        logging.info("CSV writer ready.")

        strategy = LowPowerStrategy(picam2_logger, hailo_model, csv_writer, deployment_info, zone_map)
        logging.info("--- Starting Main Logging Loop ---")
        
        while True:
            line = ""
            try:
                line = radar_serial.readline().decode('utf-8').strip()
                if line:
                    logging.debug(f"Raw radar line: {line}")
                    speed_mps = None
                    if line.startswith('{') and line.endswith('}'):
                        data = json.loads(line)
                        if 'speed' in data: speed_mps = float(data['speed'])
                    elif '"mps"' in line:
                        parts = line.split(',');
                        if len(parts) == 2: speed_mps = float(parts[1])

                    if speed_mps is not None:
                        radar_data_to_process = {'Speed_mps': speed_mps}
                        strategy.process_radar_trigger(radar_data_to_process)
                        csv_file_handle.flush()
            except serial.SerialException as e:
                logging.error(f"Radar serial error: {e}. Re-initializing...", exc_info=True)
                if radar_serial: radar_serial.close(); time.sleep(5)
                try:
                    radar_serial = serial.Serial(port='/dev/ttyACM0', baudrate=9600, timeout=1)
                    logging.info("Re-sending radar configuration commands..."); 
                    radar_serial.write(b'O1\r\n'); time.sleep(0.1)
                    radar_serial.write(b'S9\r\n'); time.sleep(0.1)
                    radar_serial.write(b'OU\r\n'); time.sleep(0.1)
                except Exception as reinit_e:
                    logging.error(f"Failed to re-initialize radar: {reinit_e}. Retrying..."); time.sleep(10)
            except (json.JSONDecodeError, ValueError, IndexError, KeyError) as parse_e:
                logging.warning(f"Could not process radar line: '{line}'. Error: {parse_e}")
            except Exception as loop_e:
                logging.error(f"Unhandled exception in main loop: {loop_e}", exc_info=True)
    except Exception as e: 
        logging.error(f"FATAL error in logger setup: {e}", exc_info=True)
    finally:
        logging.info("Closing resources.");
        if radar_serial:
             logging.info("Sending command to turn off radar transmitter.")
             radar_serial.write(b'o0\r\n')
             radar_serial.close()
        if picam2_logger: picam2_logger.stop()
        if csv_file_handle: csv_file_handle.close()
        logging.getLogger().removeHandler(file_handler)

# --- Flask and Main Entry Point (Unchanged) ---
if app:
    # ... (Flask code is unchanged) ...
    @app.route('/save_settings', methods=['POST'])
    def save_settings():
        drive_path = verify_usb_drive()
        if not drive_path: return jsonify(success=False, message="USB drive not found."), 500
        try:
            data = request.json; ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            folder = os.path.join(drive_path, ts); os.makedirs(folder, exist_ok=True)
            detection_settings = {"vehicle_speed_kph": 8.0, "low_speed_kph": 1.0, "shot_interval_sec": 0.25, "cooldown_sec": {"default": 5.0, "person": 5.0, "bicycle": 8.0}}
            info = {"start_utc": datetime.utcnow().isoformat()+"Z", "gps": data.get('gps'), "notes": data.get('notes'), "bearing": data.get('bearing'), "deep_sleep": data.get('deep_sleep_enabled', False), "detection_settings": detection_settings}
            with open(os.path.join(folder, 'deployment_info.json'), 'w') as f: json.dump(info, f, indent=4)
            z_map = {"dims": [GRID_COLS, GRID_ROWS], "zones": {"0":"ignore", "1":"road", "2":"sidewalk", "3":"bike_lane"}, "map": data.get('mask')}
            with open(os.path.join(folder, 'zone_map.json'), 'w') as f: json.dump(z_map, f, indent=4)
            with Picamera2() as cam:
                config = cam.create_still_configuration(main={"size": (LOGGER_CAPTURE_WIDTH, LOGGER_CAPTURE_HEIGHT)}); cam.configure(config); cam.start(); time.sleep(2)
                cam.capture_file(os.path.join(folder, 'reference_photo.jpg'))
            logging.info(f"Saved new deployment: {ts}")
            return jsonify(success=True, message=f"Settings saved to: {ts}", new_folder=folder)
        except Exception as e:
            logging.error(f"Save settings error: {e}", exc_info=True); return jsonify(success=False, message=str(e)), 500
    
    # ... (the rest of the Flask code is identical)
    @app.route('/')
    def index():
        latest_folder = ""; drive_path = verify_usb_drive()
        if drive_path:
            try:
                folders = [os.path.join(drive_path, d) for d in os.listdir(drive_path) if os.path.isdir(os.path.join(drive_path, d))]
                if folders: latest_folder = max(folders, key=os.path.getmtime)
            except Exception as e: logging.error(f"Could not scan folders: {e}")
        return render_template('index.html', grid_cols=GRID_COLS, grid_rows=GRID_ROWS, latest_deployment_folder=latest_folder)
        
    @app.route('/capture_photo')
    def capture_photo():
        if not CAMERA_ENABLED: return "Error: Camera disabled.", 500
        try:
            with Picamera2() as camera:
                config = camera.create_still_configuration(main={"size": (LOGGER_CAPTURE_WIDTH, LOGGER_CAPTURE_HEIGHT)}); camera.configure(config); camera.start(); time.sleep(2)
                buffer = io.BytesIO(); camera.capture_file(buffer, format='jpeg'); buffer.seek(0)
                return Response(buffer, mimetype='image/jpeg')
        except Exception as e:
            logging.error(f"Photo capture error: {e}", exc_info=True); return "Error capturing photo.", 500
    
    @app.route('/set_time', methods=['POST'])
    def set_time():
        try:
            dt_str = request.json.get('datetime')
            if not dt_str: return jsonify(success=False, message="No datetime"), 400
            res = subprocess.run(["sudo", "/usr/bin/date", "-s", dt_str], capture_output=True, text=True)
            if res.returncode == 0: return jsonify(success=True, message=f"Time set to {dt_str}")
            else: logging.error(f"Set time failed: {res.stderr}"); return jsonify(success=False, message=res.stderr), 500
        except Exception as e:
            logging.error(f"Set time exception: {e}", exc_info=True); return jsonify(success=False, message=str(e)), 500

    @app.route('/switch_to_logger', methods=['POST'])
    def switch_to_logger():
        folder = request.json.get('folder')
        if not folder or not os.path.isdir(folder): return jsonify(success=False, message="Invalid folder."), 400
        try:
            with open(STATE_FILE, 'w') as f: json.dump({"mode": "logger", "folder": folder}, f)
            logging.info(f"State file written for folder {folder}. Requesting service restart.")
            subprocess.run(["sudo", "/usr/bin/systemctl", "restart", "traffic.service"])
            return jsonify(success=True, message="Restarting into Logger Mode...")
        except Exception as e:
            logging.error(f"State file error: {e}", exc_info=True); return jsonify(success=False, message=str(e)), 500

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument('--mode', type=str, choices=['server', 'logger'], required=True); parser.add_argument('--folder', type=str)
    args = parser.parse_args()
    if args.mode == 'server':
        if app: app.run(host='0.0.0.0', port=5000)
        else: print("ERROR: Flask not enabled.")
    elif args.mode == 'logger':
        if not args.folder or not os.path.isdir(args.folder): print(f"ERROR: --folder is required. Got: {args.folder}")
        else: run_logger_process(args.folder)