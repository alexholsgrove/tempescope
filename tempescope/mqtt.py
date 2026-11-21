"""Home Assistant integration over MQTT, using MQTT discovery.

The tempescope appears in Home Assistant as one device with a mode selector,
mist/pump enable switches, an LED brightness control and status sensors.
Incoming commands are put on a queue and handled by the main loop, so all
hardware access stays on one thread.
"""

import json
import logging

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

log = logging.getLogger(__name__)

MODES = ["auto", "off", "clear", "clouds", "drizzle", "rain", "thunderstorm", "snow", "fog"]


class HomeAssistantMQTT:
    def __init__(self, cfg, commands):
        if mqtt is None:
            raise RuntimeError("paho-mqtt is not installed (apt install python3-paho-mqtt)")
        self.base = cfg.get("topic", "tempescope")
        self.prefix = cfg.get("discovery_prefix", "homeassistant")
        self.commands = commands

        if hasattr(mqtt, "CallbackAPIVersion"):          # paho-mqtt 2.x
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.base)
        else:                                            # paho-mqtt 1.x
            self.client = mqtt.Client(client_id=self.base)
        if cfg.get("username"):
            self.client.username_pw_set(cfg["username"], cfg.get("password"))
        self.client.will_set(f"{self.base}/status", "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = lambda *a: log.warning("MQTT disconnected")
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 60)
        self.client.connect_async(cfg["host"], cfg.get("port", 1883))
        self.client.loop_start()

    # -- discovery -------------------------------------------------------

    def discovery_payload(self):
        b = self.base
        state = f"{b}/state"

        def sensor(key, name, **extra):
            return {"p": "sensor", "name": name, "unique_id": f"{b}_{key}",
                    "stat_t": state, "val_tpl": f"{{{{ value_json.{key} }}}}", **extra}

        def switch(key, name, icon):
            return {"p": "switch", "name": name, "unique_id": f"{b}_{key}", "icon": icon,
                    "cmd_t": f"{b}/{key}/set", "stat_t": state,
                    "val_tpl": f"{{{{ value_json.{key} }}}}"}

        return {
            "dev": {"ids": [b], "name": "Tempescope", "mf": "DIY", "mdl": "Tempescope (Pi Zero W)"},
            "o": {"name": "tempescope", "sw": "1.0"},
            "avty_t": f"{b}/status",
            "cmps": {
                "mode": {"p": "select", "name": "Mode", "unique_id": f"{b}_mode",
                         "icon": "mdi:weather-partly-rainy", "options": MODES,
                         "cmd_t": f"{b}/mode/set", "stat_t": state,
                         "val_tpl": "{{ value_json.mode }}"},
                "mist_enabled": switch("mist_enabled", "Mist enabled", "mdi:weather-fog"),
                "pump_enabled": switch("pump_enabled", "Pump enabled", "mdi:water-pump"),
                "brightness": {"p": "number", "name": "LED brightness", "unique_id": f"{b}_brightness",
                               "icon": "mdi:brightness-6", "min": 0, "max": 255, "step": 1,
                               "cmd_t": f"{b}/brightness/set", "stat_t": state,
                               "val_tpl": "{{ value_json.brightness }}"},
                "condition": sensor("condition", "Showing", icon="mdi:weather-cloudy"),
                "wind": sensor("wind", "Wind", dev_cla="wind_speed", unit_of_meas="m/s",
                               stat_cla="measurement"),
                "fan": sensor("fan", "Fan", unit_of_meas="%", icon="mdi:fan", stat_cla="measurement"),
                "mist": sensor("mist", "Mist", unit_of_meas="%", icon="mdi:weather-fog", stat_cla="measurement"),
                "pump": sensor("pump", "Pump", unit_of_meas="%", icon="mdi:water-pump", stat_cla="measurement"),
            },
        }

    def publish_discovery(self):
        topic = f"{self.prefix}/device/{self.base}/config"
        self.client.publish(topic, json.dumps(self.discovery_payload()), retain=True)

    # -- callbacks (run on the paho thread) -------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, *args):
        if getattr(reason_code, "is_failure", False) or (isinstance(reason_code, int) and reason_code):
            log.error("MQTT connection refused: %s (check username/password)", reason_code)
            return
        log.info("MQTT connected")
        self.publish_discovery()
        client.publish(f"{self.base}/status", "online", retain=True)
        client.subscribe(f"{self.base}/+/set")
        client.subscribe(f"{self.prefix}/status")       # HA restarts -> re-announce
        self.commands.put(("republish", None))

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode(errors="replace").strip()
        if msg.topic == f"{self.prefix}/status":
            if payload == "online":
                self.publish_discovery()
                self.commands.put(("republish", None))
            return
        parts = msg.topic.split("/")
        if len(parts) == 3 and parts[0] == self.base and parts[2] == "set":
            self.commands.put((parts[1], payload))

    # -- outgoing ---------------------------------------------------------

    def publish_state(self, state):
        self.client.publish(f"{self.base}/state", json.dumps(state), retain=True)

    def close(self):
        try:
            self.client.publish(f"{self.base}/status", "offline", retain=True).wait_for_publish(2)
        except (RuntimeError, ValueError):
            pass   # not connected: the broker's last-will marks us offline anyway
        self.client.disconnect()
        self.client.loop_stop()
