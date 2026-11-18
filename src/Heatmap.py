# teslameter_heatmap_gui.py
# -*- coding: utf-8 -*-
import sys
from multiprocessing import Queue
from PyQt6 import QtWidgets, QtCore
import pyqtgraph as pg
import numpy as np



class TeslameterHeatmap(QtWidgets.QWidget):
    def __init__(self, data_queue: Queue, grid_size, num_layers, command_queue,status_queue
    
    ):
        super().__init__()
        self.setWindowTitle("Teslameter Heatmap View")
        self.resize(1000, 850)
        self.command_queue = command_queue
        self.data_queue = data_queue
        self.status_queue = status_queue
        self.grid_size = grid_size
        self.num_layers = num_layers  # Number of possible z layers

        # Heatmap widgets
        self.plotBx = pg.ImageView()
        self.plotBy = pg.ImageView()
        self.plotBz = pg.ImageView()

        # Hide histogram + buttons
        for plot in (self.plotBx, self.plotBy, self.plotBz):
            plot.ui.roiBtn.hide()
            plot.ui.menuBtn.hide()
        
        for plot in (self.plotBx, self.plotBy, self.plotBz):
            plot.setColorMap(pg.colormap.get('viridis'))

        # Layout
        layout = QtWidgets.QGridLayout()
        layout.addWidget(QtWidgets.QLabel("Bx [T]"), 0, 0)
        layout.addWidget(QtWidgets.QLabel("By [T]"), 0, 1)
        layout.addWidget(QtWidgets.QLabel("Bz [T]"), 0, 2)
        layout.addWidget(self.plotBx, 1, 0)
        layout.addWidget(self.plotBy, 1, 1)
        layout.addWidget(self.plotBz, 1, 2)

        # Timeline slider
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(num_layers - 1)
        self.slider.setValue(0)
        self.slider.valueChanged.connect(self.update_slider_layer)
        layout.addWidget(QtWidgets.QLabel("Z layer / time:"), 2, 0)
        layout.addWidget(self.slider, 2, 1, 1, 2)

        self.setLayout(layout)

        # Buttons
        self.btn_home = QtWidgets.QPushButton("Move to Startposition")
        self.btn_rescan = QtWidgets.QPushButton("Start New Measurement")
        self.btn_home.hide()
        self.btn_start_testrun = QtWidgets.QPushButton("Start Test Run")
        self.btn_abort         = QtWidgets.QPushButton("Abort (Crash)")
        self.btn_abort.hide()
        
        self.btn_start_testrun.clicked.connect(
            lambda: self.command_queue.put(("START_TESTRUN", None))
        )

        self.btn_abort.clicked.connect(
            lambda: self.command_queue.put(("ABORT", None))
        )
                


        self.btn_home.clicked.connect(self.send_home_command)
        self.btn_rescan.clicked.connect(self.send_rescan_command)
        layout.addWidget(self.btn_home, 3, 0)
        layout.addWidget(self.btn_rescan, 3, 1)
        layout.addWidget(self.btn_start_testrun, 3, 2)
        layout.addWidget(self.btn_abort, 4, 0)


        # Data container: 3D (z, y, x)
        self.Bx = np.zeros((num_layers, *grid_size[::-1]))
        self.By = np.zeros((num_layers, *grid_size[::-1]))
        self.Bz = np.zeros((num_layers, *grid_size[::-1]))
        self.current_layer = 0

        # Update timer
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_heatmaps)
        self.timer.start(100)
    
    def send_home_command(self):
        self.command_queue.put(("HOME", None))
        self.btn_rescan.show()

    def send_rescan_command(self):
        self.command_queue.put(("RESCAN", None))

    def update_slider_layer(self, value):
        """Called when the slider is moved."""
        self.current_layer = value
        self.refresh_display()

    def refresh_display(self):
        self.plotBx.setImage(np.rot90(self.Bx[self.current_layer], 3), autoLevels=True)
        self.plotBy.setImage(np.rot90(self.By[self.current_layer], 3), autoLevels=True)
        self.plotBz.setImage(np.rot90(self.Bz[self.current_layer], 3), autoLevels=True)


    def update_heatmaps(self):
        """Fetch new data from the queue, evaluate status, and update heatmaps."""
        updated = False

        # --- EVALUATE STATUS MESSAGES ---
        while not self.status_queue.empty():
            cmd, value = self.status_queue.get()

            if cmd != "STATUS":
                continue

            if value == "WAIT_DUMMY_INSTALL":
                QtWidgets.QMessageBox.information(
                    self,
                    "Mount test dummy",
                    "Please install the test dummy on the printer.\n"
                    "Then start the test run."
                )
                self.btn_home.hide()
                self.btn_rescan.hide()
                self.btn_start_testrun.show()
                self.btn_abort.hide()

            elif value == "TESTRUN_RUNNING":
                self.btn_start_testrun.hide()
                self.btn_abort.show()

            elif value == "TESTRUN_FINISHED":
                self.btn_abort.hide()
                result = QtWidgets.QMessageBox.question(
                    self,
                    "Test run finished",
                    "Did the test dummy collide?",
                    QtWidgets.QMessageBox.StandardButton.Yes |
                    QtWidgets.QMessageBox.StandardButton.No
                )

                if result == QtWidgets.QMessageBox.StandardButton.Yes:
                    self.command_queue.put(("TESTRUN_CRASH", None))
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Collision detected",
                        "The test run was marked as a collision.\n"
                        "Please check the test dummy and reposition it if necessary.")
                else:
                    self.command_queue.put(("TESTRUN_OK", None))
                self.btn_home.show()

            elif value == "TESTRUN_ABORTED":
                self.btn_abort.hide()
                QtWidgets.QMessageBox.warning(
                    self,
                    "Test run stopped",
                    "The test run was stopped. Please check the test dummy's position."
                )
                self.btn_home.show()
                self.btn_start_testrun.show()

            elif value == "WAIT_REAL_INSTALL":
                QtWidgets.QMessageBox.information(
                    self,
                    "Mount the real teslameter",
                    "Please install the real teslameter now.\n"
                    "Afterwards, the real measurement can be started."
                )

                self.btn_abort.hide()

            elif value == "MEASUREMENT_STARTED":
                self.btn_home.hide()
                self.btn_rescan.hide()
                self.btn_start_testrun.hide()
                self.btn_abort.show()

            elif value == "MEASUREMENT_FINISHED":
                self.btn_home.show()
                self.btn_rescan.show()
                self.btn_start_testrun.hide()
                self.btn_abort.hide()

            elif value == "MEASUREMENT_ABORTED":
                self.btn_abort.hide()
                QtWidgets.QMessageBox.warning(
                    self,
                    "Measurement stopped",
                    "The measurement was stopped. Partial data (if any) was still saved to the output file."
                )
                self.btn_home.show()
                self.btn_rescan.show()

        # --- PROCESS MEASUREMENT DATA FROM QUEUE ---
        while not self.data_queue.empty():
            try:
                x, y, z, bx, by, bz = self.data_queue.get()
            except Exception as e:
                print("Invalid data record:", e)
                continue

            if (
                0 <= x < self.grid_size[0]
                and 0 <= y < self.grid_size[1]
                and 0 <= z < self.num_layers
            ):
                self.Bx[z, y, x] = bx
                self.By[z, y, x] = by
                self.Bz[z, y, x] = bz
                updated = True
                last_z = z

        # --- REFRESH DISPLAY ---
        if updated:
            self.current_layer = last_z
            self.slider.blockSignals(True)
            self.slider.setValue(self.current_layer)
            self.slider.blockSignals(False)
            self.refresh_display()

