import abc
from functools import singledispatchmethod
from .types import (AbstractNetboxType,
                    InterfaceType,
                    TagType, DeviceType)


class AbstractNoopNetboxTypesVisitor(abc.ABC):
    @singledispatchmethod
    def accept(self, o):
        raise NotImplementedError(f"unsupported type {o}")

    @accept.register
    def _(self, o: int):
        pass

    @accept.register
    def _(self, o: None):
        pass

    @accept.register
    def _(self, o: str):
        pass

    @accept.register
    def _(self, o: dict) -> dict:
        pass

    @accept.register
    def _(self, o: list) -> list:
        pass


class SwitchDeviceExporterVisitor(AbstractNoopNetboxTypesVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: DeviceType):
        o['cumulus__device_interfaces'] = {}
        for interface in o['interfaces']:
            o['cumulus__device_interfaces'][interface.getName()] = interface
        return o

    @accept.register
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
