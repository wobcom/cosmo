import abc
from .common import without_keys
from functools import singledispatchmethod, wraps
from .types import (AbstractNetboxType,
                    InterfaceType,
                    TagType, DeviceType)


def dictlike(fun):
    @wraps(fun)
    def wrapper(self, *args, **kwargs):
        return self._dictLikeTemplateMethod(fun(self, *args, **kwargs))
    return wrapper


class AbstractNoopNetboxTypesVisitor(abc.ABC):
    @singledispatchmethod
    def accept(self, o):
        raise NotImplementedError(f"unsupported type {o}")

    @accept.register
    def _(self, o: int):
        return o

    @accept.register
    def _(self, o: None):
        return o

    @accept.register
    def _(self, o: str):
        return o

    def _dictLikeTemplateMethod(self, o):
        for key in list(without_keys(o,"__parent").keys()):
            o[key] = self.accept(o[key])
        return o

    @accept.register
    def _(self, o: dict) -> dict:
        return self._dictLikeTemplateMethod(o)

    @accept.register
    def _(self, o: list) -> list:
        for i, v in enumerate(o):
            o[i] = self.accept(v)
        return o


class SwitchDeviceExporterVisitor(AbstractNoopNetboxTypesVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    @dictlike
    def _(self, o: DeviceType):
        o['cumulus__device_interfaces'] = {}
        for interface in o['interfaces']:
            o['cumulus__device_interfaces'][interface.getName()] = interface
        return o

    @accept.register
    @dictlike
    def _(self, o: TagType):
        if o.getTagName() == "speed":
            o.getParent(InterfaceType)["speed"] = {
                "1g": 1000,
                "10g": 10_000,
                "100g": 100_000,
            }[o.getTagValue()]
        elif o.getTagName() == "fec":
            if o.getTagValue() in ['off', 'rs', 'baser']:
                o.getParent(InterfaceType)["fec"] = o.getTagValue()
        elif o.getTagName() == "lldp":
            o.getParent(InterfaceType)["lldp"] = True
        return o
