#!/usr/bin/env bash
# ESP32-S3-DevKitC-1-N16R8: UART upload, native USB reserved for HID.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -ne 1 || "$1" == '--help' ]]; then
  echo 'Usage: ./hardware/flash.sh SERIAL_PORT | --build-only'
  exit 0
fi
cli="${ARDUINO_CLI:-arduino-cli}"
if ! command -v "$cli" >/dev/null 2>&1; then
  echo 'Missing arduino-cli. See docs/setup.md.' >&2
  exit 1
fi
if [[ ! -f hardware/hid_bridge/secrets.h ]]; then
  echo 'Copy hardware/hid_bridge/secrets.example.h to secrets.h and edit it first.' >&2
  exit 1
fi
fqbn="${FQBN:-esp32:esp32:esp32s3:USBMode=default,CDCOnBoot=default,CPUFreq=80,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB,UploadSpeed=460800}"
"$cli" --config-file arduino-cli.yaml compile --fqbn "$fqbn" \
  --build-property 'compiler.cpp.extra_flags=-DDEBUG_SERIAL=1' \
  --build-path "$PWD/hardware/build" hardware/hid_bridge
if [[ "$1" != '--build-only' ]]; then
  "$cli" --config-file arduino-cli.yaml upload --fqbn "$fqbn" \
    --port "$1" --input-dir "$PWD/hardware/build" hardware/hid_bridge
fi
