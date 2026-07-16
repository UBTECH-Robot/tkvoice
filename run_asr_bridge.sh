#!/bin/bash
source /opt/ros/humble/setup.bash
exec python3 /debug/tkvoice/src/audio_service/audio_service/asr_bridge.py