class SampleInputDialog(QtWidgets.QDialog):
    """Dialog for entering sample dimensions and step size."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sample Parameter Input")
        self.setFixedSize(300, 250)

        layout = QtWidgets.QFormLayout()

        # Input fields
        self.length_input = QtWidgets.QDoubleSpinBox()
        self.length_input.setRange(1, 500)
        self.length_input.setValue(20)
        self.length_input.setSuffix(" mm")

        self.width_input = QtWidgets.QDoubleSpinBox()
        self.width_input.setRange(1, 500)
        self.width_input.setValue(20)
        self.width_input.setSuffix(" mm")

        self.height_input = QtWidgets.QDoubleSpinBox()
        self.height_input.setRange(0, 500)  # 0 = single-plane measurement
        self.height_input.setValue(10)
        self.height_input.setSuffix(" mm")

        self.stepsize_input = QtWidgets.QDoubleSpinBox()
        self.stepsize_input.setRange(0.1, 50)
        self.stepsize_input.setValue(5)
        self.stepsize_input.setSuffix(" mm")

        # Buttons
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        # Assemble layout
        layout.addRow("Length (X):", self.length_input)
        layout.addRow("Width (Y):", self.width_input)
        layout.addRow("Height (Z):", self.height_input)
        layout.addRow("Step size:", self.stepsize_input)
        layout.addRow(button_box)

        self.setLayout(layout)

    def get_values(self):
        """Return the entered values as a tuple."""
        return (
            self.length_input.value(),
            self.width_input.value(),
            self.height_input.value(),
            self.stepsize_input.value(),
        )

def run_gui(data_queue,dim_queue, command_queue, status_queue, grid_size=None, num_layers=None):
    """Start the PyQt6 application with the input dialog and heatmaps."""
    app = QtWidgets.QApplication(sys.argv)

    # 1. Show dialog before starting the heatmap
    dialog = SampleInputDialog()
    if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
        vals = dialog.get_values()
        dim_queue.put(vals)
        grid_size=(
            int(vals[0] / vals[3]) + 1,
            int(vals[1] / vals[3]) + 1,)
        num_layers = int(vals[2] / vals[3]) + 1

    else:
        print("Cancelled by user.")
        sys.exit(0)

    # 2. Start the main heatmap
    window = TeslameterHeatmap(data_queue, grid_size, num_layers, command_queue,status_queue)
    window.show()
    sys.exit(app.exec())
