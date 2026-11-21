# Tempescope

A desktop weather display based on Ken Kawamoto's
[Tempescope](https://kenkawamoto.com/projects/tempescope). It fetches the current
weather from OpenWeather and recreates it in a box: clouds from an ultrasonic mister,
rain from a water pump, wind from a fan, and sun or lightning from a NeoPixel ring.

## Hardware

| Part                    | BCM pin | Notes                          |
|-------------------------|---------|--------------------------------|
| Raspberry Pi Zero W     |         | Raspberry Pi OS Trixie 32-bit Lite |
| NeoPixel ring (12 LEDs) | 21      | PCM output, driven by rpi_ws281x |
| Fan                     | 24      | via MOSFET, software PWM        |
| Ultrasonic mister       | 17      | via MOSFET                      |
| Water pump              | 22      | via MOSFET                      |

## Setup (on the Pi)

```bash
git clone <this repo> ~/tempescope && cd ~/tempescope
bash setup.sh            # creates config.yml from config.example.yml
nano config.yml          # API key/location or MQTT details
```

## Running

```bash
sudo ./venv/bin/python -m tempescope                  # live weather
sudo ./venv/bin/python -m tempescope --demo           # cycle every effect
sudo ./venv/bin/python -m tempescope --condition rain # force one effect
```

`sudo` is needed because rpi_ws281x drives GPIO 21 through DMA. Use the venv's
Python by its full path, since plain `sudo python3` won't see the venv.

On a Mac the hardware is mocked, so you can run `python3 -m tempescope --demo`
to check the logic (needs `pip install pyyaml`).

To start on boot:

```bash
bash setup.sh --service
journalctl -u tempescope -f
```

## Home Assistant

The tempescope connects to the Mosquitto broker and appears automatically (MQTT
discovery) as a **Tempescope** device with:

- **Mode**: auto, off, or force any condition
- **Mist enabled / Pump enabled**: safety lockouts for an empty tank. These reset
  to the `disabled` list in `config.yml` whenever the tempescope restarts.
- **LED brightness**
- Sensors for the condition shown, wind, and fan/mist/pump levels

To set it up:

1. In Home Assistant, create a user for the tempescope (Settings > People > Users)
   and put its username/password in the `mqtt` section of `config.yml`.
2. Set `weather.source: homeassistant`.
3. Copy [homeassistant/automation.example.yaml](homeassistant/automation.example.yaml)
   to `homeassistant/automation.yaml`, swap in your entity IDs, and add it as an
   automation in Home Assistant. It sends a forecast weather entity plus (optionally)
   live rain rate and wind from a weather station. The forecast sets the overall
   picture (cloud, fog, snow, thunder) and the station decides whether it is
   actually raining here and how hard.

### Local files

`config.yml` and `homeassistant/automation.yaml` hold your own API key, passwords
and entity IDs, so they are git-ignored. Only the `*.example.*` versions are
committed: copy them and fill in your details.

## Hardware tests

```bash
./venv/bin/python tools/pwm_test.py fan     # or mist / pump
./venv/bin/python tools/fan_calibrate.py    # find fan_min / fan_kick
sudo ./venv/bin/python tools/strandtest.py -c
```

## Weather → effect

| Condition    | Mist          | Pump               | LEDs                   |
|--------------|---------------|--------------------|------------------------|
| clear        | off           | off                | warm sun (blue at night) |
| clouds       | scaled by cloud % | off            | grey                   |
| drizzle/rain | max           | scaled by intensity | blue                  |
| thunderstorm | max           | max                | dark + lightning       |
| snow / fog   | max           | off                | white / grey           |

The fan follows wind speed in every condition. Tune the levels in the `effects`
section of `config.yml`.
