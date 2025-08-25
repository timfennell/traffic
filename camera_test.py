import time
import logging

# Set up logging to see detailed errors
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    logging.info("Attempting to import Picamera2...")
    from picamera2 import Picamera2
    logging.info("Picamera2 imported successfully.")

    logging.info("Attempting to import cv2 (OpenCV)...")
    import cv2
    logging.info("cv2 (OpenCV) imported successfully.")

    logging.info("--- TEST: Initializing camera ---")
    with Picamera2() as camera:
        logging.info("Camera object created.")
        config = camera.create_still_configuration()
        logging.info("Configuration created.")
        camera.configure(config)
        logging.info("Camera configured.")
        camera.start()
        logging.info("Camera started.")
        time.sleep(1)
        camera.capture_file("test_capture.jpg")
        logging.info("--- SUCCESS: Photo captured successfully to test_capture.jpg ---")

except Exception as e:
    logging.error(f"--- TEST FAILED ---", exc_info=True)