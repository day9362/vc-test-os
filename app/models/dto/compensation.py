from pydantic import BaseModel


class ChannelBiasItemOut(BaseModel):
    channel: str
    value: float


class ChannelBiasOut(BaseModel):
    measured_at: int
    golden_model: str
    samples: int
    threshold_c: float
    items: list[ChannelBiasItemOut]


class CompChannelOut(BaseModel):
    channel: str
    value: float


class CompensationOut(BaseModel):
    items: list[CompChannelOut]
