#!/usr/bin/python3
# -*- coding: utf-8 -*-

import ctypes as C
import sys
from PyQt6 import QtWidgets, QtCore
import pyqtgraph as pg
from multiprocessing import Queue
from pathlib import Path


def get_base_path():

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent.parent


def find_dll_path():
    base = get_base_path()
    # PyInstaller (onedir) may place bundled data next to the exe or, since
    # v6, inside a "_internal" subfolder depending on build configuration.
    candidates = [
        base / "drivers" / "a3mtslib64.dll",
        base / "_internal" / "drivers" / "a3mtslib64.dll",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "Teslameter DLL not found. Searched in:\n"
        + "\n".join(str(c) for c in candidates)
    )


BASE_PATH = get_base_path()
DLL_PATH = find_dll_path()

A3mtslib = C.CDLL(str(DLL_PATH))

device_number = C.c_int(0)
def count_devices() -> int:
    count = C.c_ushort()
    A3mtslib.count_devices(C.byref(count))
    return count.value

def get_device_name(device_number: int) -> str:
    name_buffer = C.create_string_buffer(40)
    A3mtslib.get_device_name_ch(C.byref(C.c_int(device_number)), name_buffer)
    return name_buffer.value.decode()

def get_sensor_values():
    timestamp = C.c_ulong()
    sensorx = C.c_float()
    sensory = C.c_float()
    sensorz = C.c_float()
    A3mtslib.get_sensor_values_fl(
        C.byref(device_number),
        C.byref(timestamp),
        C.byref(sensorx),
        C.byref(sensory),
        C.byref(sensorz)
    )

    return sensorx.value, sensory.value, sensorz.value

