"""Hardware drivers: NeoPixel ring + PWM outputs (fan, mist, pump).

On a machine without the Pi libraries (e.g. a Mac), mock drivers are used
so the effect logic can be developed and tested anywhere.
"""

import logging

log = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO  # provided by python3-rpi-lgpio on Trixie
except ImportError:
    GPIO = None

try:
    from rpi_ws281x import PixelStrip
except ImportError:
    PixelStrip = None


def color(r, g, b):
    """Pack RGB into the 24-bit int rpi_ws281x expects."""
    return (int(r) << 16) | (int(g) << 8) | int(b)


class LEDRing:
    def __init__(self, cfg):
        self.count = cfg["count"]
        self.brightness = cfg.get("brightness", 255)
        self._mock = PixelStrip is None
        if self._mock:
            log.warning("rpi_ws281x not available: using mock LED ring")
            self._pixels = [0] * self.count
            return
        self._strip = PixelStrip(
            self.count,
            cfg["pin"],
            800000,              # signal frequency
            cfg.get("dma", 10),
            cfg.get("invert", False),
            self.brightness,
            cfg.get("channel", 0),
        )
        self._strip.begin()

    def set(self, i, c):
        if self._mock:
            self._pixels[i] = c
        else:
            self._strip.setPixelColor(i, c)

    def fill(self, c):
        for i in range(self.count):
            self.set(i, c)

    def show(self):
        if not self._mock:
            self._strip.show()

    def set_brightness(self, value):
        self.brightness = max(0, min(255, int(value)))
        if not self._mock:
            self._strip.setBrightness(self.brightness)

    def off(self):
        self.fill(0)
        self.show()


class PWMOutput:
    """A MOSFET-driven load (fan, mister, pump) on a software-PWM GPIO pin."""

    def __init__(self, name, pin, freq=100, enabled=True):
        self.name = name
        self.pin = pin
        self.enabled = enabled
        self.duty = 0.0
        self._pwm = None
        if not enabled:
            log.warning("%s (GPIO %d) is DISABLED in config: it will stay off", name, pin)
        if GPIO is None:
            log.warning("RPi.GPIO not available: mock %s on GPIO %d", name, pin)
            return
        # Drive the pin low immediately so the MOSFET is definitely off
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
        self._pwm = GPIO.PWM(pin, freq)
        self._pwm.start(0)

    def set(self, duty):
        if not self.enabled:
            return
        duty = max(0.0, min(100.0, float(duty)))
        if duty != self.duty:
            log.info("%s -> %.0f%%", self.name, duty)
            self.duty = duty
            if self._pwm:
                self._pwm.ChangeDutyCycle(duty)

    def off(self):
        self.set(0)

    def set_enabled(self, enabled):
        if enabled == self.enabled:
            return
        if not enabled:
            self.set(0)          # switch off before locking out
        self.enabled = enabled
        log.warning("%s %s", self.name, "ENABLED" if enabled else "DISABLED")


class Hardware:
    def __init__(self, cfg):
        if GPIO is not None:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
        pins = cfg["pins"]
        disabled = set(cfg.get("disabled") or [])
        freqs = cfg.get("pwm_freq") or {}
        self.leds = LEDRing(cfg["leds"])

        def out(name):
            return PWMOutput(name, pins[name], freqs.get(name, 100), enabled=name not in disabled)

        self.fan = out("fan")
        self.mist = out("mist")
        self.pump = out("pump")

    def off(self):
        for out in (self.fan, self.mist, self.pump):
            out.off()
        self.leds.off()

    def close(self):
        self.off()
        if GPIO is not None:
            GPIO.cleanup()
