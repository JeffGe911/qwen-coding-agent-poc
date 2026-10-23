def clamp(value, lower, upper):
    if lower > upper:
        raise ValueError
    return min(max(value, lower), upper)