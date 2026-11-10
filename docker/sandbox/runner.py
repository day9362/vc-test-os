import inspect
import json
import os
import traceback
from pathlib import Path

import pandas as pd


def main() -> None:
    work = Path(os.environ.get("WORK_DIR", "/work"))
    out = Path(os.environ.get("OUT_DIR", "/out"))
    runs = _frame(work, "results.json", "runs.json")
    samples = _frame(work, "samples.json")
    code = (work / "code.py").read_text(encoding="utf-8")
    namespace: dict = {"pd": pd}
    try:
        exec(compile(code, "analysis.py", "exec"), namespace)
        analyze = namespace.get("analyze")
        if not callable(analyze):
            raise RuntimeError("代码里需要定义 analyze(results, samples)")
        if _accepts_samples(analyze):
            result = analyze(runs, samples)
        else:
            result = analyze(runs)
        if not isinstance(result, dict):
            raise RuntimeError("analyze 必须返回 dict")
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        (out / "error.txt").write_text(traceback.format_exc()[-4000:], encoding="utf-8")
        raise SystemExit(1)


def _frame(work: Path, name: str, fallback: str = "") -> pd.DataFrame:
    path = work / name
    if not path.exists() and fallback:
        path = work / fallback
    if not path.exists():
        return pd.DataFrame()
    return pd.read_json(path, orient="records")


def _accepts_samples(analyze: object) -> bool:
    parameters = list(inspect.signature(analyze).parameters.values())
    if any(item.kind == inspect.Parameter.VAR_POSITIONAL for item in parameters):
        return True
    return len(parameters) >= 2


if __name__ == "__main__":
    main()
