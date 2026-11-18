# Teslameter library files

The files from the teslameter manufacturer belong in this folder. They are not included in this repository because they are the manufacturer's property.

Copy these five files from the `python example` folder of the 3MTS software that comes with the teslameter into this folder:

- `a3mtslib64.dll` (the teslameter library)
- `USBIOLIB.dll`
- `libgcc_s_seh-1.dll`
- `libstdc++-6.dll`
- `libwinpthread-1.dll`

The other files in that folder are not needed. Copying them too does no harm.

The program and the exe build both look for `drivers\a3mtslib64.dll`.
