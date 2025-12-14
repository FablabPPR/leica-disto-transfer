# Leica DISTO D1/D110 BLE Reader

Python application to connect to a Leica DISTO D1/D110 laser distance meter via Bluetooth Low Energy (BLE) and retrieve distance measurements.

## Features

- ✅ Automatic BLE connection to DISTO distance meter
- ✅ Smart timer mode: automatic measurement 1 second after button press (for stabilization)
- ✅ Automatic laser activation for aiming during delay
- ✅ Auto-type: automatic input of measurements into spreadsheets
- ✅ Configurable delay
- ✅ Support for different units (m, ft, in, mm, yd, etc.)
- ✅ Active mode to trigger measurements from PC

## Requirements

### System
- Python 3.7+
- Linux with Bluetooth LE (BlueZ)
- Bluetooth enabled

### Python Dependencies
```bash
pip install -r requirements.txt
```

Or with a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### For Auto-Type (Optional)
The auto-type feature uses `pynput` for keyboard simulation. It works out of the box on most systems.

**Compatibility:**
- ✅ Works perfectly on X11 systems
- ✅ Works with XWayland apps (VS Code, many Electron apps)
- ⚠️  Limited support for Wayland native apps (LibreOffice, Chromium under Wayland)

**Note:** If you need full Wayland native support, consider using X11 mode for your desktop environment.

## Installation

```bash
# Clone or download the project
git clone <repo-url>
cd leica

# Install dependencies
pip install -r requirements.txt

# Make script executable (optional)
chmod +x disto_reader.py
```

## Usage

### Passive Mode (default)
Listens for measurements when you press the physical button on the distance meter:

```bash
python disto_reader.py
```

**Workflow:**
1. Script connects to DISTO
2. You press the button on the distance meter
3. Laser turns on automatically
4. After 1 second, an automatic measurement is taken
5. Result is displayed

### Auto-Type Mode (for spreadsheets)
Measurements are automatically typed into the active application:

```bash
python disto_reader.py --auto-type
```

**Usage with spreadsheets:**
1. Open your spreadsheet (LibreOffice Calc, Excel, Google Sheets...)
2. Click on the first cell
3. Launch the script with `--auto-type`
4. Switch back to spreadsheet (Alt+Tab)
5. Take your measurements!

Each measurement will be automatically typed and validated with Enter.

### Custom Delay
Adjust the delay before the final measurement:

```bash
python disto_reader.py --delay 2.0    # 2 seconds
python disto_reader.py -d 0.5         # 0.5 second
```

### Decimal Separator
Choose between dot or comma for decimal separator:

```bash
python disto_reader.py --separator .    # 1.234 (default)
python disto_reader.py --separator ,    # 1,234 (European format)
python disto_reader.py -s ,             # Short form
```

Useful for European locales where comma is the standard decimal separator.

### Active Mode
Trigger measurements from PC (interactive interface):

```bash
python disto_reader.py --active
```

Available commands:
- `m` : Measure distance
- `a` : Measure distance + angle
- `l` : Turn laser on
- `o` : Turn laser off
- `q` : Quit

### Full Help

```bash
python disto_reader.py --help
```

## Examples

### Simple measurements
```bash
# Standard passive mode (1s)
python disto_reader.py

# More time to aim (3s)
python disto_reader.py --delay 3
```

### Fill a spreadsheet
```bash
# Auto-type with 2s delay
python disto_reader.py --auto-type --delay 2

# Auto-type with comma separator (European format)
python disto_reader.py -t -s ,

# Combine all options: auto-type, 2s delay, comma separator
python disto_reader.py -t -d 2 -s ,
```

### Control from PC
```bash
python disto_reader.py --active
```

## Data Format

### Measurements
- **Format**: Number with 3 decimals (e.g., `1.234` or `1,234`)
- **Supported units**: m, ft, in, mm, yd, ft+in
- **Decimal separator**: Configurable via `--separator` (dot or comma)

### Auto-type
- **Typed format**: `X.XXX` or `X,XXX` (no unit, based on separator setting)
- **Default separator**: Decimal point `.` (use `-s ,` for comma)
- **Validation**: Automatic Enter key press

## BLE Protocol

The script implements Leica's proprietary BLE protocol:

- **Service UUID**: `3ab10100-f831-4395-b29d-570977d5bf94`
- **Characteristics**:
  - Distance: `3ab10101-...` (Float 4 bytes, Little Endian)
  - Unit: `3ab10102-...` (Integer 1 byte)
  - Command: `3ab10109-...` (ASCII strings)

For more details, see `CLAUDE.md`.

## Troubleshooting

### Device not found
- Check that DISTO is powered on
- Check that Bluetooth is enabled: `bluetoothctl power on`
- Make sure DISTO is not connected to another device
- Try with sudo (may fix some permission issues)

### Auto-type doesn't work

**Check your environment:**
```bash
echo $XDG_SESSION_TYPE  # x11 or wayland
```

#### On X11
Auto-type should work perfectly. ✅

#### On Wayland
- **XWayland apps**: Auto-type works normally (VS Code, many Electron apps, older applications)
- **Wayland native apps**: Limited support - may not work in LibreOffice, Chromium, etc.

**Solutions for Wayland:**
1. **Use X11 mode** (recommended if you need full auto-type support):
   ```bash
   # Log out and select "GNOME on Xorg" or "KDE Plasma (X11)" at login screen
   ```

2. **Use XWayland apps** when possible (many apps use XWayland by default)

3. **Manual entry**: If auto-type doesn't work, measurements are still displayed on screen for manual entry

### Bluetooth permission errors

```bash
# Option 1: Run with sudo (temporary)
sudo python disto_reader.py

# Option 2: Add user to bluetooth group (permanent)
sudo usermod -aG bluetooth $USER
# Then logout and login
```

### Timeout or missing measurements
- Increase delay: `--delay 2`
- Check distance between PC and DISTO (Bluetooth range ~10m)
- Avoid metal obstacles between them

## Architecture

```
disto_reader.py
├── BLE Scan (DISTO discovery)
├── GATT Connection
├── Notification setup (critical timing: 950ms + 100ms)
├── Passive Mode (automatic timer)
│   ├── Button press detection → Measurement ignored
│   ├── Immediate laser activation
│   ├── Configurable wait (default: 1s)
│   └── Automatic measurement → Display + auto-type
└── Active Mode (manual commands)
    └── Interactive interface
```

## Contributing

This project was developed by analyzing the official Leica DISTO Android APK through decompilation (jadx).

## License

Personal and educational use.

## Authors

Developed with assistance from Claude (Anthropic) by analyzing the BLE protocol from the official Android application.

## References

- [CLAUDE.md](CLAUDE.md) - Detailed BLE protocol documentation
- Official Android app: `leica.disto.transferBLE` (version 1.20)
- Protocol: BLE GATT with Leica proprietary service
