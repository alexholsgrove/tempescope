"""Turn a Weather reading into fan/mist/pump levels and LED animations."""

import math
import random
import time

from .hardware import color


def wind_to_fan(wind, cfg):
    """Map wind speed (m/s) to fan duty. Below fan_min the fan may stall, so
    any noticeable wind starts at fan_min."""
    if wind < 1.0:
        return 0.0
    frac = min(1.0, wind / cfg["wind_max"])
    return cfg["fan_min"] + frac * (100 - cfg["fan_min"])


class Display:
    def __init__(self, hw, cfg):
        self.hw = hw
        self.cfg = cfg
        self.weather = None
        self._next_flash = 0.0

    def apply(self, w):
        """Set the slow-changing outputs for a new weather reading."""
        self.weather = w
        c = self.cfg
        mist = pump = 0.0

        if w.condition == "clouds":
            mist = c["mist_min"] + w.intensity * (c["mist_max"] - c["mist_min"])
        elif w.condition in ("drizzle", "rain", "thunderstorm"):
            mist = c["mist_max"]
            pump = c["pump_min"] + w.intensity * (c["pump_max"] - c["pump_min"])
        elif w.condition in ("snow", "fog"):
            mist = c["mist_max"]

        self.hw.mist.set(mist)
        self.hw.pump.set(pump)

        fan = wind_to_fan(w.wind, c)
        kick = c.get("fan_kick", 0)
        if kick and fan > 0 and self.hw.fan.duty == 0:
            # Low speeds may not start a stopped fan: give it a burst at full power first
            self.hw.fan.set(100)
            time.sleep(kick)
        self.hw.fan.set(fan)

    def tick(self):
        """Advance the LED animation one frame. Call this frequently."""
        w = self.weather
        if w is None:
            return
        t = time.monotonic()
        leds = self.hw.leds
        breathe = 0.75 + 0.25 * math.sin(t * 0.8)   # slow gentle pulse

        if not w.is_day:
            base = (10, 15, 60)                      # moonlight blue
        elif w.condition == "clear":
            base = (255, 160, 40)                    # warm sun
        elif w.condition == "clouds":
            g = int(200 - 100 * w.intensity)
            base = (g, g, g + 20)
        elif w.condition in ("drizzle", "rain"):
            base = (40, 70, 160)
        elif w.condition == "thunderstorm":
            base = (25, 25, 60)
        elif w.condition == "snow":
            base = (200, 210, 255)
        else:                                        # fog
            base = (120, 120, 130)

        leds.fill(color(*(v * breathe for v in base)))

        if w.condition == "thunderstorm" and t >= self._next_flash:
            self._lightning(leds)
            self._next_flash = t + random.uniform(0.5, 6.0)

        leds.show()

    @staticmethod
    def _lightning(leds):
        """A few rapid white flashes on random pixels."""
        for _ in range(random.randint(1, max(1, leds.count // 3))):
            pixel = random.randrange(leds.count)
            leds.set(pixel, color(255, 255, 255))
            leds.show()
            time.sleep(random.uniform(0.01, 0.1))
            leds.set(pixel, 0)
            leds.show()
