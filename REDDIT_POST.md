I built a lightweight Python spectrum analyzer for RTL-SDR — real-time, auto-detection, and sweep mode

---

Hey r/RTLSDR! I've been working on a CLI-first spectrum analyzer and wanted to share it with the community. It's designed to be lightweight and scriptable for automated monitoring.

**What it does:**
- Real-time spectrum + waterfall (GUI or headless over SSH)
- Automatic signal detection with adaptive noise floor
- Frequency sweeping across ranges with CSV/SQLite export
- IQ recording (.raw for GNU Radio, .npz for NumPy)
- SQLite storage with terminal stats dashboard

**Example usage:**
```bash
# Basic monitoring
rtl-sdr-analyzer analyze --freq 446e6 --headless

# Sweep 400-500 MHz
rtl-sdr-analyzer sweep 400e6 500e6 --step 1e6 --db-path scan.db

# View stats
rtl-sdr-analyzer stats scan.db
```

**Tech stack:** Python, Typer, Pydantic, matplotlib, SQLite + Rich

GitHub (MIT, open to contributions): https://github.com/msalexms/rtl-sdr-analyzer

Right now it works over RTL-TCP (tested with the rtl-sdr Docker container). Feedback and contributions are very welcome — what would make this more useful for your setups?
