#!/bin/bash
# Sets up a Raspberry Pi to run the front bar chalkboard (sign.py) from power-up.
# Run once on a fresh Raspberry Pi OS Lite, on the sign's Pi:
#   curl -fsSL https://staff.sisyphusbrewing.com/sign/pi/install.sh | sudo bash
# For Adafruit's RGB Matrix Bonnet or HAT, add: sudo SIGN_WIRING=adafruit-hat bash
# (Sam chose the Pi route on Nov 11 2026; see sign.py for why.)
set -euo pipefail

SITE=https://staff.sisyphusbrewing.com/sign/pi
DIR=/opt/sisyphus-sign
WIRING=${SIGN_WIRING:-regular}

echo "== packages"
apt-get update -q
apt-get install -y -q git build-essential cmake python3-dev python3-pip python3-pil python3-requests cython3

echo "== panel library (rpi-rgb-led-matrix)"
if [ ! -d /opt/rpi-rgb-led-matrix ]; then
  git clone --depth 1 https://github.com/hzeller/rpi-rgb-led-matrix /opt/rpi-rgb-led-matrix
fi
cd /opt/rpi-rgb-led-matrix
# The library's own instructions: "pip install ." from its top folder. Raspberry
# Pi OS wants the extra flag before pip may install system-wide.
pip3 install --break-system-packages .
python3 -c "import rgbmatrix" && echo "panel library OK"

echo "== sign program"
mkdir -p "$DIR/fonts"
for f in sign.py fonts/6x10.bdf fonts/9x18B.bdf; do
  curl -fsSL "$SITE/$f" -o "$DIR/$f"
done

# The panel library needs a whole processor core to itself and no sound card
# (the sound chip shares the timer it uses), or the panels flicker.
if ! grep -q isolcpus=3 /boot/firmware/cmdline.txt 2>/dev/null; then
  sed -i '1 s/$/ isolcpus=3/' /boot/firmware/cmdline.txt
fi
echo "blacklist snd_bcm2835" > /etc/modprobe.d/blacklist-rgb-matrix.conf
sed -i 's/^dtparam=audio=on/dtparam=audio=off/' /boot/firmware/config.txt || true

# Speed and colour depth are picked by sign.py to suit the Pi model; add
# SIGN_SLOWDOWN= or SIGN_PWM_BITS= lines here to override them.
cat > /etc/sisyphus-sign.env <<EOF
SIGN_WIRING=$WIRING
EOF

cat > /etc/systemd/system/sisyphus-sign.service <<EOF
[Unit]
Description=Sisyphus front bar chalkboard
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=/etc/sisyphus-sign.env
ExecStart=/usr/bin/python3 $DIR/sign.py
Restart=always
RestartSec=2
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable sisyphus-sign.service
echo "== done. Reboot (sudo reboot) and the sign starts by itself."
