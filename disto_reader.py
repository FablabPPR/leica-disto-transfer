#!/usr/bin/env python3
"""
Leica DISTO D1/D110 BLE Reader
Simple script to connect to a Leica DISTO device and display distance measurements.

Requirements:
    pip install bleak

Usage:
    python disto_reader.py              # Passive mode (listen to button presses)
    python disto_reader.py --active     # Active mode (trigger measurements from PC)
"""

import argparse
import asyncio
import struct
import sys
import time
from bleak import BleakScanner, BleakClient

# For keyboard automation - using pynput for simplicity and keyboard layout compatibility
try:
    from pynput.keyboard import Controller, Key
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False
    print("⚠️  Warning: pynput not available, auto-type won't work")
    print("   Install with: pip install pynput")


# UUIDs from decompiled Android app
DISTO_SERVICE_UUID = "3ab10100-f831-4395-b29d-570977d5bf94"
DISTANCE_CHAR_UUID = "3ab10101-f831-4395-b29d-570977d5bf94"
DISTANCE_UNIT_CHAR_UUID = "3ab10102-f831-4395-b29d-570977d5bf94"
COMMAND_CHAR_UUID = "3ab10109-f831-4395-b29d-570977d5bf94"

# Unit code mappings
DISTANCE_UNITS = {
    0: "m",
    1: "ft",
    2: "in",
    3: "mm",
    4: "mm",
    5: "mm",
    6: "yd",
    7: "ft+in",
    8: "ft+in",
    9: "ft+in",
}

# Global state
current_distance = None
current_unit = 0
ble_client = None  # BLE client for sending commands from notification handler
timer_mode = False  # If True, first measurement triggers a delayed second measurement
waiting_for_final_measurement = False  # Flag to know if we're waiting for the final measurement
measurement_counter = 0  # Counter to track measurement cycles
expected_cycle_id = None  # ID of the cycle we're expecting a final measurement from
measurement_in_progress = False  # Flag to prevent overlapping measurements
measurement_delay = 1.0  # Delay in seconds before taking the final measurement
auto_type = False  # If True, automatically type measurements to active window
keyboard_controller = Controller() if PYNPUT_AVAILABLE else None  # Keyboard controller for auto-type
decimal_separator = ','  # Decimal separator for formatted output ('.' or ',')


def parse_distance(data: bytes) -> float:
    """
    Parse distance value from BLE characteristic.

    Format: 4-byte IEEE 754 float, Little Endian

    Args:
        data: Raw bytes from DISTANCE characteristic

    Returns:
        Distance value as float
    """
    if len(data) != 4:
        print(f"Warning: Expected 4 bytes, got {len(data)}")
        return 0.0

    # Unpack as Little Endian float
    distance = struct.unpack('<f', data)[0]
    return distance


def parse_unit(data: bytes) -> int:
    """
    Parse unit code from BLE characteristic.

    Format: 1-byte integer

    Args:
        data: Raw bytes from DISTANCE_UNIT characteristic

    Returns:
        Unit code as integer
    """
    if len(data) < 1:
        print(f"Warning: Expected at least 1 byte, got {len(data)}")
        return 0

    return data[0]


def type_measurement(distance: float):
    """
    Type the measurement value into the active window and press Enter.
    Uses pynput for simple, keyboard layout-independent typing.

    Args:
        distance: Distance value to type (without unit)
    """
    if not auto_type or not keyboard_controller:
        return

    # Format with configured decimal separator
    value_str = f"{distance:.3f}"
    value_str = value_str.replace('.', decimal_separator)

    try:
        # Small delay to ensure the window is ready
        time.sleep(0.2)

        # Type the measurement value
        keyboard_controller.type(value_str)

        # Press Enter
        keyboard_controller.press(Key.enter)
        keyboard_controller.release(Key.enter)

        print(f"✅ Typing complete")
    except Exception as e:
        print(f"❌ Typing error: {e}")


