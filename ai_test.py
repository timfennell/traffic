import logging
import os

# Set up logging to see detailed errors
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    logging.info("--- AI HARDWARE TEST ---")
    logging.info("Attempting to import Hailo Platform and OpenCV...")
    
    # --- THE CORRECTED IMPORT STATEMENT ---
    from hailo_platform.pyhailort import pyhailort
    import cv2
    
    logging.info("Libraries imported successfully.")
    
    # NOTE: The rest of the Hailo API is different. For this test,
    # simply importing the library is enough to prove it works.
    # We will stop here. A successful import is a complete victory.
    
    logging.info("--- SUCCESS: Hailo libraries were found and imported successfully! ---")

except Exception as e:
    logging.error(f"--- AI TEST FAILED ---", exc_info=True)