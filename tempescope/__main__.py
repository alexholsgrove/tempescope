"""Entry point:  python -m tempescope [--config config.yml] [--condition rain] [--demo]"""

import argparse
import json
import logging
import queue
import signal
import sys
import time
from pathlib import Path

import yaml

from . import weather as wx
from .effects import Display
from .hardware import Hardware

log = logging.getLogger("tempescope")

CONDITIONS = ["clear", "clouds", "drizzle", "rain", "thunderstorm", "snow", "fog"]


def forced(condition, live):
    """A fake reading for a forced mode, keeping the live wind and day/night."""
    intensity = {"clear": 0.0, "clouds": 0.7, "drizzle": 0.3}.get(condition, 1.0)
    wind = live.wind if live else 4.0
    is_day = live.is_day if live else True
    return wx.Weather(condition, intensity, wind, is_day, "forced")


class Tempescope:
    def __init__(self, cfg, args):
        self.cfg = cfg
        self.hw = Hardware(cfg["hardware"])
        self.display = Display(self.hw, cfg["effects"])
        self.commands = queue.Queue()
        self.source = cfg["weather"].get("source", "openweather")
        self.live = None                      # latest real weather reading
        self.mode = args.condition or "auto"  # auto | off | <condition>
        self.night = args.night
        self.demo = args.demo
        self.mqtt = None

        mcfg = cfg.get("mqtt") or {}
        if mcfg.get("enabled"):
            from .mqtt import HomeAssistantMQTT
            self.mqtt = HomeAssistantMQTT(mcfg, self.commands)
        elif self.source == "homeassistant":
            log.error("weather.source is 'homeassistant' but mqtt is not enabled")

    # -- state ------------------------------------------------------------

    def refresh(self):
        """Re-apply outputs for the current mode and report state."""
        if self.mode == "off":
            self.display.weather = None
            self.hw.off()
        elif self.mode == "auto":
            if self.live:
                self.display.apply(self.live)
        else:
            w = forced(self.mode, self.live)
            if self.night:
                w.is_day = False
            self.display.apply(w)
        self.publish()

    def publish(self):
        if not self.mqtt:
            return
        w = self.display.weather
        hw = self.hw
        self.mqtt.publish_state({
            "mode": self.mode,
            "condition": w.condition if w else "off",
            "wind": round(w.wind, 1) if w else 0,
            "fan": round(hw.fan.duty),
            "mist": round(hw.mist.duty),
            "pump": round(hw.pump.duty),
            "mist_enabled": "ON" if hw.mist.enabled else "OFF",
            "pump_enabled": "ON" if hw.pump.enabled else "OFF",
            "brightness": hw.leds.brightness,
        })

    # -- commands from Home Assistant ---------------------------------------

    def handle(self, key, payload):
        log.info("Command: %s = %s", key, payload)
        if key == "mode":
            if payload in ("auto", "off", *CONDITIONS):
                self.mode = payload
                self.demo = False
        elif key in ("mist_enabled", "pump_enabled"):
            out = self.hw.mist if key == "mist_enabled" else self.hw.pump
            out.set_enabled(payload.upper() == "ON")
        elif key == "brightness":
            self.hw.leds.set_brightness(float(payload))
        elif key == "weather":
            if self.source != "homeassistant":
                return
            self.live = wx.from_homeassistant(json.loads(payload))
        elif key != "republish":
            return
        self.refresh()

    # -- main loop ----------------------------------------------------------

    def run(self):
        wcfg = self.cfg["weather"]
        interval = wcfg.get("refresh_minutes", 10) * 60
        demo_secs = self.cfg.get("demo_seconds", 20)
        next_fetch = next_demo = 0.0
        demo_i = 0
        if self.mode != "auto":
            self.refresh()

        while True:
            now = time.monotonic()

            while not self.commands.empty():
                try:
                    self.handle(*self.commands.get_nowait())
                except Exception:
                    log.exception("Bad command")

            if self.demo and now >= next_demo:
                self.mode = CONDITIONS[demo_i % len(CONDITIONS)]
                log.info("Demo: %s", self.mode)
                demo_i += 1
                next_demo = now + demo_secs
                self.refresh()

            if self.source == "openweather" and now >= next_fetch:
                try:
                    self.live = wx.fetch(wcfg["api_key"], wcfg["location"])
                    next_fetch = now + interval
                    if self.mode == "auto":
                        self.refresh()
                    else:
                        self.publish()
                except Exception as e:
                    log.error("Weather fetch failed: %s (retrying in 60s)", e)
                    next_fetch = now + 60

            self.display.tick()
            time.sleep(0.05)

    def close(self):
        log.info("Shutting down")
        self.hw.close()
        if self.mqtt:
            self.mqtt.close()


def main():
    p = argparse.ArgumentParser(prog="tempescope")
    p.add_argument("--config", default=str(Path(__file__).resolve().parent.parent / "config.yml"))
    p.add_argument("--condition", choices=CONDITIONS, help="force a condition")
    p.add_argument("--night", action="store_true", help="with --condition: show night colours")
    p.add_argument("--demo", action="store_true", help="cycle through every condition")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = yaml.safe_load(Path(args.config).read_text())

    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)  # systemd stop -> clean shutdown

    app = Tempescope(cfg, args)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
