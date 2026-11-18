# Teslameter Printer

This program uses a 3D printer to move a teslameter (a magnetic field sensor) step by step around a sample. At each point it measures the magnetic field. While it runs you see the result live as three colour maps (Bx, By, Bz), and at the end it saves everything to a text file.

Before every real measurement you do a **test run** with a dummy instead of the real sensor. The test run moves through exactly the same points as the measurement, just faster. If the dummy hits nothing, the real sensor won't either.

---

## What you need

- The 3D printer, connected to the PC by USB and switched on
- The 3MTS teslameter, connected to the PC by USB
- A **test dummy**: something the same size and shape as the teslameter probe, but cheap to bump into things
- The program folder `TeslameterPrinter`, containing `TeslameterPrinter.exe` and a `_internal` subfolder. Ask the person who set this up in your lab for it, or build it yourself (see *For developers* at the end). Always copy the **whole folder**, not just the `.exe`.

You do **not** need to install Python or anything else. Everything the program needs is in the folder.

---

## First-time setup

Do this once per PC.

### 1. Find the printer's COM port

Windows gives every USB printer a "COM port" number, and the program needs to know which one.

1. Plug in the printer and switch it on.
2. Right-click the Start button and open **Device Manager**.
3. Expand **Ports (COM & LPT)**. You'll see something like *USB-SERIAL CH340 (COM3)* or *USB Serial Device (COM5)*.
   - Not sure which entry is the printer? Unplug it, watch which entry disappears, then plug it back in.
4. Note the number, for example `COM3`.

### 2. Enter it in `config.ini`

In the program folder, open `config.ini` with Notepad. If the file isn't there yet, start the program once and it will create it.

```ini
[printer]
port = COM3
baudrate = 115200
testrun_feedrate = 1500
```

| Setting | What it means | Change it? |
|---|---|---|
| `port` | The COM port from step 1 | **Yes**, if it isn't COM3 |
| `baudrate` | Connection speed to the printer | Leave as is, unless the printer's manual says otherwise |
| `testrun_feedrate` | How fast the test run moves (the measurement always moves at 500) | Optional. A higher number means a faster test run, but a harder bump if the dummy does hit something |

Save the file. Changes apply the next time you start the program.

### 3. Check the teslameter is recognised

Plug in the teslameter. If Windows doesn't recognise it, or the program later can't read values from it, install the manufacturer's software: run `Setup_3MTS_...exe` from the `Teslameter\Installation Software\3MTS Installer` folder on the Desktop.

---

## Running a measurement

> ⚠️ **Right after you start the program, the printer homes all axes and then moves to its start position.** Before you start it, make sure nothing is in the printer's way and keep your hands out of the printer.

### Step 1: Start the program

Double-click `TeslameterPrinter.exe`. A black text window opens. **Leave it open.** It is the program; closing it stops everything.

The printer homes and moves to the start position. The start position is the **corner** of the area that will be scanned, at a height of 30 mm.

### Step 2: Enter the sample size

A small window asks for four values, all in millimetres:

| Field | Meaning |
|---|---|
| **Length (X)** | How far to scan along the printer's X axis, starting at the start position |
| **Width (Y)** | How far to scan along the Y axis |
| **Height (Z)** | How far upward to scan. Use `0` for a single flat layer |
| **Step size** | Distance between two measuring points |

Tips:
- **Use whole numbers.** Values are rounded to whole millimetres, so a step size below 1 mm doesn't work.
- The scan area must stay inside the printer: length up to 100 mm, width up to 110 mm, height up to 200 mm.
- **Number of points** = (length ÷ step + 1) × (width ÷ step + 1) × (height ÷ step + 1). The measurement takes about **2 seconds per point**. For example, 20 × 20 × 10 mm at a 5 mm step is 5 × 5 × 3 = 75 points, about 2–3 minutes. Smaller steps add up fast: the same area at a 1 mm step is 4851 points, close to 3 hours.

Click **OK**. The heatmap window opens.

### Step 3: Test run with the dummy

1. A message asks you to **mount the test dummy**. Mount it where the teslameter normally goes, then click OK.
2. Click **Start Test Run**. The printer moves through every point.
3. Watch the printer. **If the dummy is about to hit something, click "Abort (Crash)"** right away. (See *If something goes wrong* below.)
4. When the test run is done, the program asks: **"Did the test dummy collide?"**
   - **Yes**: reposition the sample or change the sample size, then do another test run.
   - **No**: carry on.

