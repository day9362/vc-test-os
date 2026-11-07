_SOURCE = {"sim": "仿真平台", "cluster": "真实集群"}
_ON_503 = {"skip": "跳过该机台", "pause": "暂停全部同步"}


def describe_settings_changes(before: dict, after: dict) -> list[str]:
    changes: list[str] = []
    _field(changes, before, after, ("source",), "数据源", lambda value: _SOURCE.get(str(value), str(value)))
    _field(changes, before, after, ("cluster", "base_url"), "集群地址")
    if not _same(_get(before, ("cluster", "token")), _get(after, ("cluster", "token"))):
        changes.append("修改了集群令牌")
    _field(changes, before, after, ("cluster", "timeout_s"), "请求超时", lambda value: f"{_num(value)} 秒")
    _field(changes, before, after, ("cluster", "retries"), "失败重试", lambda value: f"{_num(value)} 次")
    _field(changes, before, after, ("cluster", "on_503"), "机台返回 503 时", lambda value: _ON_503.get(str(value), str(value)))
    _field(changes, before, after, ("sim", "base_url"), "仿真地址")
    _field(changes, before, after, ("sim", "speed"), "仿真倍率", lambda value: f"×{_num(value)}")
    _switch(changes, before, after, ("sim", "use_ground_truth"), "Ground truth")
    _jobs(changes, before.get("jobs") or [], after.get("jobs") or [])
    if not _same(_get(before, ("storage", "dsn")), _get(after, ("storage", "dsn"))):
        changes.append("修改了数据库连接")
    _field(changes, before, after, ("storage", "samples_days"), "过程曲线保留", lambda value: f"{_num(value)} 天")
    _field(changes, before, after, ("storage", "runs_days"), "测试记录保留", lambda value: f"{_num(value)} 天")
    _switch(changes, before, after, ("storage", "agg_5m"), "5 分钟汇总")
    _field(changes, before, after, ("storage", "object_store"), "对象存储")
    _field(changes, before, after, ("ai", "model"), "共用模型")
    _field(changes, before, after, ("ai", "monthly_budget_m"), "月度预算", lambda value: f"{_num(value)} M tokens")
    _field(changes, before, after, ("ai", "alert_pct"), "预算提醒", lambda value: f"{_num(value)}%")
    if _same(_get(before, ("ai", "model")), _get(after, ("ai", "model"))) and not _same(_get(before, ("ai", "models")), _get(after, ("ai", "models"))):
        changes.append("调整了各模块使用的模型")
    _field(changes, before, after, ("rules", "drift_c"), "设备异常阈值", lambda value: f"{_num(value)} ℃")
    _field(changes, before, after, ("rules", "ack_timeout_min"), "告警确认超时", lambda value: f"{_num(value)} 分钟")
    _field(changes, before, after, ("rules", "we_rules"), "趋势规则", lambda value: "、".join(str(item) for item in value) or "无")
    _switch(changes, before, after, ("rules", "sentinel_as_data_anomaly"), "哨兵值记为数据异常")
    _switch(changes, before, after, ("rules", "degraded_alarm"), "通信降级告警")
    return changes


def _jobs(changes: list[str], before: list, after: list) -> None:
    old = {str(job.get("key")): job for job in before if isinstance(job, dict)}
    new = {str(job.get("key")): job for job in after if isinstance(job, dict)}
    for key in dict.fromkeys([*old, *new]):
        name = str((new.get(key) or old.get(key) or {}).get("name") or key)
        if key not in old or key not in new:
            changes.append(f"调整了同步任务 {name}")
            continue
        if not _same(old[key].get("enabled"), new[key].get("enabled")):
            changes.append(f"{'启用' if new[key].get('enabled') else '停用'}{name}")
        if not _same(old[key].get("interval_s"), new[key].get("interval_s")):
            changes.append(f"{name}间隔改为 {_num(new[key].get('interval_s'))} 秒")


def _field(changes: list[str], before: dict, after: dict, path: tuple[str, ...], label: str, render=None) -> None:
    old = _get(before, path)
    new = _get(after, path)
    if _same(old, new):
        return
    shown = render(new) if render else new
    changes.append(f"{label}改为 {shown}")


def _switch(changes: list[str], before: dict, after: dict, path: tuple[str, ...], label: str) -> None:
    old = bool(_get(before, path))
    new = bool(_get(after, path))
    if old == new:
        return
    changes.append(f"{'打开' if new else '关闭'}{label}")


def _get(payload: dict, path: tuple[str, ...]):
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _same(old, new) -> bool:
    if isinstance(old, bool) or isinstance(new, bool):
        return bool(old) == bool(new)
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return float(old) == float(new)
    if isinstance(old, list) and isinstance(new, list):
        return [str(item) for item in old] == [str(item) for item in new] or sorted(str(item) for item in old) == sorted(str(item) for item in new)
    return old == new


def _num(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return str(number)
