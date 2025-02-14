import abc
import ipaddress
import warnings
from functools import singledispatchmethod

from .manufacturers import AbstractManufacturer
from .types import (InterfaceType,
                    TagType, VLANType, IPAddressType, DeviceType)

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
        manufacturer = AbstractManufacturer.getManufacturerFor(o.getParent(DeviceType))
        parent_interface = o.getParent(InterfaceType)
        if parent_interface and manufacturer.isManagementInterface(parent_interface):
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
                    # if we have tagged and untagged VLANs on an interface,
                    # untagged VLANs belong to the tagged VID list as well
                } | ({ "tagged_vlans": [o.getVID()] } if len(o.getParent(InterfaceType).getTaggedVLANS()) else {}),
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
        if parent_interface.enabled() and not parent_interface.isLagMember():
            ret[self._interfaces_key]["bridge"]["bridge_ports"] = [ parent_interface.getName() ]
        return ret

    @staticmethod
    def processInterfaceCommon(o: InterfaceType):
        manufacturer = AbstractManufacturer.getManufacturerFor(o.getParent(DeviceType))
        description = {
            "description": o.getDescription()
        } if o.getDescription() else {}
        bpdu_filter = {
            "bpdufilter": True
        } if not manufacturer.isManagementInterface(o) else {}
        return {
            "mtu": 10_000 if not o.getMTU() else o.getMTU()
        } | description | bpdu_filter

    def processLagMember(self, o: InterfaceType):
        return {
            self._interfaces_key: {
                o.getName(): {
                    "bond_mode": "802.3ad",
                } | self.processInterfaceCommon(o)
            }
        }

    def processInterface(self, o: InterfaceType):
        return {
            self._interfaces_key: {
                o.getName(): self.processInterfaceCommon(o)
            }
        }

    def processInterfaceLagInfo(self, o: InterfaceType):
        return {
            self._interfaces_key: {
                o.getName(): {
                    "bond_slaves": [
                        o.getParent(InterfaceType).getName()
                    ]
                },
                o.getParent(InterfaceType).getName(): {
                    "description": f"LAG Member of {o.getName()}"
                }
            }
        }

    @accept.register
    def _(self, o: InterfaceType):
        # either lag interface
        if o.isLagInterface():
            return self.processLagMember(o)
        # 'lag': {'__typename': 'InterfaceType', 'id': '${ID}', 'name': '${NAME}'}
        elif type(o.getParent()) == InterfaceType: # interface in interface -> lagInfo
            return self.processInterfaceLagInfo(o)
        # or "normal" interface
        else:
            return self.processInterface(o)

    def processSpeedTag(self, o: TagType):
        parent_interface = o.getParent(InterfaceType)
        speeds = {
            "1g": 1000,
            "10g": 10_000,
            "100g": 100_000,
        }
        if o.getTagValue() not in speeds:
            warnings.warn(
                f"Interface speed {o.getTagValue()} on interface "
                f"{parent_interface.getName()} is not known, ignoring"
            )
        else:
            return {
                self._interfaces_key: {
                    parent_interface.getName(): {
                        "speed": speeds[o.getTagValue()]
                    }
                }
            }

    def processFECTag(self, o: TagType):
        parent_interface = o.getParent(InterfaceType)
        fecs = ["off", "rs", "baser"]
        if o.getTagValue() not in fecs:
            warnings.warn(
                f"FEC mode {o.getTagValue()} on interface "
                f"{parent_interface.getName()} is not known, ignoring"
            )
        else:
            return {
                self._interfaces_key: {
                    parent_interface.getName(): {
                        "fec": o.getTagValue()
                    }
                }
            }

    def processLLDPTag(self, o: TagType):
        parent_interface = o.getParent(InterfaceType)
        return {
            self._interfaces_key: {
                parent_interface.getName(): {
                    "lldp": True
                }
            }
        }

    @accept.register
    def _(self, o: TagType):
        if o.getTagName() == "speed":
            return self.processSpeedTag(o)
        if o.getTagName() == "fec":
            return self.processFECTag(o)
        if o.getTagName() == "lldp":
            return self.processLLDPTag(o)
