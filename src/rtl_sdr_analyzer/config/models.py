"""Pydantic configuration models with validation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SourceMode = Literal["auto", "usb", "rtl_tcp", "simulated", "file"]
WindowType = Literal["blackmanharris", "hann", "hamming", "rectangular"]


class SourceSettings(BaseModel):
    """RF input source settings."""

    mode: SourceMode = Field(default="auto")
    device_index: int = Field(default=0, ge=0)
    library_path: str | None = Field(default=None)
    replay_path: str | None = Field(default=None)


class RtlTcpSettings(BaseModel):
    """RTL-TCP server connection settings."""

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=1234, ge=1, le=65535)
    connect_timeout: float = Field(default=5.0, gt=0.0)
    read_timeout: float = Field(default=2.0, gt=0.0)


class ReceiverSettings(BaseModel):
    """Receiver hardware settings."""

    frequency: float = Field(default=98.0e6, gt=0.0)
    sample_rate: float = Field(default=2.048e6, ge=225_001.0, le=3_200_000.0)
    fft_size: int = Field(default=2048, ge=256, le=16384)
    gain: float | None = Field(default=None, ge=0.0, le=60.0)
    ppm: int = Field(default=0, ge=-500, le=500)
    direct_sampling: int = Field(default=0, ge=0, le=2)
    agc: bool = Field(default=False)

    @field_validator("fft_size")
    @classmethod
    def _power_of_two(cls, value: int) -> int:
        if value & (value - 1) != 0:
            raise ValueError("fft_size must be a power of 2")
        return value


class DspSettings(BaseModel):
    """Spectrum DSP settings."""

    window: WindowType = Field(default="blackmanharris")
    averaging: int = Field(default=4, ge=1, le=64)
    ema_alpha: float = Field(default=0.35, gt=0.0, le=1.0)
    remove_dc: bool = Field(default=True)


class DetectorSettings(BaseModel):
    """Signal detection algorithm settings."""

    enabled: bool = Field(default=True)
    power_threshold: float = Field(default=-55.0, ge=-140.0, le=10.0)
    snr_threshold: float = Field(default=10.0, ge=0.0, le=100.0)
    bandwidth_threshold: float = Field(default=5_000.0, ge=0.0)
    z_score_threshold: float = Field(default=3.0, gt=0.0)
    detection_window: int = Field(default=5, ge=1)
    min_duration: float = Field(default=0.2, ge=0.0)
    holdover_seconds: float = Field(default=0.5, ge=0.0)
    cooldown_seconds: float = Field(default=2.0, ge=0.0)
    test_mode: bool = Field(default=False)


class DisplaySettings(BaseModel):
    """Spectrum and waterfall display settings."""

    waterfall_length: int = Field(default=120, ge=10, le=500)
    target_fps: int = Field(default=20, ge=1, le=60)


class WebSettings(BaseModel):
    """Local web studio server settings."""

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8080, ge=1, le=65535)


class StorageSettings(BaseModel):
    """Persistence and recording paths."""

    db_path: str | None = Field(default=None)
    recordings_dir: str = Field(default="./recordings", min_length=1)


class Settings(BaseModel):
    """Root settings combining all subsystems.

    Environment variables are merged explicitly by :func:`load_settings`
    (``RTL_SDR__SECTION__FIELD``), so this is a plain model on purpose.
    """

    model_config = ConfigDict(extra="forbid")

    source: SourceSettings = Field(default_factory=SourceSettings)
    rtl_tcp: RtlTcpSettings = Field(default_factory=RtlTcpSettings)
    receiver: ReceiverSettings = Field(default_factory=ReceiverSettings)
    dsp: DspSettings = Field(default_factory=DspSettings)
    detector: DetectorSettings = Field(default_factory=DetectorSettings)
    display: DisplaySettings = Field(default_factory=DisplaySettings)
    web: WebSettings = Field(default_factory=WebSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
