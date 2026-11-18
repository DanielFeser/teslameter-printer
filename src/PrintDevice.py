import random
import threading
from tango import AttrWriteType
from tango.server import Device, attribute, command, device_property
import time
import re
from printrun.printcore import printcore
import ctypes as C
from multiprocessing import Process, Queue
import teslameter_gui
import Heatmap
import teslameterTest as tm
import numpy as np

STATUS_MEASUREMENT_STARTED  = "MEASUREMENT_STARTED"
STATUS_MEASUREMENT_FINISHED = "MEASUREMENT_FINISHED"
STATUS_MEASUREMENT_ABORTED  = "MEASUREMENT_ABORTED"
STATUS_WAIT_DUMMY_INSTALL   = "WAIT_DUMMY_INSTALL"
STATUS_TESTRUN_RUNNING      = "TESTRUN_RUNNING"
STATUS_TESTRUN_FINISHED     = "TESTRUN_FINISHED"
STATUS_TESTRUN_ABORTED      = "TESTRUN_ABORTED"
STATUS_WAIT_REAL_INSTALL    = "WAIT_REAL_INSTALL"
STATUS_READY_FOR_REALSCAN   = "READY_FOR_REALSCAN"
# Fixed start coordinates
FIXED_COORD = {"X": 0.0, "Y": 0.0, "Z": 30.0}
# Movement limits       
LIMITS = {
    "X": (-110, 100),
    "Y": (-110, 110),
    "Z": (0, 230)
}

# Feedrates in mm/min. The test run visits exactly the same points in the
# same order as the measurement; only the speed and the per-point pause
# differ. The test run speed is set via the testrun_feedrate property
# (config.ini).
SCAN_FEEDRATE = 500
TRAVEL_FEEDRATE = 1500        # moving to the start point / HOME
SETTLE_TIME = 1.0             # s to wait after arriving before reading the sensor
POSITION_TOLERANCE = 0.05     # mm, reported vs. commanded position


class RunAborted(Exception):
    """Raised inside a running test run / scan when ABORT was requested."""


