import configparser
import multiprocessing
import time
import sys
from pathlib import Path

import tango
from tango.test_context import DeviceTestContext

from PrintDevice import PrintDevice


HOST = "127.0.0.1"
PORT = 8888
DEVICE = f"tango://{HOST}:{PORT}/test/nodb/printdevice#dbase=no"

DEFAULT_PRINTER_PORT = "COM3"
DEFAULT_PRINTER_BAUDRATE = 115200
DEFAULT_TESTRUN_FEEDRATE = 1500  # mm/min; the measurement itself runs at 500


def get_base_path() -> Path:
    """Folder the config file lives in: next to the .exe when frozen,
    next to this script otherwise."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_printer_config() -> tuple[str, int, int]:
    """Read printer_port/printer_baudrate from config.ini next to the
    executable. Creates the file with defaults on first run so it's there
    to edit, and falls back to the defaults if the file is missing or a
    value in it can't be parsed."""
    config_path = get_base_path() / "config.ini"
    parser = configparser.ConfigParser()

    if not config_path.exists():
        parser["printer"] = {
            "port": DEFAULT_PRINTER_PORT,
            "baudrate": str(DEFAULT_PRINTER_BAUDRATE),
            "testrun_feedrate": str(DEFAULT_TESTRUN_FEEDRATE),
        }
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("# Printer connection settings.\n")
            f.write("# 'port' is the COM port Windows assigned the printer (see Device Manager).\n")
            f.write("# 'testrun_feedrate' is the test run speed in mm/min (measurement: 500).\n")
            parser.write(f)
        print(f"Created default config file at {config_path}")

    printer_port = DEFAULT_PRINTER_PORT
    printer_baudrate = DEFAULT_PRINTER_BAUDRATE
    testrun_feedrate = DEFAULT_TESTRUN_FEEDRATE

    try:
        parser.read(config_path, encoding="utf-8")
        printer_port = parser.get("printer", "port", fallback=DEFAULT_PRINTER_PORT).strip()
        printer_baudrate = parser.getint("printer", "baudrate", fallback=DEFAULT_PRINTER_BAUDRATE)
        testrun_feedrate = parser.getint("printer", "testrun_feedrate", fallback=DEFAULT_TESTRUN_FEEDRATE)
    except (configparser.Error, ValueError) as e:
        print(f"WARNING: Could not read {config_path} ({e}); using defaults "
              f"({DEFAULT_PRINTER_PORT}, {DEFAULT_PRINTER_BAUDRATE}, F{DEFAULT_TESTRUN_FEEDRATE}).")

    print(f"Using printer port {printer_port} at {printer_baudrate} baud, "
          f"test run F{testrun_feedrate} (from {config_path})")
    return printer_port, printer_baudrate, testrun_feedrate


def main():
    print("========================================")
    print("   Starting Teslameter / Tango Server")
    print("========================================")

    # --------------------------------------------------
    # 1. Start the Tango test server (in this process)
    # --------------------------------------------------
    # Note: `sys.executable -m tango.test_context ...` only works with a
    # real Python interpreter. In a PyInstaller-built .exe, sys.executable
    # is the .exe itself, which does not understand "-m" - it would just
    # keep relaunching the .exe. That's why the test server runs directly
    # in this process (in a background thread) instead.
    print("\n[1/3] Starting Tango test server...")

    printer_port, printer_baudrate, testrun_feedrate = load_printer_config()
    context = DeviceTestContext(
        PrintDevice,
        host=HOST,
        port=PORT,
        timeout=60,
        properties={
            "printer_port": printer_port,
            "printer_baudrate": printer_baudrate,
            "testrun_feedrate": testrun_feedrate,
        },
    )

    try:
        context.start()
    except Exception as e:
        print("\nERROR: Tango server could not be started.")
        print(e)
        sys.exit(1)

    print("Tango server started.")

    # --------------------------------------------------
    # 2. Check the connection
    # --------------------------------------------------
    print("\n[2/3] Checking Tango server...")

    dp = context.device
    dp.set_timeout_millis(600000)  # 10 minutes

    try:
        dp.ping()
        print("Tango server is reachable.")
    except Exception:
        print("\nERROR: Tango server could not be reached.")
        context.stop()
        sys.exit(1)

    # --------------------------------------------------
    # 3. Start the Heatmap
    # --------------------------------------------------
    print("\n[3/3] Starting Heatmap...")

    try:
        dp.start_Heatmap()
        print("Heatmap started.")

    except Exception as e:
        print("\nERROR while starting the Heatmap:")
        print(e)

        context.stop()
        sys.exit(1)

    # --------------------------------------------------
    # Keep the server running
    # --------------------------------------------------
    print("\n========================================")
    print("   Teslameter system is running")
    print("========================================")
    print("Tango Device:")
    print(DEVICE)
    print("\nPress CTRL+C to stop")
    print("")

    try:
        while True:
            # Check whether the Tango server thread is still running
            if not context.thread.is_alive():
                print("\nTango server has stopped.")
                break

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\nStopping system...")

    finally:
        # Shut down the Tango server cleanly
        if context.thread.is_alive():
            print("Stopping Tango server...")
            context.stop()

        print("System stopped.")


if __name__ == "__main__":
    # Must be the very first thing: prevents multiprocessing.Process
    # children started by Heatmap/GUI from re-running the whole program
    # in a frozen (PyInstaller) .exe.
    multiprocessing.freeze_support()
    main()
