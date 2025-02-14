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


class ObjCache:
    def __init__(self):
        self._obj_cache = {}
        self.hits = 0

    def associate(self, o: object, v: object):
        self._obj_cache[id(o)] = v

    def get(self, o: object):
        if id(o) in self._obj_cache.keys():
            self.hits += 1
            return self._obj_cache[id(o)]
        return None

    def getHits(self):
        return self.hits
