import math

from app.core.config import settings
from app.models.dto.compensation import ChannelBiasItemOut, ChannelBiasOut

TEMP_CHANNELS = ["T0", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11", "T12", "T13", "T14", "Ta"]
SPECIAL = {("M07", "T1"): 0.182, ("M07", "Ta"): 0.052, ("M03", "T0"): 0.048, ("M10", "T5"): -0.074}
GOLDEN_MODEL = "HVP1307G17-1"
SAMPLES = 10


def estimate_channel_bias(machine_id: str, measured_at: int) -> ChannelBiasOut:
    n = int(machine_id[1:]) if len(machine_id) > 1 and machine_id[1:].isdigit() else 0
    items = []
    for index, channel in enumerate(TEMP_CHANNELS):
        value = SPECIAL.get((machine_id, channel))
        if value is None:
            value = round(math.sin(n * 3.1 + index * 1.7) * 0.03, 3)
        items.append(ChannelBiasItemOut(channel=channel, value=value))
    return ChannelBiasOut(
        measured_at=measured_at,
        golden_model=GOLDEN_MODEL,
        samples=SAMPLES,
        threshold_c=settings.drift_c,
        items=items,
    )
