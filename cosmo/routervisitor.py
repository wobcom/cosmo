import re
import warnings
from functools import singledispatchmethod

from cosmo.types import L2VPNType, VRFType, CosmoLoopbackType, InterfaceType, TagType
from cosmo.visitors import AbstractNoopNetboxTypesVisitor


class RouterDeviceExporterVisitor(AbstractNoopNetboxTypesVisitor):
    _interfaces_key = "interfaces"

    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    def processWANL2VPN(self, o: L2VPNType):
        pass

    @accept.register
    def _(self, o: L2VPNType):
        if o.getName().startswith("WAN"):
            return self.processWANL2VPN(o)

    @accept.register
    def _(self, o: CosmoLoopbackType):
        pass

    @accept.register
    def _(self, o: VRFType):
        pass

    @accept.register
    def _(self, o: InterfaceType):
        return {
            self._interfaces_key: {
                o.getName(): {
                    "type": o.getAssociatedType(),
                    "description": o.getDescription(),
                    "mtu": o.getMTU(),
                } | ({"shutdown": True} if not o.enabled() else {})
            }
        }

    def processAutonegTag(self, o: TagType):
        return {
            self._interfaces_key: {
                o.getParent(InterfaceType).getName(): {
                    "gigether": {
                        "autonegotiation": True if o.getTagValue() == "on" else False
                    }
                }
            }
        }

    def processSpeedTag(self, o: TagType):
        if not re.search("[0-9]+[tgmTGM]", o.getTagValue()):
            warnings.warn(
                f"Interface speed {o.getTagValue()} on interface "
                f"{o.getParent(InterfaceType).getName()} is not known, ignoring"
            )
        else:
            return {
                self._interfaces_key: {
                    o.getParent(InterfaceType).getName(): {
                        "gigether":  {
                            "speed": o.getTagValue()
                        }
                    }
                }
            }

    @accept.register
    def _(self, o: TagType):
        if o.getTagName() == "autoneg":
            return self.processAutonegTag(o)
        if o.getTagName() == "speed":
            return self.processSpeedTag(o)