### Step 4: Real measurement

1. A message asks you to **mount the real teslameter**. Swap the dummy for the teslameter and click OK.
2. Click **Move to Startposition**. The printer moves up first, then across, then down, so it doesn't drag the sensor through the sample.
3. Click **Start New Measurement**.
4. The colour maps fill in point by point. Use the slider under the maps to look at the different height layers.

You can click **Start New Measurement** again afterwards to repeat the measurement with the same settings.

### Step 5: Get your data

When the measurement is done, a file named like `scan_20261118_141258.txt` (date and time) appears in the program folder, next to the `.exe`.

The top lines starting with `#` describe the measurement: sample size, step size, and whether it was aborted. Then there's one line per point:

```
X position, Y position, Z position (all in mm), Bx, By, Bz
```

(Note: the column header in the file says `ix, iy, iz`, but those columns contain the positions in mm.)

You can open the file in Excel (*Data → From Text/CSV*, comma-separated) or in any analysis tool.

### Step 6: Close the program

Click into the black text window and press **Ctrl + C**, or just close the window.

---

## If something goes wrong

| Problem | What to do |
|---|---|
| You clicked **Abort (Crash)** | The printer stops immediately and locks itself for safety. **Switch the printer off and on again**, close the program, and start it again. Then check the dummy and the sample before the next test run. |
| Text window says *"Printer did not respond on COM3"* | Wrong COM port, or the printer is off or unplugged. Check the port number (First-time setup, step 1) and `config.ini`. |
| Text window says *"Teslameter DLL not found"* | The program folder is incomplete. Copy the whole `TeslameterPrinter` folder again, including the `_internal` subfolder. |
| Test run or measurement stops with *"Printer did not reach …"* | The printer lost a command, usually because of a loose USB cable or a USB hub. Check the cable and plug it directly into the PC, then restart the printer and the program. |
| The program windows open again and again | You're running a very old version (from before August 2026). Get a current one. |
| The colour maps stay empty | Check that the teslameter is plugged in (First-time setup, step 3). |
| You clicked **Cancel** in the sample size window | The program can't continue without the sample size. Close the black text window and start the program again. |

When in doubt: **switch the printer off.** That always stops it safely.

---

## Safety summary

- Keep hands out of the printer while the program runs. It moves right after starting.
- **Always do a test run with the dummy** before a measurement, and do a new one whenever you change the sample, its position, or the sample size.
- Stay at the printer during the test run, ready to click *Abort (Crash)* or switch the printer off.

---

## For developers

Requirements: Windows, [uv](https://docs.astral.sh/uv/) (it installs the right Python version and all packages by itself), and the 3MTS software that comes with the teslameter.

### 1. Get the code and the teslameter library

```
git clone <this repository's URL>
cd <repository folder>
```

The teslameter manufacturer's library files are **not** in this repository, because they're the manufacturer's property. Copy them into the `drivers\` folder as described in [drivers/README.md](drivers/README.md).

### 2. Run from source

```
cd src
uv run StartPrinter.py
```

The first run downloads Python and the packages, which takes a few minutes. `config.ini` is created in `src\`.

### 3. Build the exe

Close any running `TeslameterPrinter.exe` first, then in the repository folder:

```
uv run pyinstaller --noconfirm TeslameterPrinter.spec
```

The finished program is the folder `dist\TeslameterPrinter\`. Hand out that whole folder. Building **replaces that folder**, so save `config.ini` and any `scan_*.txt` files from it first and copy them back afterwards.

The built folder contains the manufacturer's library files. Only pass it on to people who are allowed to use the 3MTS software, for example other users of the same device.

### Code overview

| File | Purpose |
|---|---|
| `src\StartPrinter.py` | Entry point: reads `config.ini`, starts the Tango device server, opens the GUI |
| `src\PrintDevice.py` | Tango device: printer control (via printrun), test run and measurement logic, teslameter readout |
| `src\Heatmap.py` | GUI: sample size dialog, heatmaps, buttons |
| `src\teslameterTest.py` | Loads the 3MTS teslameter library (`drivers\a3mtslib64.dll`) |
| `drivers\` | Teslameter library and its DLLs, bundled into the exe |

---

## License

The code in this repository is released under the [MIT License](LICENSE). The teslameter manufacturer's library files are not part of this repository and are not covered by that license.
