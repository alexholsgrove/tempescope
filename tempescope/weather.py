"""Fetch current weather from OpenWeather and reduce it to what the display needs."""

import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

API_URL = "https://api.openweathermap.org/data/2.5/weather"


@dataclass
class Weather:
    condition: str      # clear | clouds | drizzle | rain | thunderstorm | snow | fog
    intensity: float    # 0..1, how heavy the rain/clouds/etc are
    wind: float         # m/s
    is_day: bool
    description: str = ""


def classify(code, clouds_pct):
    """Map an OpenWeather condition code to (condition, intensity).

    See https://openweathermap.org/weather-conditions
    """
    if 200 <= code < 300:
        return "thunderstorm", 1.0
    if 300 <= code < 400:
        return "drizzle", 0.3
    if 500 <= code < 600:
        # 500 light, 501 moderate, 502+ heavy; 52x showers
        return "rain", {500: 0.4, 501: 0.7}.get(code, 1.0)
    if 600 <= code < 700:
        return "snow", 0.8
    if 700 <= code < 800:
        return "fog", 1.0
    if code == 800:
        return "clear", 0.0
    return "clouds", max(0.2, clouds_pct / 100.0)


# Home Assistant weather entity states -> (condition, intensity)
# https://developers.home-assistant.io/docs/core/entity/weather/#recommended-values-for-state-and-condition
HA_CONDITIONS = {
    "sunny": ("clear", 0.0),
    "clear-night": ("clear", 0.0),
    "exceptional": ("clear", 0.0),
    "windy": ("clear", 0.0),
    "partlycloudy": ("clouds", 0.4),
    "windy-variant": ("clouds", 0.5),
    "cloudy": ("clouds", 0.9),
    "fog": ("fog", 1.0),
    "rainy": ("rain", 0.6),
    "pouring": ("rain", 1.0),
    "hail": ("rain", 1.0),
    "lightning": ("thunderstorm", 1.0),
    "lightning-rainy": ("thunderstorm", 1.0),
    "snowy": ("snow", 0.8),
    "snowy-rainy": ("snow", 0.8),
}

TO_MS = {"m/s": 1.0, "km/h": 1 / 3.6, "mph": 0.44704, "kn": 0.514444, "ft/s": 0.3048}


def _num(v):
    """Home Assistant states arrive as strings and may be 'unavailable'."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def from_homeassistant(data):
    """Build a Weather from the JSON the Home Assistant automation publishes:

    {"condition": "rainy",                 # forecast weather entity state
     "wind_speed": 12.3, "wind_gust": 20,  # live station values (optional gust)
     "wind_speed_unit": "km/h",
     "rain_rate": 1.2,                     # live station rain rate, mm/h (optional)
     "is_day": true}

    The forecast gives the overall picture (clouds, fog, snow, thunder). If a
    station rain rate is supplied it decides whether it is actually raining here.
    """
    ha = data.get("condition", "")
    condition, intensity = HA_CONDITIONS.get(ha, ("clear", 0.0))

    rain_rate = _num(data.get("rain_rate"))
    if rain_rate is not None and condition not in ("snow", "thunderstorm"):
        if rain_rate >= 0.5:
            # UK: light < 2 mm/h, moderate 2-10, heavy > 10
            condition, intensity = "rain", max(0.4, min(1.0, rain_rate / 10))
        elif rain_rate > 0:
            condition, intensity = "drizzle", 0.3
        elif condition in ("rain", "drizzle"):
            condition, intensity = "clouds", 0.9     # forecast rain, but dry here

    unit = data.get("wind_speed_unit") or "m/s"
    to_ms = TO_MS.get(unit, 1.0)
    speed = _num(data.get("wind_speed")) or 0.0
    gust = _num(data.get("wind_gust")) or 0.0
    # Instantaneous station wind is very jumpy; letting gusts count for a bit
    # keeps the fan from constantly stopping and starting.
    wind = max(speed, gust * 0.6) * to_ms
    is_day = data.get("is_day")
    if is_day is None:
        is_day = ha != "clear-night"
    w = Weather(condition, intensity, round(wind, 1), bool(is_day), ha)
    log.info("Weather from Home Assistant: %s", w)
    return w


def fetch(api_key, location, timeout=10):
    params = {"appid": api_key, "units": "metric"}
    if isinstance(location, dict):
        params.update(lat=location["lat"], lon=location["lon"])
    else:
        params["q"] = location
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        data = json.load(resp)

    code = data["weather"][0]["id"]
    condition, intensity = classify(code, data.get("clouds", {}).get("all", 0))
    now = time.time()
    sys = data.get("sys", {})
    is_day = sys.get("sunrise", 0) <= now <= sys.get("sunset", now + 1)
    w = Weather(
        condition=condition,
        intensity=intensity,
        wind=data.get("wind", {}).get("speed", 0.0),
        is_day=is_day,
        description=data["weather"][0].get("description", ""),
    )
    log.info("Weather: %s", w)
    return w
