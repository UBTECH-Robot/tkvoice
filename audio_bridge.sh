#!/bin/bash
WAV=/debug/tkvoice/output.wav
LAST=0
while true; do
    if [ -f "$WAV" ]; then
        MT=$(stat -c %Y "$WAV" 2>/dev/null || echo 0)
        if [ "$MT" -gt "$LAST" ]; then
            LAST=$MT
            echo "[AUDIO] Playing $WAV"
            paplay --device=48 "$WAV" 2>/dev/null || paplay "$WAV" 2>/dev/null
            echo "[AUDIO] Done"
        fi
    fi
    sleep 0.3
done
