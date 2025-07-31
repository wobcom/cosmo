from abc import ABC
from typing import Optional

APP_NAME = "cosmo"


class AbstractRecoverableError(Exception, ABC):
    def __init__(self, text: str, on: Optional[object] = None, *args):
        super().__init__(text, *args)
        self.associated_object = on

class DeviceSerializationError(AbstractRecoverableError):
    pass


class InterfaceSerializationError(AbstractRecoverableError):
    pass


class StaticRouteSerializationError(AbstractRecoverableError):
    pass


class L2VPNSerializationError(AbstractRecoverableError):
    pass

# recursive type for the shape of cosmo output. use it when specifying something that
# the visitors will export.
CosmoOutputType = dict[str, str|dict[str, "CosmoOutputType"]|list["CosmoOutputType"]]

JsonOutputType = CosmoOutputType

# next() can raise StopIteration, so that's why I use this function
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
