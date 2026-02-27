#!/bin/bash
# Carga .env y arranca el gateway
set -a
source .env
set +a
python3 -m uvicorn gateway:app --host 0.0.0.0 --port ${PORT:-8200} --reload 2>&1 | tee -a gateway.log