def distance_notification_handler(sender, data: bytearray):
    """
    Handle distance value notifications from the device.

    Called when the DISTANCE characteristic sends a notification
    (i.e., when the physical button on the device is pressed).

    In timer mode:
    - First measurement (from button press) is ignored and triggers a delayed measurement
    - Second measurement (after 1s delay) is displayed
    """
    global current_distance, waiting_for_final_measurement, ble_client, measurement_counter
    global expected_cycle_id, measurement_in_progress

    distance = parse_distance(bytes(data))
    current_distance = distance
    unit_str = DISTANCE_UNITS.get(current_unit, f"unknown({current_unit})")

    # Format distance with configured decimal separator
    distance_str = f"{distance:.3f}"
    distance_str = distance_str.replace('.', decimal_separator)

    if timer_mode:
        if waiting_for_final_measurement and expected_cycle_id is not None:
            # This is the final measurement after the delay - display it
            print(f"✓ Final measurement: {distance_str} {unit_str}\n")

            # Type the measurement if auto-type is enabled
            type_measurement(distance)

            waiting_for_final_measurement = False
            measurement_in_progress = False
            expected_cycle_id = None
        elif not measurement_in_progress:
            # This is the initial measurement from button press - start new cycle
            # Only accept if no measurement is currently in progress
            measurement_counter += 1
            measurement_in_progress = True
            expected_cycle_id = measurement_counter

            delay_text = f"{measurement_delay:.1f} second" if measurement_delay == 1.0 else f"{measurement_delay:.1f} seconds"
            print(f"⏱️  Button detected (measurement: {distance_str} {unit_str}) - measuring in {delay_text}...")
            waiting_for_final_measurement = True

            # Schedule the delayed measurement
            asyncio.create_task(delayed_measurement(measurement_counter))
        # else: Ignore this notification - a measurement is already in progress
    else:
        # Normal mode - just display the measurement
        print(f"📏 Distance: {distance_str} {unit_str}\n")


def unit_notification_handler(sender, data: bytearray):
    """
    Handle distance unit notifications from the device.

    Called when the DISTANCE_UNIT characteristic sends a notification.
    """
    global current_unit

    unit = parse_unit(bytes(data))
    current_unit = unit


async def send_command(client: BleakClient, command: str):
    """
    Send a command to the DISTO device.

    Commands are sent as ASCII strings to the COMMAND characteristic.

    Available commands:
        "g"  - Measure distance
        "gi" - Measure distance + angle
        "iv" - Measure angle only
        "o"  - Laser on
        "p"  - Laser off

    Args:
        client: Connected BleakClient
        command: Command string to send
    """
    try:
        await client.write_gatt_char(COMMAND_CHAR_UUID, command.encode('ascii'))
    except Exception as e:
        print(f"⚠️  Error sending command: {e}")


async def delayed_measurement(cycle_id):
    """
    Turn on laser, wait configured delay, then trigger a measurement.

    Called automatically when timer mode is enabled and a button press is detected.

    Args:
        cycle_id: Measurement cycle identifier
    """
    global ble_client, waiting_for_final_measurement, expected_cycle_id, measurement_in_progress

    if ble_client:
        # Turn on laser immediately so user can aim
        await send_command(ble_client, "o")
        print(f"🔴 Laser activated - aim at target...")
    else:
        print(f"❌ Error: connection lost")
        measurement_in_progress = False
        expected_cycle_id = None
        return

    await asyncio.sleep(measurement_delay)

    # Check if this cycle is still the expected one (might have been cancelled)
    if expected_cycle_id != cycle_id:
        return

    if ble_client:
        print(f"📡 Measuring...")
        await send_command(ble_client, "g")

        # Timeout safety: reset state if no measurement arrives within 3 seconds
        await asyncio.sleep(3.0)
        if waiting_for_final_measurement and expected_cycle_id == cycle_id:
            print(f"⚠️  Timeout - no measurement received, resetting...")
            waiting_for_final_measurement = False
            measurement_in_progress = False
            expected_cycle_id = None
    else:
        print(f"❌ Error: connection lost")
        measurement_in_progress = False
        expected_cycle_id = None


async def find_disto_device():
    """
    Scan for BLE devices and find the DISTO device.

    Filters for devices with "disto", "stabila", or "wdm" in their name
    (case-insensitive).

    Returns:
        BLEDevice object if found, None otherwise
    """
    print("🔍 Scanning for DISTO device...")

    devices = await BleakScanner.discover(timeout=10.0)

    for device in devices:
        if device.name:
            name_lower = device.name.lower()
            if "disto" in name_lower or "stabila" in name_lower or "wdm" in name_lower:
                print(f"✓ Found device: {device.name} ({device.address})")
                return device

    return None


