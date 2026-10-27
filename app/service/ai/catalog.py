MODULES = (
    {"id": "agent.analysis", "name": "跨批次分析", "where": "AI Agent", "desc": "按型号、批次、机台和方案对比差异", "model": "deepseek-v3", "trigger": "用户"},
    {"id": "agent.plan", "name": "方案生成", "where": "测试方案", "desc": "把一句话整理成方案草稿", "model": "qwen3-max", "trigger": "用户"},
    {"id": "agent.ops", "name": "设备操作", "where": "AI Agent", "desc": "用自然语言查看和控制测试机", "model": "qwen3-max", "trigger": "用户"},
    {"id": "report", "name": "报告生成", "where": "批次报告", "desc": "按已算好的数字写总结，并在沙箱里画补充图", "model": "deepseek-v3", "trigger": "用户"},
    {"id": "anomaly", "name": "异常归因", "where": "运行总览 · 告警", "desc": "新告警产生时自动区分设备、产品和数据异常", "model": "deepseek-v3", "trigger": "自动"},
    {"id": "calib", "name": "补偿建议", "where": "设备配置 · 一致性", "desc": "根据标准样品复测给出通道补偿建议", "model": "qwen3-max", "trigger": "用户 + 自动"},
)

MODULE_IDS = {item["id"] for item in MODULES}
AUTO_MODULES = {item["id"] for item in MODULES if "自动" in item["trigger"]}

# 元 / 百万 token，顺序是输入、输出。和统计页原来的公开单价一致。
PRICES = {
    "deepseek-v3": (2.0, 8.0),
    "qwen3-max": (6.0, 24.0),
    "deepseek-flash": (1.0, 2.0),
    "rule": (0.0, 0.0),
}
FALLBACK_PRICE = (4.0, 16.0)


def price_of(model: str, overrides: dict | None = None) -> tuple[float, float]:
    custom = (overrides or {}).get(model)
    if isinstance(custom, dict):
        return float(custom.get("input") or 0), float(custom.get("output") or 0)
    return PRICES.get(model, FALLBACK_PRICE)


def cost_cny(model: str, incoming: int, outgoing: int, overrides: dict | None = None) -> float:
    pin, pout = price_of(model, overrides)
    return incoming * pin / 1_000_000 + outgoing * pout / 1_000_000
