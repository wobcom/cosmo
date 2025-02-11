import abc
import ipaddress
from functools import singledispatchmethod
from .types import (InterfaceType,
                    TagType, VLANType, IPAddressType)

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
    _interfaces_key = "cumulus__device_interfaces"

    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: IPAddressType):
        parent_interface = o.getParent(InterfaceType)
        if parent_interface and parent_interface.isManagementInterface():
            return {
                self._interfaces_key: {
                    parent_interface.getName(): {
                        "vrf": "mgmt",
                        "mtu": 1_500 if not parent_interface.getMTU() else parent_interface.getMTU(),
                        "address": o.getIPAddress(),
                        "gateway": next(
                            ipaddress.ip_network(o.getIPAddress(),strict=False).hosts()
                        ).compressed
                    }
                }
            }

    def processUntaggedVLAN(self, o: VLANType):
        return {
            self._interfaces_key: {
                o.getParent(InterfaceType).getName(): {
                    "untagged_vlan": o.getVID(),
                    # untagged VLANs belong to the vid list as well
                    "tagged_vlans": [ o.getVID() ]
                },
                "bridge": {
                    "mtu": 10_000,
                    "tagged_vlans": [ o.getVID() ]
                }
            }
        }

    def processTaggedVLAN(self, o: VLANType):
        return {
            self._interfaces_key: {
                o.getParent(InterfaceType).getName(): {
                    "tagged_vlans": [ o.getVID() ]
                },
                "bridge": {
                    "mtu": 10_000,
                    "tagged_vlans": [ o.getVID() ],
                }
            }
        }

    @accept.register
    def _(self, o: VLANType):
        ret = None
        parent_interface = o.getParent(InterfaceType)
        if o in parent_interface.getTaggedVLANS():
            ret = self.processTaggedVLAN(o)
        elif o == parent_interface.getUntaggedVLAN():
            ret = self.processUntaggedVLAN(o)
        if parent_interface.enabled() and not parent_interface.lagMember():
            ret[self._interfaces_key]["bridge"]["bridge_ports"] = [ parent_interface.getName() ]
        return ret

    def processLagMember(self, o: InterfaceType):
        pass

    def processInterface(self, o: InterfaceType):
        return {
            self._interfaces_key: {
                o.getName(): {
                    "mtu": 10_000 if not o.getMTU() else o.getMTU()
                } | {
                    "description": o.getDescription()
                } if o.getDescription() else {} | {
                    "bpdufilter": True
                } if not o.isManagementInterface() else {}
            }
        }

    @accept.register
    def _(self, o: InterfaceType):
        # either lag member
        if type(o.getParent()) == InterfaceType:
            return self.processLagMember(o)
        else:
        # or device interface
            return self.processInterface(o)

    @accept.register
    def _(self, o: TagType):
        parent_interface = o.getParent(InterfaceType)
        if o.getTagName() == "speed":
            return {
                self._interfaces_key: {
                    parent_interface.getName(): {
                        "speed": {
                        "1g": 1000,
                        "10g": 10_000,
                        "100g": 100_000,
                        }[o.getTagValue()]
                    }
                }
            }
        if o.getTagName() == "fec" and o.getTagValue() in ["off", "rs", "baser"]:
            return {
                self._interfaces_key: {
                    parent_interface.getName(): {
                        "fec": o.getTagValue()
                    }
                }
            }
        if o.getTagName() == "lldp":
            return {
                self._interfaces_key: {
                    parent_interface.getName(): {
                        "lldp": True
                    }
                }
            }
