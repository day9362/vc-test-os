import math
import statistics


def five_number(values: list[float]) -> list[float]:
    ordered = sorted(values)
    if len(ordered) == 1:
        value = ordered[0]
        return [value, value, value, value, value]
    quarters = statistics.quantiles(ordered, n=4, method="inclusive")
    return [ordered[0], quarters[0], quarters[1], quarters[2], ordered[-1]]


def pearson(xs: list[float], ys: list[float]) -> float | None:
    count = len(xs)
    if count < 3 or count != len(ys):
        return None
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    scale_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    scale_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if scale_x == 0 or scale_y == 0:
        return None
    return covariance / (scale_x * scale_y)


def welch(left: list[float], right: list[float]) -> dict | None:
    if len(left) < 2 or len(right) < 2:
        return None
    mean_left = statistics.fmean(left)
    mean_right = statistics.fmean(right)
    var_left = statistics.variance(left)
    var_right = statistics.variance(right)
    spread = var_left / len(left) + var_right / len(right)
    if spread == 0:
        probability = 1.0 if mean_left == mean_right else 0.0
        freedom = float(len(left) + len(right) - 2)
    else:
        freedom = _welch_df(var_left, len(left), var_right, len(right), spread)
        probability = student_t_sf(abs(mean_left - mean_right) / math.sqrt(spread), freedom)
    return {
        "n_left": len(left),
        "n_right": len(right),
        "mean_left": mean_left,
        "mean_right": mean_right,
        "diff": mean_left - mean_right,
        "df": freedom,
        "p": probability,
        "method": "Welch t",
    }


def student_t_sf(t_value: float, df: float) -> float:
    if df <= 0:
        return 1.0
    if t_value == 0:
        return 1.0
    x = df / (df + t_value * t_value)
    return _regularized_beta(df / 2, 0.5, x)


def _welch_df(var_left: float, n_left: int, var_right: float, n_right: int, spread: float) -> float:
    denominator = 0.0
    if n_left > 1 and var_left:
        term = var_left / n_left
        denominator += term * term / (n_left - 1)
    if n_right > 1 and var_right:
        term = var_right / n_right
        denominator += term * term / (n_right - 1)
    if denominator == 0:
        return float(n_left + n_right - 2)
    return spread * spread / denominator


def _regularized_beta(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    log_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    if x < (a + 1) / (a + b + 2):
        front = math.exp(a * math.log(x) + b * math.log(1 - x) - log_beta) / a
        return front * _beta_cf(a, b, x)
    front = math.exp(a * math.log(x) + b * math.log(1 - x) - log_beta) / b
    return 1 - front * _beta_cf(b, a, 1 - x)


def _beta_cf(a: float, b: float, x: float) -> float:
    qab = a + b
    qap = a + 1
    qam = a - 1
    c = 1.0
    d = 1 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-10:
            break
    return h