class PrintDevice(Device):

    #host: str = device_property(mandatory=True)
    #location: str = device_property()
    printer_port: str = device_property(default_value="COM3")
    printer_baudrate: int = device_property(default_value=115200)
    testrun_feedrate: int = device_property(default_value=1500)

    def init_device(self):
        super().init_device()
        # Position tracking. Every M114 sent is counted (_pos_requests) and
        # every position report received is counted (_pos_reports), so a
        # waiter can tell whether the report it asked for has arrived.
        self._pos_cond = threading.Condition()
        self._pos_requests = 0
        self._pos_reports = 0

        self.data_queue = Queue()       # For live measurement data
        self.dim_queue = Queue()        # For sample dimensions
        self.command_queue = Queue()    # For commands from GUI
        self.status_queue  = Queue()    # For status updates to GUI

        # Cooperative cancellation for a running test run / scan. The
        # listener thread stays free to keep reading command_queue while
        # a scan runs in its own worker thread, so an "ABORT" command can
        # be handled immediately instead of waiting for the scan to finish.
        self.stop_event = threading.Event()
        self._active_worker = None

        self.listener_thread = threading.Thread(target=self.listen_to_gui_commands, daemon=True)
        self.listener_thread.start()

        self._sample_length =1
        self._sample_width =1
        self._sample_height =1
        self._sample_stepsize =1
        self._sample_distance =1
        self.current_position = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        self.port = self.printer_port
        self.baudrate = self.printer_baudrate
        self.p = printcore(self.port, self.baudrate)
        print("Connecting to printer...")
        timeout = 20  # seconds
        start = time.time()
        while not self.p.online:
            if time.time() - start > timeout:
                raise RuntimeError(
                    f"Printer did not respond on {self.port} within {timeout}s. "
                    "Check the USB/serial connection and the configured printer_port."
                )
            time.sleep(0.1)
        print("Connected.")
        self.p.recvcb = self.handle_response
        self.home_and_move_to_start()


        tm.A3mtslib.open_device(C.byref(tm.device_number))

    def handle_response(self, line):
        print("Received:", line)
        if "X:" in line:
            match = re.search(r"X:\s*(-?\d+\.?\d*)\s+Y:\s*(-?\d+\.?\d*)\s+Z:\s*(-?\d+\.?\d*)", line)
            if match:
                x, y, z = map(float, match.groups())
                with self._pos_cond:
                    self.current_position = {"X": x, "Y": y, "Z": z}
                    self._pos_reports += 1
                    self._pos_cond.notify_all()
                print(f"Updated position: {self.current_position}")

    def listen_to_gui_commands(self):
        while True:

            cmd, value = self.command_queue.get()

            if cmd == "HOME":
                print("GUI Command: Move home")
                # Worker thread, so ABORT stays possible during the travel.
                self._start_worker(self._home_worker)

            elif cmd == "RESCAN":
                print("GUI Command: Start new scan")
                self._start_worker(self.scan_volume)

            elif cmd == "START_TESTRUN":
                self._start_worker(self.run_testrun)

            elif cmd == "TESTRUN_OK":
                self.status_queue.put(("STATUS", STATUS_WAIT_REAL_INSTALL))

            elif cmd == "TESTRUN_CRASH":
                print("Test run marked as collision by user")

            elif cmd == "ABORT":
                print("GUI Command: Emergency stop requested")
                # Signal the running worker to stop at its next checkpoint,
                # and immediately fire the printer's emergency stop so any
                # motion in flight halts right away rather than waiting for
                # the worker loop to notice.
                self.stop_event.set()
                self._emergency_stop()

    def _emergency_stop(self):
        """Send M112 immediately. p.send() would put it at the end of
        printcore's queue, behind every command still waiting there, so
        drop the queued commands and write M112 straight to the port."""
        dropped = 0
        while True:
            try:
                self.p.priqueue.get_nowait()
                dropped += 1
            except Exception:
                break
        if dropped:
            print(f"Dropped {dropped} queued printer command(s).")
        try:
            self.p.printer.write(b"M112\n")
        except Exception as e:
            print(f"Direct M112 write failed ({e}); falling back to queue.")
            self.p.send_now("M112")
        # Wake up anything waiting for a position report.
        with self._pos_cond:
            self._pos_cond.notify_all()

    # ------------------------------------------------------------------
    # Motion helpers
    #
    # printcore.send() only queues a command and returns immediately, and
    # outside "print" mode printcore does not even wait for the printer's
    # "ok" before sending the next line. So M400 alone does not make
    # Python wait. Everything that has to wait for the head goes through
    # _wait_until_idle(), which waits for an M114 report sent after M400.
    # ------------------------------------------------------------------
    def _query_position(self):
        """Send M114 and return the number of the report to wait for."""
        with self._pos_cond:
            self._pos_requests += 1
            ticket = self._pos_requests
        self.p.send("M114")
        return ticket

    def _at(self, target):
        x, y, z = target
        pos = self.current_position
        return (abs(pos["X"] - x) <= POSITION_TOLERANCE and
                abs(pos["Y"] - y) <= POSITION_TOLERANCE and
                abs(pos["Z"] - z) <= POSITION_TOLERANCE)

    def _wait_until_idle(self, target=None, timeout=60.0):
        """Block until the printer has finished all queued moves and
        reported its position. With target=(x, y, z) in printer
        coordinates, also require the head to be at that position - this
        catches commands lost on the serial line."""
        self.p.send("M400")
        ticket = self._query_position()
        deadline = time.time() + timeout
        with self._pos_cond:
            while True:
                if self.stop_event.is_set():
                    raise RunAborted()
                if self._pos_reports >= ticket and (target is None or self._at(target)):
                    return
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise RuntimeError(
                        f"Printer did not reach {target} within {timeout:.0f}s "
                        f"(last reported position: {self.current_position}). "
                        "Commands may have been lost on the serial connection."
                    )
                self._pos_cond.wait(min(remaining, 0.1))

    def _move(self, x, y, z, feedrate):
        """Move to absolute printer coordinates and return once the head
        is there."""
        for axis, val in (("X", x), ("Y", y), ("Z", z)):
            lo, hi = LIMITS[axis]
            if not lo <= val <= hi:
                raise ValueError(f"{axis}={val:.3f} outside limits {LIMITS[axis]}")
        pos = self.current_position
        dist = ((pos["X"] - x) ** 2 + (pos["Y"] - y) ** 2 + (pos["Z"] - z) ** 2) ** 0.5
        # Generous timeout: 3x the nominal move time (firmware may clamp
        # the Z feedrate well below the requested one) plus a fixed margin.
        timeout = 3 * dist / (feedrate / 60.0) + 15
        self.p.send("G90")
        self.p.send(f"G1 X{x:.3f} Y{y:.3f} Z{z:.3f} F{feedrate}")
        self._wait_until_idle(target=(x, y, z), timeout=timeout)

    def _travel_to(self, x, y, z, feedrate=TRAVEL_FEEDRATE):
        """Collision-aware travel: up to a safe Z first (at least the top
        layer of the scan volume), then X, then Y, then down. Never a
        diagonal move down through the scan volume."""
        self._wait_until_idle()  # fresh, settled position
        safe_z = min(FIXED_COORD["Z"] + float(self._sample_height), LIMITS["Z"][1])
        pos = dict(self.current_position)
        lift = max(pos["Z"], safe_z, z)
        if pos["Z"] < lift:
            self._move(pos["X"], pos["Y"], lift, feedrate)
        if abs(pos["X"] - x) > POSITION_TOLERANCE:
            self._move(x, pos["Y"], lift, feedrate)
        if abs(pos["Y"] - y) > POSITION_TOLERANCE:
            self._move(x, y, lift, feedrate)
        if abs(lift - z) > POSITION_TOLERANCE:
            self._move(x, y, z, feedrate)

    def _travel_to_start(self):
        print("Travelling to start position (up, across, down)...")
        self._travel_to(FIXED_COORD["X"], FIXED_COORD["Y"], FIXED_COORD["Z"])

    def _home_worker(self):
        try:
            self._travel_to_start()
            print("At start position.")
        except RunAborted:
            print("Move to start position aborted.")
        except Exception as e:
            print(f"ERROR while moving to start position: {e}")

    def _run_raster(self, feedrate, on_point=None):
        """Shared by run_testrun() and scan_volume(): travel to the start
        point, then visit every raster point, waiting at each one until
        the head has actually arrived. on_point(iz, x, y, z) runs at each
        point (the measurement reads the sensor there)."""
        self._travel_to_start()
        current_layer = None
        for iz, x_target, y, z in self.raster_scan_points():
            if self.stop_event.is_set():
                raise RunAborted()
            if iz != current_layer:
                # raster_scan_points() keeps X/Y equal across a layer
                # change, so this first move of a layer is a pure Z move.
                print(f"Starting layer at Z={z:.3f}")
                current_layer = iz
            print(f"Moving to X={x_target:.3f}, Y={y:.3f}, Z={z:.3f}")
            self._move(x_target, y, z + FIXED_COORD["Z"], feedrate)
            if on_point is not None:
                on_point(iz, x_target, y, z)

    def _start_worker(self, target):
        """Run a long scan (run_testrun/scan_volume) in its own thread so
        listen_to_gui_commands() stays free to receive an ABORT command
        while the scan is in progress."""
        if self._active_worker is not None and self._active_worker.is_alive():
            print("A run is already in progress; ignoring new start request.")
            return
        self.stop_event.clear()
        self._active_worker = threading.Thread(target=target, daemon=True)
        self._active_worker.start()

    def _check_bounds(self):
        """Raise ValueError if the current sample dimensions would move the
        print head outside LIMITS on any axis. Every move applies
        FIXED_COORD['Z'] as a Z offset (see raster_scan_points/run_testrun/
        scan_volume), so the Z check must include that offset - checking
        the sample height alone against LIMITS["Z"] misses it and would
        let the head be commanded past its configured Z limit."""
        if not (LIMITS["X"][0] <= 0 <= LIMITS["X"][1] and LIMITS["X"][0] <= self._sample_length <= LIMITS["X"][1]):
            raise ValueError(f"Sample length {self._sample_length} mm out of bounds {LIMITS['X']}")
        if not (LIMITS["Y"][0] <= 0 <= LIMITS["Y"][1] and LIMITS["Y"][0] <= self._sample_width <= LIMITS["Y"][1]):
            raise ValueError(f"Sample width {self._sample_width} mm out of bounds {LIMITS['Y']}")

        z_min = FIXED_COORD['Z']
        z_max = self._sample_height + FIXED_COORD['Z']
        if not (LIMITS["Z"][0] <= z_min <= LIMITS["Z"][1] and LIMITS["Z"][0] <= z_max <= LIMITS["Z"][1]):
            raise ValueError(
                f"Sample height {self._sample_height} mm would move Z through "
                f"{z_min:.1f}-{z_max:.1f} mm, outside limits {LIMITS['Z']}"
            )

    def raster_scan_points(self):
        """Generate the (layer_index, x, y, z) move sequence shared by
        run_testrun() and scan_volume(). Both commands iterate this same
        generator, which guarantees the collision test run always moves
        through the exact same points, in the exact same order, as the
        real measurement scan."""

        self._sample_length = float(self._sample_length)
        self._sample_width  = float(self._sample_width)
        self._sample_height = float(self._sample_height)
        self._sample_stepsize = float(self._sample_stepsize)
        z_points = np.arange(0, self._sample_height + self._sample_stepsize/2, self._sample_stepsize)
        y_points = np.arange(0, self._sample_width  + self._sample_stepsize/2, self._sample_stepsize)
        x_points = np.arange(0, self._sample_length + self._sample_stepsize/2, self._sample_stepsize)

        # row_count keeps incrementing across the whole scan instead of
        # resetting at each new Z layer, so the X zigzag direction picks up
        # mirrored from wherever the previous layer left off. Combined with
        # reversing the row order every other layer (so a new layer's first
        # row is at the same Y as the previous layer's last row), the last
        # point of one layer and the first point of the next always share
        # the same X and Y - only Z changes when moving to a new layer.
        row_count = 0
        for iz, z in enumerate(z_points):

            y_iter = y_points if iz % 2 == 0 else y_points[::-1]

            for y in y_iter:

                x_iter = x_points if row_count % 2 == 0 else x_points[::-1]

                for x in x_iter:
                    yield iz, float(x), float(y), float(z)

                row_count += 1
    
    @attribute
    def get_sample_width(self)->float:
        return self._sample_width
    @attribute
    def get_sample_length(self)->float:
        return self._sample_length
    @attribute
    def get_sample_stepsize(self)->float:
        return self._sample_stepsize
    @attribute
    def set_sample_width(self, value: float):
        self._sample_width = value
    @attribute
    def set_sample_length(self, value: float):
        self._sample_length = value

    @attribute
    def set_sample_stepsize(self, value: float):
        self._sample_stepsize = value

    @attribute
    def get_start_position(self):
        return [self.current_position.get("X", 0.0), self.current_position.get("Y", 0.0), self.current_position.get("Z", 20.0)]

    @attribute
    def get_x_position(self)->float:
        return self.current_position.get("X", 0.0)
    
    @attribute
    def get_y_position(self)->float:
        return self.current_position.get("Y", 0.0)
            
    @attribute
    def get_z_position(self)->float:
        return self.current_position.get("Z", 0.0)      
    
    
    @command
    def run_testrun(self):

        self._check_bounds()

        self._sample_length   = float(self._sample_length)
        self._sample_width    = float(self._sample_width)
        self._sample_height   = float(self._sample_height)
        self._sample_stepsize = float(self._sample_stepsize)

        print(f"Test run with L={self._sample_length} mm, W={self._sample_width} mm, "
            f"H={self._sample_height} mm, step={self._sample_stepsize} mm, "
            f"F{self.testrun_feedrate}")

        self.status_queue.put(("STATUS", STATUS_TESTRUN_RUNNING))

        # Same _run_raster() as scan_volume(): same start travel, same
        # points, same order, and it also waits at every point until the
        # head has arrived. Only differences: higher feedrate, no sensor
        # read and no settle pause.
        try:
            self._run_raster(self.testrun_feedrate)
        except RunAborted:
            print("Test run aborted by user.")
            self.status_queue.put(("STATUS", STATUS_TESTRUN_ABORTED))
            return
        except Exception as e:
            print(f"ERROR during test run: {e}")
            self.status_queue.put(("STATUS", STATUS_TESTRUN_ABORTED))
            return

        print("Test run finished - head has reached the last point.")
        self.status_queue.put(("STATUS", STATUS_TESTRUN_FINISHED))

    @command
    def start_gui(self):
        self.gui_process = Process(
            target=teslameter_gui.run_gui,
            args=(self.data_queue, self.dim_queue, self.command_queue)
        )
        self.gui_process.start()

        # Wait for sample dimensions from GUI
        print("Waiting for sample dimensions input...")
        while self.dim_queue.empty():
            time.sleep(0.1)

        dims = self.dim_queue.get()
        self._sample_length, self._sample_width, self._sample_height = dims
        print(f"Sample dimensions received: L={dims[0]}, W={dims[1]}, H={dims[2]}")
        
    
    @command
    def read_position(self):
        self._query_position()  # request position update
    @command
    def beep(self):
        self.p.send("M300 S440 P200")
        self.p.send("M300 S660 P250")
        self.p.send("M300 S880 P300")
    @command
    def move(self, values: list[float]):
        if len(values) != 3:
            raise ValueError("Values must be a list of three floats: [x,y,z]")
        dx, dy, dz = values
        if not (LIMITS["X"][0] <= self.current_position["X"] + dx <= LIMITS["X"][1]):
            raise ValueError(f"X movement out of bounds: {self.current_position['X']} + {dx}")
        if not (LIMITS["Y"][0] <= self.current_position["Y"] + dy <= LIMITS["Y"][1]):
            raise ValueError(f"Y movement out of bounds: {self.current_position['Y']} + {dy}")
        if not (LIMITS["Z"][0] <= self.current_position["Z"] + dz <= LIMITS["Z"][1]):
            raise ValueError(f"Z movement out of bounds: {self.current_position['Z']} + {dz}")
        self.current_position["X"] += dx
        self.current_position["Y"] += dy
        self.current_position["Z"] += dz
        self.p.send("G90")  # absolute positioning
        self.p.send(f"G1 X{self.current_position['X']} Y{self.current_position['Y']} Z{self.current_position['Z']} F3000")
        self.p.send("M400")  # wait for moves to complete
        self._query_position()  # report position
    @command
    def scan_sample(self):
        z_height = FIXED_COORD['Z']
        direction = 1  # 1 for forward, -1 for backward
        device_number = C.c_int()
        device_number.value=0
        tm.A3mtslib.open_device(C.byref(device_number))
        
        

        # Raster points along each axis
        x_points = np.arange(0, self._sample_length + self._sample_stepsize, self._sample_stepsize)
        y_points = np.arange(0, self._sample_width + self._sample_stepsize, self._sample_stepsize)
        z_points = np.arange(0, self._sample_height + self._sample_stepsize, self._sample_stepsize)

        scan_points = []

        # --- 1. South side (y = 0) ---
        for j, z in enumerate(z_points):
            if j % 2 == 0:
                seq = x_points
            else:
                seq = x_points[::-1]
            for x in seq:
                scan_points.append((x, -10, z+40))

        # --- 2. West side (x = 0) ---
        for j, z in enumerate(z_points):
            if j % 2 == 0:
                seq = y_points
            else:
                seq = y_points[::-1]
            for y in seq:
                scan_points.append((-10, y, z+40))

        # --- 3. North side (y = Ly) ---
        for j, z in enumerate(z_points):
            if j % 2 == 0:
                seq = x_points[::-1]
            else:
                seq = x_points
            for x in seq:
                scan_points.append((x, 10+self._sample_width, z+40))

        # --- 4. East side (x = Lx) ---
        for j, z in enumerate(z_points):
            if j % 2 == 0:
                seq = y_points[::-1]
            else:
                seq = y_points
            for y in seq:
                scan_points.append((10+self._sample_length, y, z+40))
        for point in scan_points:
            self.p.send("G90")  # absolute positioning
            x_target, y_target, z_target = point
            print(f"Moving to X={x_target}, Y={y_target}, Z={z_target}")
            self.p.send(f"G1 X{x_target} Y{y_target} Z{z_target} F500")
            self.p.send("M400")  # wait for moves to complete
            time.sleep(5)  # small pause to clear buffer

    @command
    def start_Heatmap(self):
        self.gui_process = Process(
            target=Heatmap.run_gui,
            args=(self.data_queue, 
                  self.dim_queue,
                  self.command_queue,
                  self.status_queue,
                  (self._sample_length // self._sample_stepsize + 1,
                   self._sample_width // self._sample_stepsize + 1),
                  self._sample_height // self._sample_stepsize + 1)
        )
        self.gui_process.start()
        while self.dim_queue.empty():
            time.sleep(0.1)
        dims = self.dim_queue.get()
        self._sample_length  = float(round(dims[0]))
        self._sample_width   = float(round(dims[1]))
        self._sample_height  = float(round(dims[2]))
        self._sample_stepsize = float(round(dims[3]))

        self.status_queue.put(("STATUS", STATUS_WAIT_DUMMY_INSTALL))
       
    @command
    def scan_volume(self, output_file=""):
        if not output_file:
            output_file = f"scan_{time.strftime('%Y%m%d_%H%M%S')}.txt"

        self.status_queue.put(("STATUS", STATUS_MEASUREMENT_STARTED))
        device_number = C.c_int()
        device_number.value=0
        def coord_to_index(val, step, max_index):
            idx = int(round(val / step))
            if idx < 0:
                idx = 0
            if idx >= max_index:
                idx = max_index - 1
            return idx
        all_data = []
        self._check_bounds()
        self._sample_length = float(self._sample_length)
        self._sample_width = float(self._sample_width)
        self._sample_height = float(self._sample_height)
        self._sample_stepsize = float(self._sample_stepsize)

        # Same _run_raster() as run_testrun(), so the measurement traces
        # exactly the path the test run already verified collision-free.
        def measure_point(iz, x_target, y, z):
            # _run_raster() only calls this once the head has arrived;
            # the settle time lets vibrations die down before reading.
            time.sleep(SETTLE_TIME)

            # Get sensor values
            timestamp = C.c_ulong()
            sensorx = C.c_float()
            sensory = C.c_float()
            sensorz = C.c_float()
            tm.A3mtslib.clear_buffer(C.byref(device_number))
            time.sleep(0.1)
            tm.A3mtslib.get_sensor_values_fl(
                C.byref(device_number),
                C.byref(timestamp),
                C.byref(sensorx),
                C.byref(sensory),
                C.byref(sensorz)
            )

            Bx, By, Bz = sensorx.value, sensory.value, sensorz.value
            #Bx,By,Bz = random.uniform(-30000,30000), random.uniform(-30000,30000), random.uniform(-30000,30000)
            print(f"Measurement: Bx={Bx:.4f}, By={By:.4f}, Bz={Bz:.4f}")

            ix = coord_to_index(x_target, self._sample_stepsize, self._sample_length // self._sample_stepsize + 1)
            iy = coord_to_index(y, self._sample_stepsize, self._sample_width // self._sample_stepsize + 1)
            iz_index = coord_to_index(z, self._sample_stepsize, self._sample_height // self._sample_stepsize + 1)

            self.data_queue.put((ix, iy, iz_index, Bx, By, Bz))
            all_data.append((x_target, y, z, Bx, By, Bz))

        aborted = False
        try:
            self._run_raster(SCAN_FEEDRATE, on_point=measure_point)
        except RunAborted:
            print("Measurement aborted by user.")
            aborted = True
        except Exception as e:
            print(f"ERROR during measurement: {e}")
            aborted = True

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# Teslameter scan {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# aborted={aborted}\n")
            f.write(f"# sample_length_mm={self._sample_length}\n")
            f.write(f"# sample_width_mm={self._sample_width}\n")
            f.write(f"# sample_height_mm={self._sample_height}\n")
            f.write(f"# step_size_mm={self._sample_stepsize}\n")
            f.write("ix, iy, iz, Bx, By, Bz\n")
            for ix, iy, iz, Bx, By, Bz in all_data:
                f.write(f"{ix}, {iy}, {iz}, {Bx:.2f}, {By:.2f}, {Bz:.2f}\n")

        print(f"Wrote {len(all_data)} data points to {output_file}")
        self.status_queue.put(("STATUS", STATUS_MEASUREMENT_ABORTED if aborted else STATUS_MEASUREMENT_FINISHED))

    @command
    def move_to(self, coordinates: list[float]):
        if len(coordinates) != 3:
            raise ValueError("Coordinates must be a list of three floats: [X, Y, Z]")
        x, y, z = coordinates
        if not (LIMITS["X"][0] <= x <= LIMITS["X"][1]):
            raise ValueError(f"X coordinate {x} out of bounds {LIMITS['X']}")
        if not (LIMITS["Y"][0] <= y <= LIMITS["Y"][1]):
            raise ValueError(f"Y coordinate {y} out of bounds {LIMITS['Y']}")
        if not (LIMITS["Z"][0] <= z <= LIMITS["Z"][1]):
            raise ValueError(f"Z coordinate {z} out of bounds {LIMITS['Z']}")
        print(f"Moving to X:{x}, Y:{y}, Z:{z}")
        self.current_position.update({"X": x, "Y": y, "Z": z})
        self.p.send("G90")                 # absolute positioning
        self.p.send(f"G1 X{x} Y{y} Z{z} F3000")
        self.p.send("M400")              # wait for moves to complete
        self._query_position()              # report position

    @command
    def home_and_move_to_start(self):
        # Absolute mode + mm
        self.p.send("G21")               # mm units
        self.p.send("G90")               # absolute positioning
        self.p.send("G28")               # home all axes
        self.p.send("M400")
        self.p.send("G92 X0 Y0 Z0")

        # Move to start position
        self.p.send(f"G1 X{FIXED_COORD['X']} Y{FIXED_COORD['Y']} Z{FIXED_COORD['Z']} F3000")
        

        # Wait for motion to finish and report final position
        self.p.send("M400")              # wait for moves to complete
        self._query_position()              # report position

   

if __name__ == "__main__":
    PrintDevice.run_server()