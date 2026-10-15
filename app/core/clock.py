from time import time


def now_ms() -> int:
    return int(time() * 1000)
