#!/bin/bash
cd /debug/tkvoice
pkill -f tkvoice_venv.*container_pipeline.py 2>/dev/null || true
sleep 1
VLLM=$(docker ps --format '{{.Names}}' | grep vllm | head -1)
if [ -n "$VLLM" ]; then
    docker exec "$VLLM" /debug/tkvoice/tkvoice_venv/bin/python3 \
        /debug/tkvoice/container_pipeline.py > /debug/tkvoice/pipeline.log 2>&1 &
    echo "PID=$! (container=$VLLM)"
else
    echo "ERROR: no vllm container found"
fi
