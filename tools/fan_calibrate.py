#!/usr/bin/env python3
"""Find the fan's minimum usable PWM duty cycle.

    ./venv/bin/python tools/fan_calibrate.py [--pin 24] [--step 5] [--hold 4]

Test 1 (stall): spins the fan up at 100%, then steps down. Answer whether the fan
is still turning at each step. This finds the lowest speed it keeps running at.

Test 2 (start): from a standstill, steps up until the fan starts by itself.
This finds the lowest speed that gets it going without a kick start.
"""
import argparse
import time

import RPi.GPIO as GPIO


def ask(prompt):
    while True:
        a = input(prompt + " [y/n] ").strip().lower()
        if a in ("y", "n"):
            return a == "y"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pin", type=int, default=24)
    p.add_argument("--freq", type=int, default=100, help="PWM frequency (Hz)")
    p.add_argument("--step", type=int, default=5, help="duty step (%%)")
    p.add_argument("--hold", type=float, default=4, help="seconds to settle at each step")
    args = p.parse_args()

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(args.pin, GPIO.OUT, initial=GPIO.LOW)
    pwm = GPIO.PWM(args.pin, args.freq)
    pwm.start(0)

    def run(duty, label=""):
        pwm.ChangeDutyCycle(duty)
        print(f"  {duty:3d}% {label}", flush=True)
        time.sleep(args.hold)

    stall = start = None
    try:
        print("\nTest 1: stall speed. The fan spins up at 100%, then slows down.")
        input("Press Enter to start...")
        run(100, "(spin up)")
        last_ok = 100
        for duty in range(100 - args.step, 0, -args.step):
            run(duty)
            if not ask("  Still spinning smoothly?"):
                stall = last_ok
                break
            last_ok = duty
        else:
            stall = last_ok
        print(f"=> Lowest speed that keeps it running: {stall}%")

        pwm.ChangeDutyCycle(0)
        print("\nTest 2: start speed. Waiting for the fan to stop...")
        time.sleep(max(5, args.hold))
        for duty in range(args.step, 101, args.step):
            run(duty)
            if ask("  Has it started spinning?"):
                start = duty
                break
            pwm.ChangeDutyCycle(0)   # back to a standstill before the next try
            time.sleep(2)
        print(f"=> Lowest speed that starts it from a standstill: {start}%")
    except KeyboardInterrupt:
        print("\nStopped early.")
    finally:
        pwm.stop()
        GPIO.cleanup()

    if stall:
        margin = min(100, stall + 5)
        print("\nSuggested config.yml settings:")
        if start and start <= margin:
            print(f"  fan_min: {max(margin, start)}\n  fan_kick: 0")
        else:
            print(f"  fan_min: {margin}       # a few % above the stall speed, for safety")
            print(f"  fan_kick: 1.0     # kick start at 100% (start speed was {start or '>100'}%)")


if __name__ == "__main__":
    main()
