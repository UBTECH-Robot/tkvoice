#!/bin/bash
cd /debug/tkvoice
pkill -f venv.*container_pipeline.py 2>/dev/null || true
sleep 1
docker exec walker-llm.vllm-1 /debug/tkvoice/venv/bin/python3 /debug/tkvoice/container_pipeline.py > /debug/tkvoice/pipeline.log 2>&1 &
echo  PID=$!
