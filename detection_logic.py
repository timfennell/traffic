import time
import logging
import math
import csv
from datetime import datetime
import numpy as np

class LowPowerStrategy:
    def __init__(self, camera, model, csv_writer, deployment_info, zone_map):
        logging.info("Initializing LowPowerStrategy v2.0...")
        self.picam2 = camera
        self.hailo_model = model
        self.csv_writer = csv_writer
        
        # --- Load settings from config file with safe defaults ---
        self.settings = deployment_info.get("detection_settings", {})
        self.vehicle_classes = self.settings.get("vehicle_classes", {'car', 'motorcycle', 'bus', 'truck'})
        self.vehicle_speed_kph = self.settings.get("vehicle_speed_kph", 8.0)
        self.low_speed_kph = self.settings.get("low_speed_kph", 2.0)
        self.shot_interval_sec = self.settings.get("shot_interval_sec", 0.25)
        self.cooldown_config_sec = self.settings.get("cooldown_sec", {"default": 5.0, "person": 5.0, "bicycle": 8.0})

        self.camera_bearing = int(deployment_info.get("bearing", 0))
        self.grid_dims = zone_map.get("dims", [32, 18])
        self.zone_names = zone_map.get("zones", {})
        self.zone_map_grid = zone_map.get("map", [])
        
        # --- Per-class cooldown timers ---
        self.cooldown_timers = {}

    def _get_location_type(self, x, y):
        grid_cols, grid_rows = self.grid_dims
        w, h = self.picam2.camera_configuration()['main']['size']
        col = int((x / w) * grid_cols)
        row = int((y / h) * grid_rows)
        if 0 <= row < grid_rows and 0 <= col < grid_cols:
            zone_id = str(self.zone_map_grid[row][col])
            return self.zone_names.get(zone_id, "unknown")
        return "out_of_bounds"

    def _calculate_direction(self, start_pos, end_pos):
        dx, dy = end_pos['x'] - start_pos['x'], end_pos['y'] - start_pos['y']
        if abs(dx) < 5 and abs(dy) < 5: return "Stationary"
        angle = math.degrees(math.atan2(dy, dx))
        if -45 <= angle <= 45: rel = "Right"
        elif 45 < angle < 135: rel = "Down"
        elif -135 < angle < -45: rel = "Up"
        else: rel = "Left"
        maps = {0:{"Up":"N","Down":"S","Left":"W","Right":"E"}, 90:{"Up":"E","Down":"W","Left":"N","Right":"S"}, 180:{"Up":"S","Down":"N","Left":"E","Right":"W"}, 270:{"Up":"W","Down":"E","Left":"S","Right":"N"}}
        return maps.get(self.camera_bearing, {}).get(rel, f"Rel_{rel}")

    def _capture_and_analyze(self):
        try:
            image_array = self.picam2.capture_array()
            detections = self.hailo_model.run_inference(image_array)
            # --- DEBUGGING ENHANCEMENT #3 ---
            logging.info(f"AI analysis complete. Found {len(detections)} detections.")
            return detections
        except Exception as e:
            logging.error(f"Capture/analysis error: {e}", exc_info=True)
            return []

    def _log_all_detections(self, detections, speed_kph, primary_direction="N/A"):
        if not detections: return
        
        primary_target = next((d for d in detections if d['type'] in self.vehicle_classes), None)
        if not primary_target:
            w, h = self.picam2.camera_configuration()['main']['size']
            primary_target = min(detections, key=lambda d: math.sqrt((d['box_center']['x'] - w/2)**2 + (d['box_center']['y'] - h/2)**2))

        for d in detections:
            location = self._get_location_type(d['box_center']['x'], d['box_center']['y'])
            if location == 'ignore':
                logging.debug(f"Discarding {d['type']} in IGNORE zone.")
                continue

            speed = speed_kph if d == primary_target else "Associated"
            direction = primary_direction if d == primary_target else "Associated"
            
            cooldown_period = self.cooldown_config_sec.get(d['type'], self.cooldown_config_sec.get("default", 5.0))
            self.cooldown_timers[d['type']] = time.monotonic() + cooldown_period

            log_entry = [datetime.utcnow().isoformat()+"Z", d['type'], d['confidence'], speed, direction, location, d['box_center']['x'], d['box_center']['y']]
            self.csv_writer.writerow(log_entry)
            logging.info(f"LOGGED: {d['type']} at speed {speed}, dir {direction}")

    def process_radar_trigger(self, radar_data):
        speed_kph = round(radar_data.get('Speed_mps', 0) * 3.6, 2)
        
        logging.debug(f"Radar trigger: {speed_kph} kph")

        if speed_kph >= self.vehicle_speed_kph:
            self._handle_high_speed_event(speed_kph)
        elif speed_kph >= self.low_speed_kph:
            current_time = time.monotonic()
            if any(current_time >= self.cooldown_timers.get(cls, 0) for cls in ['person', 'bicycle']):
                 self._handle_low_speed_event(speed_kph)
            else:
                logging.debug("Low-speed event ignored: all relevant classes on cooldown.")

    def _handle_high_speed_event(self, speed_kph):
        logging.info(f"High-speed event ({speed_kph} kph). Two-Shot.")
        detections1 = self._capture_and_analyze()
        time.sleep(self.shot_interval_sec)
        detections2 = self._capture_and_analyze()

        direction = "N/A"
        if detections1 and detections2:
            cam_size = self.picam2.camera_configuration()['main']['size']
            best1 = self.hailo_model.find_best_detection(detections1, cam_size)
            best2 = self.hailo_model.find_best_detection(detections2, cam_size)
            if best1 and best2 and best1['type'] == best2['type']:
                direction = self._calculate_direction(best1['box_center'], best2['box_center'])
        
        self._log_all_detections(detections2, speed_kph, direction)

    def _handle_low_speed_event(self, speed_kph):
        logging.info(f"Low-speed event ({speed_kph} kph). Conditional-Shot.")
        detections = self._capture_and_analyze()
        if not detections: return

        current_time = time.monotonic()
        valid_detections = [d for d in detections if current_time >= self.cooldown_timers.get(d['type'], 0)]
        if not valid_detections:
            logging.debug("Detections found but all classes are on cooldown. Ignoring.")
            return

        direction = "N/A"
        if any(d['type'] == 'bicycle' for d in valid_detections):
            logging.info("Bicycle detected, getting second shot for direction.")
            time.sleep(self.shot_interval_sec)
            detections2 = self._capture_and_analyze()
            if detections2:
                cam_size = self.picam2.camera_configuration()['main']['size']
                bike1 = self.hailo_model.find_best_detection([d for d in valid_detections if d['type'] == 'bicycle'], cam_size)
                bike2 = self.hailo_model.find_best_detection([d for d in detections2 if d['type'] == 'bicycle'], cam_size)
                if bike1 and bike2:
                    direction = self._calculate_direction(bike1['box_center'], bike2['box_center'])
                valid_detections = detections2

        self._log_all_detections(valid_detections, speed_kph, direction)