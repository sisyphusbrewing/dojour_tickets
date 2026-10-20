#!/usr/bin/env bash
# One-time setup for the portable Stream Deck + (Raspberry Pi 4 + Waveshare UPS HAT (B) in the printed dock).
# The Pi runs Companion Satellite, so the deck shows the same pages as the bar deck, driven by Companion on
# the office PC over Wi-Fi. Flash "Raspberry Pi OS Lite (64-bit)" with Raspberry Pi Imager first, setting the
# hostname (portable-deck), Wi-Fi and SSH in its settings, then on the Pi run:
#   curl -sSL https://sisyphusbrewing.github.io/dojour_tickets/av/pi-satellite-setup.sh | sudo bash
# Safe to run again. What it does:
#   - installs Companion Satellite as a service pointed at Companion on the office PC
#   - turns off Wi-Fi power saving, so the deck doesn't lag or drop after sitting idle
#   - enables I2C and installs a battery watcher for the UPS HAT: shuts the Pi down cleanly when the
#     cells run low, and sends the battery % to Companion's custom variable "deck_battery" every minute
set -e

COMPANION_IP="${COMPANION_IP:-192.168.86.42}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run it with sudo: curl -sSL https://sisyphusbrewing.github.io/dojour_tickets/av/pi-satellite-setup.sh | sudo bash"
  exit 1
fi

echo "Companion Satellite"
if [ ! -d /opt/companion-satellite ]; then
  curl -sSL https://raw.githubusercontent.com/bitfocus/companion-satellite/main/pi-image/install.sh | bash
fi
# Satellite imports this file at startup (Bookworm keeps the boot partition at /boot/firmware)
boot=/boot/firmware; [ -d "$boot" ] || boot=/boot
printf 'COMPANION_IP=%s\nCOMPANION_PORT=16622\nREST_PORT=9999\n' "$COMPANION_IP" > "$boot/satellite-config"
systemctl enable satellite
systemctl restart satellite
echo "  points at Companion on $COMPANION_IP:16622"

echo "Wi-Fi"
cat > /etc/systemd/system/wifi-powersave-off.service <<'UNIT'
[Unit]
Description=Keep Wi-Fi awake for the Stream Deck
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/sbin/iw dev wlan0 set power_save off

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now wifi-powersave-off.service
echo "  power saving off"

echo "Battery"
raspi-config nonint do_i2c 0
apt-get install -yq python3-smbus i2c-tools >/dev/null
cat > /usr/local/bin/deck-battery <<'PY'
#!/usr/bin/env python3
# Waveshare UPS HAT (B): INA219 at 0x42 reads the 2-cell pack (6.0 V empty, 8.4 V full)
import os, sys, time, urllib.request
import smbus

COMPANION = sys.argv[1]
SHUTDOWN_VOLTS = 6.3  # about 10% left; stops before the HAT cuts power mid-write
bus = smbus.SMBus(1)
low = 0
while True:
    try:
        raw = bus.read_word_data(0x42, 0x02)
        raw = ((raw & 0xFF) << 8) | (raw >> 8)  # INA219 sends big-endian
        volts = (raw >> 3) * 0.004
        pct = max(0, min(100, round((volts - 6.0) / 2.4 * 100)))
        low = low + 1 if volts < SHUTDOWN_VOLTS else 0
        if low >= 3:  # three low readings in a row, not a blip
            os.system("shutdown -h now")
        urllib.request.urlopen(urllib.request.Request(
            f"http://{COMPANION}:8000/api/custom-variable/deck_battery/value?value={pct}", method="POST"), timeout=5)
    except Exception:
        pass  # Wi-Fi gap or Companion closed; try again next minute
    time.sleep(60)
PY
chmod +x /usr/local/bin/deck-battery
cat > /etc/systemd/system/deck-battery.service <<UNIT
[Unit]
Description=Portable deck battery watcher
After=network-online.target

[Service]
ExecStart=/usr/local/bin/deck-battery $COMPANION_IP
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now deck-battery.service
if i2cdetect -y 1 | grep -q ' 42'; then echo "  UPS HAT found"; else echo "  UPS HAT not seen yet; reboot once after I2C is enabled"; fi

echo ""
echo "Done. Plug in the Stream Deck +; it appears under Surfaces in Companion (http://$COMPANION_IP:8000)."
