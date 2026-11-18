# teslameter_gui.py
# -*- coding: utf-8 -*-
import sys
from multiprocessing import Queue
from PyQt6 import QtWidgets, QtCore
import pyqtgraph as pg

class SampleDialog(QtWidgets.QDialog):
    """Dialog for entering the length, width, and height of a sample"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Enter Sample Dimensions")
        self.resize(300, 150)

        # Input fields
        self.length_edit = QtWidgets.QLineEdit()
        self.width_edit = QtWidgets.QLineEdit()
        self.height_edit = QtWidgets.QLineEdit()

        # Labels
        form_layout = QtWidgets.QFormLayout()
        form_layout.addRow("Length (mm):", self.length_edit)
        form_layout.addRow("Width (mm):", self.width_edit)
        form_layout.addRow("Height (mm):", self.height_edit)

        # Buttons
        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(form_layout)
        layout.addWidget(self.button_box)
        self.setLayout(layout)

    def get_values(self):
        """Return the entered values as a float tuple"""
        try:
            length = float(self.length_edit.text())
            width = float(self.width_edit.text())
            height = float(self.height_edit.text())
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Error", "Please enter valid numbers!")
            return None
        return length, width, height

class TeslameterPlot(QtWidgets.QWidget):
    def __init__(self, data_queue: Queue, sample_dims=None):
        super().__init__()
        self.setWindowTitle("Teslameter Live Plot")
        self.resize(800, 500)
        self.data_queue = data_queue

        # Plot Setup
        self.plotWidget = pg.PlotWidget(title="Magnetfeld (Tesla)")
        self.plotWidget.addLegend()
        self.plotWidget.showGrid(x=True, y=True)
        

       
        self.xdata, self.ydata, self.zdata, self.t = [], [], [], []
        self.time_index = 0

        
        self.curve_x = self.plotWidget.plot(pen=pg.mkPen('r', width=2), name='Bx')
        self.curve_y = self.plotWidget.plot(pen=pg.mkPen('g', width=2), name='By')
        self.curve_z = self.plotWidget.plot(pen=pg.mkPen('b', width=2), name='Bz')

        # Layout 
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.plotWidget)
        self.setLayout(layout)

        
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(100)  

    def update_plot(self):
        
        while not self.data_queue.empty():
            bx, by, bz = self.data_queue.get()
            self.xdata.append(bx)
            self.ydata.append(by)
            self.zdata.append(bz)
            self.t.append(self.time_index)
            self.time_index += 1

        # Update Plot
        self.curve_x.setData(self.t, self.xdata)
        self.curve_y.setData(self.t, self.ydata)
        self.curve_z.setData(self.t, self.zdata)


def run_gui(data_queue: Queue, dim_queue=None):
    """Starts the PyQt6 application"""
    app = QtWidgets.QApplication(sys.argv)
    dialog = SampleDialog()
    if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
        values = dialog.get_values()
        if values:
            if dim_queue is not None:
                dim_queue.put(values)
            window = TeslameterPlot(data_queue, sample_dims=values)
            window.show()
            sys.exit(app.exec())
    else:
        print("Measurement cancelled.")
        sys.exit(0)

    window = TeslameterPlot(data_queue)
    window.show()
    sys.exit(app.exec())