from pydantic import BaseModel, Field


class LimitInput(BaseModel):
    item: str = Field(description="判定项，例如 Temp_T0-T1、power_w")
    low: float | None = None
    high: float | None = None
    unit: str = ""
    skipped: bool = False


class PlanInput(BaseModel):
    name: str
    start_temp_c: float = Field(description="起测温度 ℃")
    duration_s: int = Field(description="测试时长 1–600 秒")
    sample_period_s: float = Field(description="采样周期 秒")
    power_w: float = Field(description="加热功率 0.1–10 W")
    force_g: float = Field(description="压紧力 20–300 g")
    orientation: int = Field(description="放置角度：0 平放、90 竖放")
    overtemp_c: float = Field(description="超温保护 ℃")
    ambient_low_c: float
    ambient_high_c: float
    limits: list[LimitInput] = Field(default_factory=list)


class ChannelValue(BaseModel):
    channel: str = Field(description="通道，例如 T0、T1")
    value: float = Field(description="补偿量 ℃")
