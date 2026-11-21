#!/usr/bin/env python3
"""Interactively set duty cycle on a PWM output.

    ./venv/bin/python tools/pwm_test.py fan|mist|pump   (or a BCM pin number)
"""
import sys

PINS = {"fan": 24, "mist": 17, "pump": 22}

name = sys.argv[1] if len(sys.argv) > 1 else "fan"
pin = PINS.get(name) or int(name)

if name in ("mist", "pump"):
    if input(f"Running the {name} dry can damage it. Is there water in the tank? [y/N] ").lower() != "y":
        sys.exit("Aborted.")

import RPi.GPIO as GPIO  # imported after the check so nothing touches GPIO first

GPIO.setmode(GPIO.BCM)
GPIO.setup(pin, GPIO.OUT)
pwm = GPIO.PWM(pin, 100)
pwm.start(0)
try:
    while True:
        try:
            duty = float(input(f"{name} (GPIO{pin}) duty 0-100: "))
        except ValueError:
            continue
        pwm.ChangeDutyCycle(max(0.0, min(100.0, duty)))
except (KeyboardInterrupt, EOFError):
    pass
finally:
    pwm.stop()
    GPIO.cleanup()
