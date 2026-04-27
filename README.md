<div align="center">

# 📡 RTL-SDR Signal Analyzer & Jamming Detector

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![RTL-SDR](https://img.shields.io/badge/RTL--SDR-Compatible-orange.svg)](https://www.rtl-sdr.com)

*A real-time spectrum analyzer and signal detection tool leveraging RTL-SDR hardware for RF monitoring and jamming detection.*

[Features](#-features) • [Installation](#-installation) • [Usage](#-usage) • [Configuration](#%EF%B8%8F-configuration) • [Contributing](#-contributing)

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

## 🚀 Installation

### Prerequisites

- Python 3.9 or newer
- RTL-SDR hardware
- Docker & Docker Compose (for RTL-TCP server)

### Setup

We recommend using [`uv`](https://docs.astral.sh/uv/) for fast environment management:

```bash
# Clone the repository
git clone https://github.com/msalexms/rtl-sdr-analyzer.git
cd rtl-sdr-analyzer

# Create virtual environment and install
uv venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

uv pip install -e ".[dev,test]"
```

### Optional: GUI Backend

For interactive matplotlib plots, install a GUI backend:

```bash
uv pip install -e ".[gui]"  # Installs PyQt6
```

If no GUI backend is available, the analyzer automatically falls back to **headless mode**.

## 💻 Usage

### 1. Start the RTL-TCP server

```bash
cd docker
docker-compose up -d
```

### 2. Run the analyzer

```bash
# Interactive GUI mode (requires GUI backend + DISPLAY)
rtl-sdr-analyzer analyze --freq 98e6 --host 127.0.0.1

# Headless mode (console logs only)
rtl-sdr-analyzer analyze --headless --freq 98e6 --host 127.0.0.1

# With CSV export
rtl-sdr-analyzer analyze --headless \
  --freq 446e6 \
  --export-format csv \
  --export-path events.csv
```

### Commands

| Command | Description |
|---------|-------------|
| `analyze` | Run real-time spectrum analysis |
| `record` | Record raw IQ samples to file (stub) |
| `config-validate` | Validate a YAML configuration file |
| `config-show` | Display resolved configuration |

### CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `--config` | Path to configuration file | `config/default.yml` |
| `--host` | RTL-TCP server host | `192.168.31.34` |
| `--port` | RTL-TCP server port | `1234` |
| `--freq` | Center frequency (Hz) | `915e6` |
| `--sample-rate` | Sample rate (Hz) | `2.048e6` |
| `--fft-size` | FFT size | `2048` |
| `--power-threshold` | Signal power threshold (dB) | `-70` |
| `--bandwidth-threshold` | Minimum bandwidth (Hz) | `100000` |
| `--z-score-threshold` | Statistical deviation threshold | `1.5` |
| `--detection-window` | Analysis window (samples) | `5` |
| `--min-duration` | Minimum event duration (s) | `0.1` |
| `--test-mode` | Enable sensitive detection | `false` |
| `--headless` | Run without GUI | `false` |
| `--export-format` | Export format: `csv` or `json` | — |
| `--export-path` | Path for exported events | — |
| `--log-level` | Logging level | `INFO` |
| `--log-format` | Log format: `text` or `json` | `text` |

### Configuration

Configuration follows this priority (lowest → highest):

1. **Defaults** baked into the code
2. **YAML file** (`config/default.yml` or `--config`)
3. **Environment variables** (`RTL_SDR__RECEIVER__FREQUENCY=98000000`)
4. **CLI flags** (`--freq 98e6`)

Example `config/default.yml`:

```yaml
rtl_tcp:
  host: "192.168.31.34"
  port: 1234

receiver:
  frequency: 915000000  # 915 MHz
  sample_rate: 2048000  # 2.048 MHz
  fft_size: 2048

detector:
  power_threshold: -70.0
  bandwidth_threshold: 100000
  z_score_threshold: 1.5
  detection_window: 5
  min_duration: 0.1
  test_mode: false

display:
  waterfall_length: 50
  update_interval: 50
```

Validate your config:

```bash
rtl-sdr-analyzer config-validate my-config.yml
```

Show resolved config:

```bash
rtl-sdr-analyzer config-show --format json
```

## 🧪 Development

```bash
# Run tests
pytest

# Linting
ruff check src tests
ruff format src tests

# Type checking
mypy --strict src
```

## 📊 Signal Analysis Examples

### Walkie-Talkie Transmission (446 MHz)
![446 MHz Spectrogram](spectrogram.png)
*Spectrogram showing distinct signal patterns during walkie-talkie transmission at 446 MHz*

### Common Signal Patterns
- 📱 **GSM/LTE**: Characteristic wide-band signals
- 📻 **FM Radio**: Strong, stable signals in the 88-108 MHz range
- 🛜 **Wi-Fi**: Periodic bursts in the 2.4/5 GHz bands
- 🎮 **RF Remote Controls**: Brief, narrow-band transmissions

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'feat: add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">
<p>Developed with ❤️ by RF enthusiasts</p>

[Report Bug](https://github.com/msalexms/rtl-sdr-analyzer/issues) • [Request Feature](https://github.com/msalexms/rtl-sdr-analyzer/issues)
</div>
