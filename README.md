<div align="center">

# 📡 RTL-SDR Signal Analyzer & Jamming Detector

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![RTL-SDR](https://img.shields.io/badge/RTL--SDR-Compatible-orange.svg)](https://www.rtl-sdr.com)

*A real-time spectrum analyzer and signal detection tool leveraging RTL-SDR hardware for RF monitoring and jamming detection.*

[Features](#-features) • [Installation](#-installation) • [Usage](#-usage) • [Configuration](#%EF%B8%8F-configuration) • [Commands](#-commands) • [Examples](#-examples) • [Contributing](#-contributing)

</div>

---

## 📑 Table of Contents

- [Features](#-features)
- [Installation](#-installation)
  - [Prerequisites](#prerequisites)
  - [Setup with uv](#setup-with-uv-recommended)
  - [GUI Backend](#optional-gui-backend)
  - [Alternative pip](#alternative-using-pip)
- [Usage](#-usage)
  - [Quick Start](#quick-start-3-steps)
  - [Choose your mode](#2-choose-your-mode)
  - [Run the analyzer](#3-run-the-analyzer)
- [Commands](#-commands)
  - [`analyze`](#analyze--real-time-spectrum-analysis)
  - [`record`](#record--iq-sample-recording)
  - [`sweep`](#sweep--frequency-range-scanning)
  - [`stats`](#stats--statistics-dashboard)
  - [`config-validate`](#config-validate--validate-configuration)
  - [`config-show`](#config-show--display-resolved-configuration)
- [Configuration](#%EF%B8%8F-configuration)
  - [YAML Configuration](#1-yaml-configuration-file)
  - [Environment Variables](#2-environment-variables)
  - [CLI Flags](#3-cli-flags)
- [Examples](#-examples)
  - [FM Radio Monitoring](#example-1-fm-radio-monitoring)
  - [Walkie-Talkie Detection](#example-2-walkie-talkie-detection)
  - [GSM/LTE Analysis](#example-3-gsmlte-signal-analysis)
  - [Debug Mode](#example-4-debug-mode)
  - [Remote Server](#example-5-remote-server-setup)
  - [Custom Configs](#example-6-custom-config-per-band)
  - [IQ Recording](#example-7-iq-recording-for-offline-analysis)
  - [Frequency Sweep](#example-8-frequency-sweep)
  - [SQLite Storage](#example-9-sqlite-storage-and-stats)
- [Signal Patterns](#-common-signal-patterns)
- [Development](#-development)
- [Contributing](#-contributing)
- [License](#-license)

---

## ✨ Features

- 📊 **Real-time Visualization**: Advanced spectrum analysis with waterfall display
- 🔍 **Smart Detection**: Automatic signal anomaly and jamming detection
- 📈 **Dynamic Analysis**: Adaptive baseline calculation and threshold adjustment
- ⚙️ **Flexible Configuration**: Validated YAML config, env vars, and CLI overrides
- 🌐 **Network Support**: Built-in RTL-TCP compatibility for remote operation
- 🖥️ **GUI & Headless**: Interactive matplotlib plots or console-only daemon mode
- 📤 **Event Export**: Save detections to CSV or JSON Lines
- 💾 **SQLite Storage**: Persistent event storage with rich statistics dashboard
- 📻 **IQ Recording**: Capture raw IQ samples for offline analysis
- 🔄 **Frequency Sweeping**: Scan wide frequency ranges automatically
- 🧪 **Well Tested**: 60+ tests with 85%+ coverage

---

## 🚀 Installation

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.9+ | Required for modern type hints |
| RTL-SDR | Any | USB dongle with RTL2832U chipset |
| Docker | Latest | For RTL-TCP server container |
| Docker Compose | Latest | Included with Docker Desktop |

### Setup with `uv` (Recommended)

We recommend using [`uv`](https://docs.astral.sh/uv/) for fast environment management:

```bash
# Clone the repository
git clone https://github.com/msalexms/rtl-sdr-analyzer.git
cd rtl-sdr-analyzer

# Create virtual environment and install
uv venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install core dependencies + dev tools
uv pip install -e ".[dev,test]"

# Verify installation
rtl-sdr-analyzer --help
```

### Optional: GUI Backend

For interactive matplotlib plots, install a GUI backend:

```bash
uv pip install -e ".[gui]"  # Installs PyQt6
```

If no GUI backend is available, the analyzer **automatically falls back to headless mode** with a warning.

### Alternative: Using `pip`

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,test]"
```

---

## 💻 Usage

### Quick Start (3 steps)

#### 1. Start the RTL-TCP server

The server connects to your RTL-SDR hardware and streams IQ data over TCP:

```bash
cd docker
docker-compose up -d
```

Verify it's running:
```bash
docker ps
nc -zv 127.0.0.1 1234
```

#### 2. Choose your mode

| Mode | Use Case | Command |
|---|---|---|
| **GUI** | Interactive analysis with plots | `rtl-sdr-analyzer analyze --freq 98e6` |
| **Headless** | Server/daemon, remote monitoring | `rtl-sdr-analyzer analyze --headless --freq 98e6` |
| **Export** | Log detections to file | Add `--export-format csv --export-path events.csv` |
| **Database** | Persistent storage + stats | Add `--db-path events.db` |

#### 3. Run the analyzer

```bash
# Basic GUI mode (local server)
rtl-sdr-analyzer analyze --freq 98e6 --host 127.0.0.1

# Headless mode with CSV logging
rtl-sdr-analyzer analyze --headless \
  --freq 446e6 \
  --host 127.0.0.1 \
  --export-format csv \
  --export-path events.csv

# With SQLite persistence for later stats
rtl-sdr-analyzer analyze --headless \
  --freq 915e6 \
  --db-path events.db
```

---

## 🎮 Commands

### `analyze` — Real-time Spectrum Analysis

The main command. Connects to RTL-TCP, processes IQ samples, detects signals, and visualizes or logs results.

**Syntax:**
```bash
rtl-sdr-analyzer analyze [OPTIONS]
```

#### Connection Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--host` | | RTL-TCP server hostname/IP | `192.168.31.34` |
| `--port` | | RTL-TCP server port | `1234` |

#### Receiver Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--freq` | | Center frequency in Hz (e.g. `98e6`, `446000000`) | `915e6` |
| `--sample-rate` | | Sample rate in Hz | `2.048e6` |
| `--fft-size` | | FFT size (power of 2) | `2048` |

#### Detection Options

| Option | Description | Default |
|--------|-------------|---------|
| `--power-threshold` | Minimum signal power in dB | `-70` |
| `--bandwidth-threshold` | Minimum signal bandwidth in Hz | `100000` |
| `--z-score-threshold` | Statistical deviation threshold | `1.5` |
| `--detection-window` | Frames for baseline calculation | `5` |
| `--min-duration` | Minimum event duration in seconds | `0.1` |
| `--test-mode` | Enable sensitive detection (any criterion triggers) | `false` |

#### Display Options

| Option | Description | Default |
|--------|-------------|---------|
| `--waterfall-length` | Waterfall history length | `50` |
| `--update-interval` | Plot update interval in ms | `50` |
| `--headless` | Run without GUI (console only) | `false` |

#### Export Options

| Option | Description | Default |
|--------|-------------|---------|
| `--export-format` | Export format: `csv` or `json` | — |
| `--export-path` | File path for exported events | — |

#### Storage Options

| Option | Description | Default |
|--------|-------------|---------|
| `--db-path` | SQLite database path for persistent event storage | — |

#### Logging Options

| Option | Description | Default |
|--------|-------------|---------|
| `--log-level` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `--log-format` | Log format: `text` or `json` | `text` |
| `--config` | `-c` | Path to YAML config file | `config/default.yml` |

**Examples:**

```bash
# Monitor FM radio band with GUI
rtl-sdr-analyzer analyze --freq 98e6 --host 127.0.0.1

# Monitor walkie-talkies (446 MHz) headless with CSV export and SQLite
rtl-sdr-analyzer analyze --headless \
  --freq 446e6 \
  --host 127.0.0.1 \
  --export-format csv \
  --export-path walkie_events.csv \
  --db-path events.db

# High-sensitivity detection for weak signals
rtl-sdr-analyzer analyze --headless \
  --freq 915e6 \
  --power-threshold -80 \
  --z-score-threshold 1.0 \
  --min-duration 0.05

# Test mode (more sensitive, good for debugging)
rtl-sdr-analyzer analyze --headless \
  --freq 98e6 \
  --test-mode \
  --log-level DEBUG

# Remote server (not localhost)
rtl-sdr-analyzer analyze \
  --host 192.168.1.50 \
  --port 1234 \
  --freq 446e6
```

**Output Example (Headless):**

```
2026-04-27T09:19:07.821925Z [info     ] Starting signal analyzer...
2026-04-27T09:19:07.822081Z [info     ] Connecting to RTL-TCP server at 127.0.0.1:1234
2026-04-27T09:19:07.822307Z [info     ] Successfully connected to RTL-TCP server
2026-04-27T09:19:08.123456Z [info     ] Spectrum stats [10] | mean=-78.5 dB | min=-92.1 dB | max=-45.2 dB
2026-04-27T09:19:08.234567Z [info     ] DETECTION | freq=445.987 MHz | power=-45.2 dB | bw=12500 Hz | dur=0.15 s | conf=2.34
```

---

### `record` — IQ Sample Recording

Record raw IQ samples to a file for offline analysis with GNU Radio or custom scripts.

```bash
rtl-sdr-analyzer record output.raw --duration 30 --freq 915e6 --host 127.0.0.1
```

| Option | Description | Default |
|--------|-------------|---------|
| `output` | Output file path (required) | — |
| `--duration` | Recording duration in seconds | `10.0` |
| `--format` | Output format: `raw` or `numpy` | `raw` |
| `--freq` | Center frequency | `915e6` |
| `--host` | RTL-TCP host | `192.168.31.34` |
| `--port` | RTL-TCP port | `1234` |

**Formats:**
- **`raw`**: Interleaved uint8 I/Q data. Compatible with `rtl_sdr`, GNU Radio, and most SDR tools.
- **`numpy`**: `.npz` file with complex64 array + metadata (sample rate, frequency, timestamp).

**Examples:**

```bash
# Record 60 seconds for later analysis
rtl-sdr-analyzer record capture.raw --duration 60 --freq 446e6 --host 127.0.0.1

# Record in NumPy format
rtl-sdr-analyzer record capture.npz --duration 30 --format numpy --freq 915e6
```

---

### `sweep` — Frequency Range Scanning

Automatically scan a frequency range with configurable step and dwell time, detecting signals at each stop.

```bash
rtl-sdr-analyzer sweep START_HZ END_HZ [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `start_freq` | Start frequency in Hz (required) | — |
| `end_freq` | End frequency in Hz (required) | — |
| `--step` | Frequency step in Hz | `1e6` |
| `--dwell` | Dwell time per frequency in seconds | `2.0` |
| `--host` | RTL-TCP host | `192.168.31.34` |
| `--port` | RTL-TCP port | `1234` |
| `--sample-rate` | Sample rate | `2.048e6` |
| `--power-threshold` | Power threshold | `-70` |
| `--headless` | Run without GUI | `true` |
| `--export-format` | Export format | — |
| `--export-path` | Export file path | — |
| `--db-path` | SQLite database path | — |

**Examples:**

```bash
# Scan 400-500 MHz for walkie-talkies
rtl-sdr-analyzer sweep 400e6 500e6 --step 1e6 --dwell 2.0 --host 127.0.0.1

# Fine-grained sweep with CSV export
rtl-sdr-analyzer sweep 88e6 108e6 \
  --step 0.5e6 \
  --dwell 1.0 \
  --export-format csv \
  --export-path fm_sweep.csv

# Sweep with database persistence
rtl-sdr-analyzer sweep 400e6 500e6 --step 1e6 --db-path sweep.db
```

---

### `stats` — Statistics Dashboard

Display rich statistics from a SQLite database created with `--db-path`.

```bash
rtl-sdr-analyzer stats DB_PATH [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `db_path` | Path to SQLite database | `rtl_sdr_analyzer.db` |
| `--top-freqs` | Show top frequencies by activity | `true` |
| `--hourly` | Show hourly activity chart | `true` |
| `--recent` | Number of recent events to show | `10` |
| `--export-csv` | Export events to CSV file | — |
| `--since-hours` | Filter events by last N hours | — |

**Examples:**

```bash
# Show full dashboard
rtl-sdr-analyzer stats events.db

# Export last 24h to CSV
rtl-sdr-analyzer stats events.db --export-csv yesterday.csv --since-hours 24

# Show only summary and recent events
rtl-sdr-analyzer stats events.db --top-freqs=false --hourly=false --recent 20
```

**Dashboard Output:**
```
📊 RTL-SDR Analyzer Statistics
==================================================
Total detection events: 1542
Events in last 24h: 87
Recent sessions: 3

🔥 Top Frequencies by Activity
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Frequency (MHz) ┃ Detections ┃ Avg Power (dB) ┃ Max Power (dB) ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ 445.987         │ 523        │ -52.3          │ -30.1          │
│ 98.100          │ 412        │ -65.1          │ -45.2          │
│ 446.125         │ 607        │ -48.7          │ -28.9          │
└─────────────────┴────────────┴────────────────┴────────────────┘

📈 Hourly Activity (Last 24h)
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Hour                ┃ Detections ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ 2026-04-27 10:00    │ 12         │
│ 2026-04-27 11:00    │ 35         │
│ 2026-04-27 12:00    │ 40         │
└─────────────────────┴────────────┘
```

---

### `config-validate` — Validate Configuration

Validate a YAML configuration file against the Pydantic schema.

```bash
# Validate default config
rtl-sdr-analyzer config-validate config/default.yml

# Validate custom config
rtl-sdr-analyzer config-validate my-config.yml
```

**Output:**
```
Configuration is valid.
{
  "rtl_tcp": {
    "host": "192.168.31.34",
    "port": 1234
  },
  "receiver": {
    "frequency": 915000000.0,
    ...
  }
}
```

If invalid, you'll see detailed error messages:
```
Configuration error: 1 validation error for Settings
receiver.frequency
  Input should be greater than 0 [type=greater_than, input_value=-1, input_type=int]
```

---

### `config-show` — Display Resolved Configuration

Shows the final configuration after merging all sources (defaults → YAML → env vars → CLI).

```bash
# Show as YAML (default)
rtl-sdr-analyzer config-show

# Show as JSON
rtl-sdr-analyzer config-show --format json

# Show with custom config file
rtl-sdr-analyzer config-show --config my-config.yml --format json
```

**Useful for debugging** to verify that your env vars and CLI flags are being applied correctly.

---

## ⚙️ Configuration

Configuration follows a cascading priority (lowest → highest):

```
Code Defaults → YAML File → Environment Variables → CLI Flags
```

### 1. YAML Configuration File

Create a custom config file:

```yaml
# my-config.yml
rtl_tcp:
  host: "127.0.0.1"
  port: 1234

receiver:
  frequency: 98000000    # 98 MHz - FM Radio
  sample_rate: 2048000   # 2.048 MHz
  fft_size: 2048

detector:
  power_threshold: -70.0
  bandwidth_threshold: 100000    # 100 kHz
  z_score_threshold: 1.5
  detection_window: 5
  min_duration: 0.1
  test_mode: false

display:
  waterfall_length: 50
  update_interval: 50
```

Use it:
```bash
rtl-sdr-analyzer analyze --config my-config.yml
```

### 2. Environment Variables

Prefix with `RTL_SDR__` and use double underscores for nesting:

```bash
# Override frequency
export RTL_SDR__RECEIVER__FREQUENCY=446000000

# Override host
export RTL_SDR__RTL_TCP__HOST=192.168.1.50

# Enable test mode
export RTL_SDR__DETECTOR__TEST_MODE=true

# Then run (picks up env vars automatically)
rtl-sdr-analyzer analyze
```

See `.env.example` for all available variables.

### 3. CLI Flags

Highest priority. Override any other source:

```bash
# Override just frequency and threshold
rtl-sdr-analyzer analyze \
  --config my-config.yml \
  --freq 915e6 \
  --power-threshold -65
```

---

## 📚 Examples

### Example 1: FM Radio Monitoring

```bash
# Monitor 98 MHz with GUI
rtl-sdr-analyzer analyze --freq 98e6 --host 127.0.0.1

# Monitor with CSV export for later analysis
rtl-sdr-analyzer analyze --headless \
  --freq 98e6 \
  --host 127.0.0.1 \
  --export-format csv \
  --export-path fm_events.csv \
  --power-threshold -60
```

### Example 2: Walkie-Talkie Detection

```bash
# Headless monitoring with JSON export and SQLite
rtl-sdr-analyzer analyze --headless \
  --freq 446e6 \
  --host 127.0.0.1 \
  --export-format json \
  --export-path walkie_events.jsonl \
  --db-path walkie.db \
  --bandwidth-threshold 50000 \
  --min-duration 0.2

# View stats afterward
rtl-sdr-analyzer stats walkie.db
```

### Example 3: GSM/LTE Signal Analysis

```bash
# Monitor GSM band (around 900-1800 MHz depending on region)
rtl-sdr-analyzer analyze --headless \
  --freq 950e6 \
  --sample-rate 2.4e6 \
  --power-threshold -75 \
  --detection-window 10
```

### Example 4: Debug Mode

```bash
# Very sensitive detection with debug logging
rtl-sdr-analyzer analyze --headless \
  --freq 915e6 \
  --test-mode \
  --log-level DEBUG \
  --log-format text
```

### Example 5: Remote Server Setup

```bash
# Server runs RTL-TCP on 192.168.1.50
# Client connects from another machine
rtl-sdr-analyzer analyze \
  --host 192.168.1.50 \
  --port 1234 \
  --freq 446e6 \
  --headless
```

### Example 6: Custom Config per Band

Create `config/fm-radio.yml`:
```yaml
receiver:
  frequency: 98000000
  sample_rate: 2048000

detector:
  power_threshold: -60
  bandwidth_threshold: 150000
```

Create `config/walkie-talkie.yml`:
```yaml
receiver:
  frequency: 446000000
  sample_rate: 2048000

detector:
  power_threshold: -70
  bandwidth_threshold: 25000
  min_duration: 0.2
```

Switch between them:
```bash
rtl-sdr-analyzer analyze --config config/fm-radio.yml
rtl-sdr-analyzer analyze --config config/walkie-talkie.yml
```

### Example 7: IQ Recording for Offline Analysis

```bash
# Record 60 seconds of raw IQ data
rtl-sdr-analyzer record capture.raw \
  --duration 60 \
  --freq 446e6 \
  --host 127.0.0.1

# Record in NumPy format for Python analysis
rtl-sdr-analyzer record capture.npz \
  --duration 30 \
  --format numpy \
  --freq 915e6

# Load in Python later
python -c "import numpy as np; d = np.load('capture.npz'); print(d['iq'][:10])"
```

### Example 8: Frequency Sweep

```bash
# Scan 400-500 MHz for walkie-talkies
rtl-sdr-analyzer sweep 400e6 500e6 \
  --step 1e6 \
  --dwell 2.0 \
  --host 127.0.0.1 \
  --export-format csv \
  --export-path sweep_results.csv

# Fine-grained FM radio sweep
rtl-sdr-analyzer sweep 88e6 108e6 \
  --step 0.5e6 \
  --dwell 1.0 \
  --db-path fm_sweep.db

# View sweep stats
rtl-sdr-analyzer stats fm_sweep.db --top-freqs --hourly
```

### Example 9: SQLite Storage and Stats

```bash
# Run analyzer with persistent storage
rtl-sdr-analyzer analyze --headless \
  --freq 915e6 \
  --host 127.0.0.1 \
  --db-path monitoring.db

# Let it run for a while, then check stats
rtl-sdr-analyzer stats monitoring.db

# Export last 24 hours to CSV
rtl-sdr-analyzer stats monitoring.db \
  --export-csv yesterday.csv \
  --since-hours 24

# Show only top frequencies
rtl-sdr-analyzer stats monitoring.db --hourly=false --recent=0
```

---

## 🔧 Common Signal Patterns

| Signal Type | Frequency Range | Characteristics |
|-------------|-----------------|-----------------|
| 📻 **FM Radio** | 88-108 MHz | Strong, stable, wide bandwidth |
| 📱 **GSM/LTE** | 700-2600 MHz | Wide-band, intermittent |
| 🛜 **Wi-Fi** | 2.4/5 GHz | Periodic bursts (need downconverter) |
| 🎮 **RF Remotes** | 315/433/868 MHz | Brief, narrow-band |
| 🚗 **Walkie-Talkies** | 446 MHz | Short bursts, medium bandwidth |

---

## 🧪 Development

```bash
# Run all tests with coverage
pytest

# Run specific test file
pytest tests/unit/test_detector.py -v

# Linting
ruff check src tests
ruff format src tests

# Type checking
mypy --strict src

# Run with coverage report
pytest --cov=rtl_sdr_analyzer --cov-report=html
```

---

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'feat: add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">
<p>Developed with ❤️ by RF enthusiasts</p>

[Report Bug](https://github.com/msalexms/rtl-sdr-analyzer/issues) • [Request Feature](https://github.com/msalexms/rtl-sdr-analyzer/issues)
</div>