async def connect_and_listen(device, active_mode=False):
    """
    Connect to the DISTO device and listen for measurements.

    Implements the critical timing sequence discovered in the decompiled code:
    1. Connect and discover services
    2. Wait 950ms
    3. Enable indications on DISTANCE characteristic
    4. Wait 100ms
    5. Enable indications on DISTANCE_UNIT characteristic
    6. Listen for notifications

    Args:
        device: BLEDevice object to connect to
        active_mode: If True, allows triggering measurements from PC
    """
    global ble_client, timer_mode, measurement_in_progress, expected_cycle_id

    async with BleakClient(device.address) as client:
        ble_client = client  # Store client for use in notification handler

        # Enable timer mode only in passive mode
        timer_mode = not active_mode
        measurement_in_progress = False
        expected_cycle_id = None

        print(f"✓ Connected to {device.name}")

        # Check if DISTO service is available
        services = client.services
        if DISTO_SERVICE_UUID.lower() not in [s.uuid.lower() for s in services]:
            print(f"❌ Error: DISTO service {DISTO_SERVICE_UUID} not found!")
            print("Available services:")
            for service in services:
                print(f"  - {service.uuid}")
            return

        print(f"✓ Found DISTO service")

        # CRITICAL: Wait 950ms before enabling notifications
        # This timing is required by the device protocol
        print("⏳ Waiting 950ms (device protocol requirement)...")
        await asyncio.sleep(0.95)

        # Enable indications on DISTANCE characteristic
        print(f"✓ Enabling notifications on DISTANCE characteristic...")
        await client.start_notify(DISTANCE_CHAR_UUID, distance_notification_handler)

        # CRITICAL: Wait 100ms between characteristic notifications
        print("⏳ Waiting 100ms...")
        await asyncio.sleep(0.1)

        # Enable indications on DISTANCE_UNIT characteristic
        print(f"✓ Enabling notifications on DISTANCE_UNIT characteristic...")
        await client.start_notify(DISTANCE_UNIT_CHAR_UUID, unit_notification_handler)

        print("\n" + "="*60)
        if active_mode:
            print("✓ Ready! Commands:")
            print("  m  - Measure distance")
            print("  a  - Measure distance + angle")
            print("  l  - Laser on")
            print("  o  - Laser off")
            print("  q  - Quit")
        else:
            print("✓ Ready! Press the button on the DISTO device to measure.")
            print("  Timer mode enabled: automatic measurement 1s after button press")
            print("  Press Ctrl+C to exit.")
        print("="*60 + "\n")

        # Keep the connection alive and listen for notifications
        try:
            if active_mode:
                # Interactive mode
                loop = asyncio.get_event_loop()
                while True:
                    # Read user input in a non-blocking way
                    user_input = await loop.run_in_executor(None, input, "Command: ")
                    user_input = user_input.strip().lower()

                    if user_input == 'q':
                        break
                    elif user_input == 'm':
                        print("📡 Sending measure command...")
                        await send_command(client, "g")
                    elif user_input == 'a':
                        print("📡 Sending measure distance+angle command...")
                        await send_command(client, "gi")
                    elif user_input == 'l':
                        print("📡 Turning laser on...")
                        await send_command(client, "o")
                    elif user_input == 'o':
                        print("📡 Turning laser off...")
                        await send_command(client, "p")
                    else:
                        print("⚠️  Unknown command. Use: m, a, l, o, or q")
            else:
                # Passive mode - just wait for button presses
                while True:
                    await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n\n👋 Disconnecting...")

        # Clean up global state
        ble_client = None
        timer_mode = False
        measurement_in_progress = False
        expected_cycle_id = None


async def main(active_mode=False, delay=1.0, enable_auto_type=False, separator='.'):
    """Main entry point."""
    global measurement_delay, auto_type, decimal_separator
    measurement_delay = delay
    auto_type = enable_auto_type
    decimal_separator = separator

    print("="*60)
    print("Leica DISTO D1/D110 BLE Reader")
    if active_mode:
        print("Mode: Active (trigger from PC)")
    else:
        print(f"Mode: Passive (listen to button, delay: {delay}s)")
    if auto_type:
        print("Auto-type: ENABLED - measurements will be typed automatically")
    print("="*60 + "\n")

    # Find the device
    device = await find_disto_device()

    if device is None:
        print("\n❌ No DISTO device found!")
        print("   Make sure the device is powered on and in range.")
        return 1

    # Connect and listen
    try:
        await connect_and_listen(device, active_mode=active_mode)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Leica DISTO D1/D110 BLE Reader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python disto_reader.py                          Listen to button presses (1s delay)
  python disto_reader.py --delay 2.0              Listen with 2 second delay
  python disto_reader.py --auto-type              Auto-type measurements to spreadsheet
  python disto_reader.py --auto-type --delay 2    Auto-type with 2s delay
  python disto_reader.py -t -s ,                  Auto-type with comma separator (1,234)
  python disto_reader.py --active                 Trigger measurements from PC (active)
        """
    )
    parser.add_argument(
        '--active', '-a',
        action='store_true',
        help='Enable active mode to trigger measurements from PC'
    )
    parser.add_argument(
        '--delay', '-d',
        type=float,
        default=1.0,
        help='Delay in seconds before taking measurement (default: 1.0)'
    )
    parser.add_argument(
        '--auto-type', '-t',
        action='store_true',
        help='Automatically type measurements to active window (for spreadsheets)'
    )
    parser.add_argument(
        '--separator', '-s',
        type=str,
        choices=['.', ','],
        default=',',
        help='Decimal separator (default: , for "1.234", use , for "1,234")'
    )
    args = parser.parse_args()

    try:
        exit_code = asyncio.run(main(
            active_mode=args.active,
            delay=args.delay,
            enable_auto_type=args.auto_type,
            separator=args.separator
        ))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")
        sys.exit(0)
