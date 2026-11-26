# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Fixed
- **Gapless live IQ recording & real-time `rtl_tcp`**: the engine read only `fft_size × averaging` samples per frame (~8 % of the stream), so Web Studio recordings had gaps and `rtl_tcp` drifted behind real time. Real-time sources and active recordings are now drained completely.
- **Spectrum/sweep plots no longer hide narrow carriers** when there are more FFT bins than pixels (per-column max decimation, as the waterfall already did).
- **SQLite**: one persistent connection instead of a new connection + PRAGMAs per event; `:memory:` databases now keep their data.
- **NumPy (`.npz`) recordings stream to disk** instead of buffering every sample in RAM (~1 GB/min at 2 MSPS).

### Security
- Web Studio rejects cross-site requests (`Origin` ≠ `Host`) and, when bound to loopback, non-loopback `Host` headers — other websites can no longer retune the radio, start recordings or delete events (CSRF / DNS rebinding).
- UI renders device names, filenames and server messages as text instead of HTML.

### Changed
- Web Studio: pause state synced from the server (consistent across tabs), connection/reconnecting indicator with backoff, sweep updates via WebSocket only (resync on reconnect), `#live` / `#sweep` / `#events` deep links, Events tab live refresh, confirmation before clearing events, toasts for recording start/stop, `A` shortcut for auto scale, translated source dialog, accessible close buttons and keyboard-navigable tables, persisted waterfall colormap.

### Removed
- Dead code: `HeadlessVisualization`, `VisualizationStrategy`, `JammingEvent` alias, `SignalProcessor.calculate_signal_metrics`, no-op `analyze --headless` flag, and the unused `pydantic-settings` dependency (`Settings` is now a plain model; env vars are still merged by the loader).

## [3.0.0] - 2026-11-26

### Added
- **AMSTech Design System v1.5**: Custom Thor RF Scope brand emblem/sticker, EN/ES banners, seals, vendored `amstech-ui` fonts/tokens/components, warm Day (`#FFF6E9`) and soft Graphite Night (`#18181D`) themes, and bilingual (`EN / ES`) Web Studio UI.
- **Direct USB RTL-SDR support (`LocalUsbSource`)**: Pure-Python `ctypes` bindings for `librtlsdr` with automatic library discovery across Linux, macOS, and Windows (including sibling DLL directory handling), hardware tuner gain snapping, and safe buffer flushes.
- **Simulated RF & File Replay sources**: Realistic multi-band virtual RF carriers (`SimulatedSource`) and `.raw`/`.cu8`/`.npz` replay (`FileReplaySource`) for hardware-free demos and offline inspection.
- **FastAPI + WebSocket Web Studio (`web/`)**: Low-latency `Int16` Base64 spectrum & waterfall streaming, interactive HTML5 Canvas displays, live tuning/gain/DSP/detector controls, wideband frequency sweeper tab, live IQ recording tap, and detection history/export tab.
- **`devices` & `serve` CLI commands**: Default CLI invocation now launches the Web Studio; `devices` reports `librtlsdr` discovery and attached dongles.
- **Production `Dockerfile` & updated `docker-compose.yml`**.

### Changed
- **Calibrated DSP (`dsp/processor.py`)**: Replaced `scipy` cross-bin Butterworth smoothing with pure-NumPy coherent-gain calibrated dBFS Welch FFT averaging and linear-domain EMA smoothing.
- **Proper `rtl_tcp` protocol (`sources/rtl_tcp.py`)**: Implemented 12-byte `RTL0` handshake, fixed command opcodes (`0x05` PPM, `0x08` AGC, `0x09` direct sampling with default `0`), and byte-aligned `bytearray` packet framing.
- **Adaptive Detector (`detection/detector.py`)**: Median/MAD noise floor baseline protected against self-poisoning during active transmissions, contiguous `-3 dB` bandwidth, holdover, anti-spam cooldown, and UTC timestamps.
- **Thread-safe Storage & Recording**: WAL-mode SQLite with automatic v2→v3 schema migration, accurate per-session event counts, clipped `uint8` raw IQ recording, and complete `.npz` metadata.

### Removed
- Removed legacy `matplotlib`, `PyQt6`, `scipy`, `core/`, `orchestrator/`, and `visualization/plotter.py`.
