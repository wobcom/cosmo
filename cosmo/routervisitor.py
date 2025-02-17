import re
import warnings
from functools import singledispatchmethod

from cosmo.types import L2VPNType, VRFType, CosmoLoopbackType, InterfaceType, TagType, VLANType, DeviceType
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

    @staticmethod
    def processInterfaceCommon(o: InterfaceType):
        return {
            "type": o.getAssociatedType(),
            "description": o.getDescription(),
            "mtu": o.getMTU(),
        } | ({"shutdown": True} if not o.enabled() else {})

    @staticmethod
    def processSubInterface(o: InterfaceType):
        if not o.getUntaggedVLAN():
            warnings.warn(f"Sub interface {o.getName()} does not have a access VLAN configured, skipping...")


    @accept.register
    def _(self, o: InterfaceType):
        if o.isSubInterface():
            return self.processSubInterface(o)
        else:
            return {
                self._interfaces_key: {
                    **o.spitInterfacePathWith(self.processInterfaceCommon(o))
                }
            }

    def processUntaggedVLAN(self, o: VLANType):
        parent_interface = o.getParent(InterfaceType)
        if not parent_interface.isInAccessMode():
            warnings.warn(
                f"Interface {parent_interface} on device {o.getParent(DeviceType).getName()} "
                "is mode ACCESS but has no untagged vlan, skipping"
            )
        elif parent_interface.isSubInterface() and parent_interface.enabled():
            return {
                self._interfaces_key: {
                    **parent_interface.spitInterfacePathWith({
                        **self.processInterfaceCommon(parent_interface),
                        "vlan": o.getVID()
                    }),
                }
            }

    @accept.register
    def _(self, o: VLANType):
        parent_interface = o.getParent(InterfaceType)
        if o == parent_interface.getUntaggedVLAN():
            return self.processUntaggedVLAN(o)


    def processAutonegTag(self, o: TagType):
        return {
            self._interfaces_key: {
                **o.getParent(InterfaceType).spitInterfacePathWith({
                    "gigether": {
                        "autonegotiation": True if o.getTagValue() == "on" else False
                    }
                })
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
                    **o.getParent(InterfaceType).spitInterfacePathWith({
                        "gigether":  {
                            "speed": o.getTagValue()
                        }
                    })
                }
            }

    @accept.register
    def _(self, o: TagType):
        if o.getTagName() == "autoneg":
            return self.processAutonegTag(o)
        if o.getTagName() == "speed":
            return self.processSpeedTag(o)
