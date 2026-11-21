#!/usr/bin/env bash
# Tempescope setup for Raspberry Pi OS Trixie (32-bit Lite) on a Pi Zero W.
# Run from the project folder on the Pi:  bash setup.sh [--service]
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"

echo "==> Installing system packages"
sudo apt update
sudo apt install -y python3-venv python3-dev python3-rpi-lgpio python3-yaml python3-paho-mqtt \
                    build-essential swig
sudo apt remove -y python3-rpi.gpio 2>/dev/null || true   # conflicts with rpi-lgpio

echo "==> Creating virtualenv"
python3 -m venv --system-site-packages venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
./venv/bin/python -c "import RPi.GPIO, rpi_ws281x, yaml, paho.mqtt.client; print('OK: imports work')"

[ -f config.yml ] || { cp config.example.yml config.yml; echo "==> Created config.yml - edit it!"; }

if [[ "${1:-}" == "--service" ]]; then
  echo "==> Installing systemd service"
  sed "s#/home/pi/tempescope#$DIR#g" systemd/tempescope.service | sudo tee /etc/systemd/system/tempescope.service >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now tempescope
  echo "Logs: journalctl -u tempescope -f"
fi
