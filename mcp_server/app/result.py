from typing import Any

from app.backend import Reply


def ok(summary: str, data: Any = None, *, next_cursor: str | None = None, hints: list[str] | None = None) -> dict:
    payload: dict = {"ok": True, "summary": summary, "data": data if data is not None else {}}
    if next_cursor:
        payload["next_cursor"] = next_cursor
    if hints:
        payload["hints"] = hints
    return payload


def fail(summary: str, code: str, *, status: int | None = None, message: str = "", detail: Any = None, hints: list[str] | None = None) -> dict:
    error: dict = {"code": code}
    if status:
        error["status"] = status
    if message:
        error["message"] = message
    if detail is not None:
        error["detail"] = detail
    payload: dict = {"ok": False, "summary": summary, "error": error}
    if hints:
        payload["hints"] = hints
    return payload


def bad(summary: str, hint: str | None = None) -> dict:
    return fail(summary, "BAD_ARGUMENT", hints=[hint] if hint else None)


def missing(*names: str) -> dict:
    return bad(f"缺少参数：{'、'.join(names)}。", f"补上 {'、'.join(names)} 再调用。")


def from_reply(reply: Reply, summary: str | None = None) -> dict:
    if reply.code == "BACKEND_UNAVAILABLE":
        return fail(
            "系统平台没有响应，这次没有完成。这不是设备故障。",
            reply.code,
            hints=["稍后再试，或检查 VC-TestOS 后端是否在运行"],
        )
    if reply.status == 401:
        return fail("登录已失效或没有权限访问系统平台。", "UNAUTHORIZED", status=401, message=reply.message)
    text = summary or reply.message or f"系统平台返回 {reply.status}"
    return fail(text, reply.code, status=reply.status, message=reply.message, detail=reply.detail)


def need_approval(sentence: str, approval: dict) -> dict:
    effects = approval.get("effects") or []
    tail = f"{'；'.join(effects)}。" if effects else ""
    return {
        "ok": False,
        "summary": f"需要用户在页面上批准：{sentence}。{tail}",
        "error": {"code": "APPROVAL_REQUIRED"},
        "approval": approval,
        "hints": ["告诉用户要做什么、有什么影响，请用户在页面右侧批准；不要自己重复调用。"],
    }


def forbidden() -> dict:
    return fail(
        "只读模式不能执行写操作。",
        "FORBIDDEN",
        status=403,
        hints=["外部客户端只能查询，不能改数据。写操作请在 VC-TestOS 的 AI Agent 页面发起。"],
    )
