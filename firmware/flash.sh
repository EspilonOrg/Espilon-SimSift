#!/usr/bin/env bash
# flash.sh — Build and flash SimSift bridge firmware
#
# Usage:
#   ./flash.sh t-call     /dev/ttyUSB0
#   ./flash.sh t-sim7070g /dev/ttyACM0

set -euo pipefail

BOARD="${1:-}"
PORT="${2:-}"

if [ -z "$BOARD" ] || [ -z "$PORT" ]; then
    echo "Usage: $0 <board> <port>"
    echo "       boards: t-call, t-sim7070g"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIGS_DIR="$SCRIPT_DIR/configs"
CONFIG_FILE="$CONFIGS_DIR/$BOARD"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: Unknown board '$BOARD' — no config at $CONFIG_FILE"
    exit 1
fi

IDF_PATH="${IDF_PATH:-$HOME/esp-idf}"
source "$IDF_PATH/export.sh" > /dev/null 2>&1

echo ""
echo "  Board  : $BOARD"
echo "  Port   : $PORT"
echo ""

cp "$CONFIG_FILE" "$SCRIPT_DIR/sdkconfig.defaults"
rm -f "$SCRIPT_DIR/sdkconfig"
rm -rf "$SCRIPT_DIR/build"

idf.py -C "$SCRIPT_DIR" set-target esp32 > /dev/null 2>&1
idf.py -C "$SCRIPT_DIR" build 2>&1 | grep -E "^\[|error:|Project build"
idf.py -C "$SCRIPT_DIR" -p "$PORT" flash

echo ""
echo "  Done — SimSift bridge running on $BOARD"
