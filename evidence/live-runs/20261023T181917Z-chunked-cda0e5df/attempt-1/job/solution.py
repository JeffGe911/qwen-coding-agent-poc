def chunked(items, size):
    if not isinstance(size, int) or size <= 0:
        raise ValueError("not implemented")
    return [items[i:i+size] for i in range(0, len(items), size)]