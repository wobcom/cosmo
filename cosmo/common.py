def head(l):
    return None if not l else l[0]

def deepsort(e):
    if isinstance(e, list):
        return sorted(deepsort(v) for v in e)
    elif isinstance(e, dict):
        return {k: deepsort(v) for k, v in e.items()}
    return e


def without_keys(d, keys) -> dict:
    if type(keys) != list:
        keys = [keys]
    return {k: v for k,v in d.items() if k not in keys}
