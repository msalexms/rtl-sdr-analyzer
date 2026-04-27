"""Pydantic configuration models with validation."""

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RtlTcpSettings(BaseModel):
    """RTL-TCP server connection settings."""

    host: str = Field(default="192.168.31.34", min_length=1)
    port: int = Field(default=1234, ge=1, le=65535)


class ReceiverSettings(BaseModel):
    """Receiver hardware settings."""

    frequency: float = Field(default=915e6, gt=0)
    sample_rate: float = Field(default=2.048e6, gt=0)
    fft_size: int = Field(default=2048, gt=0)

    @field_validator("fft_size")
    @classmethod
    def _power_of_two(cls, v: int) -> int:
        if v & (v - 1) != 0:
            raise ValueError("fft_size must be a power of 2")
        return v


class DetectorSettings(BaseModel):
    """Signal detection algorithm settings."""

    power_threshold: float = Field(default=-70.0)
    bandwidth_threshold: float = Field(default=0.1e6, gt=0)
    z_score_threshold: float = Field(default=1.5, gt=0)
    detection_window: int = Field(default=5, ge=1)
    min_duration: float = Field(default=0.1, gt=0)
    test_mode: bool = Field(default=False)


class DisplaySettings(BaseModel):
    """Visualization display settings."""

    waterfall_length: int = Field(default=50, ge=1)
    update_interval: int = Field(default=50, ge=10)


class Settings(BaseSettings):
    """Root settings combining all subsystems."""

    model_config = SettingsConfigDict(
        env_prefix="RTL_SDR_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    rtl_tcp: RtlTcpSettings = Field(default_factory=RtlTcpSettings)
    receiver: ReceiverSettings = Field(default_factory=ReceiverSettings)
    detector: DetectorSettings = Field(default_factory=DetectorSettings)
    display: DisplaySettings = Field(default_factory=DisplaySettings)
