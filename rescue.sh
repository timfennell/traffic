#!/bin/bash
echo "--- RESCUE SCRIPT ACTIVATED ---"
systemctl unmask wpa_supplicant.service
systemctl enable wpa_supplicant.service
systemctl disable traffic.service
echo "Default Wi-Fi re-enabled. Custom service disabled. Reboot now."