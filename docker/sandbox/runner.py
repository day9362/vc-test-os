import json
import traceback
from pathlib import Path

import pandas as pd


def main() -> None:
    runs = pd.read_json("/work/runs.json", orient="records")
    code = Path("/work/code.py").read_text(encoding="utf-8")
    namespace: dict = {"pd": pd}
    try:
        exec(compile(code, "analysis.py", "exec"), namespace)
        analyze = namespace.get("analyze")
        if not callable(analyze):
            raise RuntimeError("代码里需要定义 analyze(runs)")
        result = analyze(runs)
        if not isinstance(result, dict):
            raise RuntimeError("analyze 必须返回 dict")
        Path("/out/result.json").write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        Path("/out/error.txt").write_text(traceback.format_exc()[-4000:], encoding="utf-8")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
