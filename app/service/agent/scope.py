def with_scope(text: str, model: str, batches: list[str]) -> str:
    chosen_model = " ".join(model.split())[:80]
    chosen_batches: list[str] = []
    for item in batches:
        batch_id = " ".join(str(item).split())[:64]
        if batch_id and batch_id not in chosen_batches:
            chosen_batches.append(batch_id)
        if len(chosen_batches) == 20:
            break
    if not chosen_model and not chosen_batches:
        return text.strip()
    lines = ["分析范围："]
    if chosen_model:
        lines.append(f"型号：{chosen_model}")
    if chosen_batches:
        lines.append("批次：" + "、".join(chosen_batches))
    else:
        lines.append("没有勾选批次。")
    lines.append("查记录、对比和写方案时用这个范围。用户问题里写明了别的型号或批次时，以问题为准。")
    lines.append(text.strip())
    return "\n".join(lines)
