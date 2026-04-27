<div align="center">

# 📡 RTL-SDR Signal Analyzer & Jamming Detector

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![RTL-SDR](https://img.shields.io/badge/RTL--SDR-Compatible-orange.svg)](https://www.rtl-sdr.com)

*A real-time spectrum analyzer and signal detection tool leveraging RTL-SDR hardware for RF monitoring and jamming detection.*

[Features](#-features) • [Installation](#-installation) • [Usage](#-usage) • [Configuration](#%EF%B8%8F-configuration) • [Commands](#-commands) • [Examples](#-examples) • [Contributing](#-contributing)

</div>

---

## ✨ Features

- 📊 **Real-time Visualization**: Advanced spectrum analysis with waterfall display
- 🔍 **Smart Detection**: Automatic signal anomaly and jamming detection
- 📈 **Dynamic Analysis**: Adaptive baseline calculation and threshold adjustment
- ⚙️ **Flexible Configuration**: Validated YAML config, env vars, and CLI overrides
- 🌐 **Network Support**: Built-in RTL-TCP compatibility for remote operation
- 🖥️ **GUI & Headless**: Interactive matplotlib plots or console-only daemon mode
- 📤 **Event Export**: Save detections to CSV or JSON Lines
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

# Custom detection parameters
rtl-sdr-analyzer analyze --headless \
  --freq 915e6 \
  --power-threshold -65 \
  --bandwidth-threshold 50000 \
  --z-score-threshold 2.0
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

# Monitor walkie-talkies (446 MHz) headless with CSV export
rtl-sdr-analyzer analyze --headless \
  --freq 446e6 \
  --host 127.0.0.1 \
  --export-format csv \
  --export-path walkie_events.csv

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

### `record` — Record IQ Samples

Record raw IQ data to a file for offline analysis.

**Note:** This command is currently a stub. Implementation coming in a future release.

```bash
rtl-sdr-analyzer record output.iq --duration 30 --freq 915e6
```

| Option | Description | Default |
|--------|-------------|---------|
| `output` | Output file path (required) | — |
| `--duration` | Recording duration in seconds | `10.0` |
| `--freq` | Center frequency | `915e6` |
| `--host` | RTL-TCP host | `192.168.31.34` |
| `--port` | RTL-TCP port | `1234` |

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

### Example 1: FM Radio Monitoring (88-108 MHz)

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

### Example 2: Walkie-Talkie Detection (446 MHz)

```bash
# Headless monitoring with JSON export
rtl-sdr-analyzer analyze --headless \
  --freq 446e6 \
  --host 127.0.0.1 \
  --export-format json \
  --export-path walkie_events.json \
  --bandwidth-threshold 50000 \
  --min-duration 0.2
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

### Example 4: Debug Mode with Test Detection

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

### Example 6: Using Custom Config for Different Bands

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
