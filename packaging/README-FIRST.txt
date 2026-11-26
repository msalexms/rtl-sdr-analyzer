rtl-sdr-analyzer (beta) - standalone build
==========================================

Start it, and the Web Studio opens in your browser at http://127.0.0.1:8080
No dongle? It starts in Demo RF mode, so you can explore right away.
Close the console window (or press Ctrl+C) to stop it.

Recordings are saved in a "recordings" folder next to where you start it.


WINDOWS
-------
1. Run rtl-sdr-analyzer.exe (double click).
2. First time with a dongle: install the WinUSB driver with Zadig
   (https://zadig.akeo.ie -> Options > List All Devices -> "Bulk-In, Interface (Interface 0)"
   -> WinUSB -> Replace Driver).
3. "Windows protected your PC": this beta is not code-signed yet.
   Click "More info" -> "Run anyway".
The RTL-SDR driver library (rtlsdr.dll, RTL-SDR Blog build, supports V3/V4) is included.


macOS
-----
1. Install the dongle library:       brew install librtlsdr
2. Allow the unsigned beta to run:   xattr -dr com.apple.quarantine rtl-sdr-analyzer
3. Start it:                         ./rtl-sdr-analyzer/rtl-sdr-analyzer --open
(Terminal: "serve --open" is the default when no command is given.)


LINUX
-----
1. Install the dongle library:       sudo apt install librtlsdr0 rtl-sdr   (Debian/Ubuntu)
                                     sudo dnf install rtl-sdr              (Fedora)
2. If the dongle is "busy": the DVB-T TV driver grabbed it. Run once:
       echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtl.conf
   then unplug and replug the dongle (the rtl-sdr package installs the udev rules).
3. Start it:                         ./rtl-sdr-analyzer/rtl-sdr-analyzer --open


Useful commands (all platforms):
  rtl-sdr-analyzer devices                 check library + dongles
  rtl-sdr-analyzer serve --source simulated --open
  rtl-sdr-analyzer --help

Prefer a normal Python install?  pipx install --pip-args=--pre rtl-sdr-analyzer
Docs, issues and source: https://github.com/msalexms/rtl-sdr-analyzer
