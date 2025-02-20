import ipaddress
import re
import warnings
from functools import singledispatchmethod

from cosmo.common import head, InterfaceSerializationError
from cosmo.manufacturers import AbstractManufacturer
from cosmo.types import L2VPNType, VRFType, CosmoLoopbackType, InterfaceType, TagType, VLANType, DeviceType, \
    L2VPNTerminationType, IPAddressType
from cosmo.visitors import AbstractNoopNetboxTypesVisitor


class RouterDeviceExporterVisitor(AbstractNoopNetboxTypesVisitor):
    _interfaces_key = "interfaces"
    _vrf_key = "routing_instances"
    _mgmt_vrf_name = "MGMT-ROUTING-INSTANCE"
    _l2circuits_key = "l2circuits"
    _vpws_authorized_terminations_n = 2

    def __init__(self, loopbacks_by_device: dict[str, CosmoLoopbackType], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.loopbacks_by_device = loopbacks_by_device
        self.allow_private_ips = False

    def allowPrivateIPs(self):
        self.allow_private_ips = True
        return self

    def disallowPrivateIPs(self):
        self.allow_private_ips = False
        return self

    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: DeviceType):
        if o.getParent(): # not root, do not process!
            return
        manufacturer = AbstractManufacturer.getManufacturerFor(o)
        return {
            self._vrf_key: {
                manufacturer.getRoutingInstanceName(): {
                    "description": self._mgmt_vrf_name,
                }
            }
        }

    @accept.register
    def _(self, o: IPAddressType):
        manufacturer = AbstractManufacturer.getManufacturerFor(o.getParent(DeviceType))
        parent_interface = o.getParent(InterfaceType)
        if not parent_interface:
            return
        if manufacturer.isManagementInterface(parent_interface) and not o.isGlobal() and not self.allow_private_ips:
            raise InterfaceSerializationError(
                f"Private IP {o.getIPAddress()} used on interface {parent_interface.getName()}"
                f"in default VRF for device {o.getParent(DeviceType).getName()}. Did you forget to configure a VRF?"
            )
        if (
                parent_interface.isLoopback()
                and not o.getIPInterfaceObject().network.prefixlen == o.getIPInterfaceObject().max_prefixlen
        ):
            raise InterfaceSerializationError(f"IP {o.getIPAddress()} is not a valid loopback IP address.")
        version = {4: "inet", 6: "inet6"}[o.getIPInterfaceObject().version]
        role = {}
        if o.getRole() and o.getRole().lower() == "secondary":
            role = {"secondary": True}
        elif any(
                [
                    (
                            str(addr.getRole()).lower() == "secondary"
                            # primary and secondary are per network
                            # IP can only be primary if another address is in the same network and marked as secondary
                            and o.getIPInterfaceObject().network == addr.getIPInterfaceObject().network
                    )
                    for addr in parent_interface.getIPAddresses()
                ]
        ):
            role = {"primary": True}
        return {
            self._interfaces_key: {
                **parent_interface.spitInterfacePathWith({
                    "families": {
                        version: {
                            "address": {
                               o.getIPInterfaceObject().with_prefixlen: role
                            }
                        }
                    }
                })
            }
        }

    def isCompliantWANL2VPN(self, o: L2VPNType) -> bool:
        terminations = o.getTerminations()
        if o.getType().lower() == "vpws" and len(terminations) != self._vpws_authorized_terminations_n:
            warnings.warn(
                "VPWS circuits are only allowed to have two terminations. "
                f"{o.getName()} has {len(terminations)} terminations, ignoring..."
            )
            return False
        if any([not isinstance(t, (InterfaceType, VLANType)) for t in terminations]):
            warnings.warn(f"Found unsupported L2VPN termination in {o.getName()}, ignoring...")
            return False
        if o.getType().lower() == "vpws" and any([not isinstance(t, InterfaceType) for t in terminations]):
            return False
        return True

    @accept.register
    def _(self, o: L2VPNType):
        if not o.getName().startswith("WAN") and self.isCompliantWANL2VPN(o):
            return

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

    @staticmethod
    def getAssociatedEncapType(l2vpn: L2VPNType) -> str|None:
        # TODO: move me in manufacturer strategy?
        l2vpn_type = l2vpn.getType().lower()
        if l2vpn_type in ["vpws", "evpl"]:
            return "vlan-ccc"
        elif l2vpn_type in ["mpls-evpn", "mpls_evpn", "vxlan-evpn", "vxlan_evpn"]:
            return "vlan-bridge"

    def processL2vpnEplEvplTerminationInterface(self, o: InterfaceType):
        parent_l2vpn = o.getParent(L2VPNType)
        # find local end
        local = next(filter(
            lambda i: (
                    isinstance(i, InterfaceType)
                    and i == o
            ),
            parent_l2vpn.getTerminations()
        ))
        # remote end is the other one
        remote = next(filter(
            lambda i: i != local,
            parent_l2vpn.getTerminations()
        ))
        # + l2circuits
        remote_end_loopback = self.loopbacks_by_device.get(remote.getAssociatedDevice().getName())
        return {
            self._l2circuits_key: {
                parent_l2vpn.getName().replace("WAN: ", ""): {
                    "interfaces": {
                        o.getName(): {
                            "local_label": 1_000_000 + int(local.getParent(L2VPNTerminationType).getId()),
                            "remote_label": 1_000_000 + int(remote.getParent(L2VPNTerminationType).getId()),
                            "remote_ip": str(ipaddress.ip_interface(remote_end_loopback.getIpv4()).ip),
                        }
                    },
                    "description": f"{parent_l2vpn.getType().upper()}: "
                                   f"{parent_l2vpn.getName().replace('WAN: ', '')} "
                                   f"via {remote.getAssociatedDevice().getName()}",
                }
            }
        }

    def processL2VPNTerminationInterface(self, o: InterfaceType):
        # TODO: guard: check it belongs to current device
        parent_l2vpn = o.getParent(L2VPNType)
        optional_l2circuits = {}
        if not o.isSubInterface():
            return
        encap_type = self.getAssociatedEncapType(parent_l2vpn)
        if not encap_type:
            return
        if parent_l2vpn.getType().lower() in ["evpl", "epl"]:
            optional_l2circuits = self.processL2vpnEplEvplTerminationInterface(o)
        return {
            self._interfaces_key: {
                **o.spitInterfacePathWith({
                    "encapsulation": encap_type,
                })
            }
        } | optional_l2circuits

    def processLagMember(self, o: InterfaceType):
        return {
            self._interfaces_key: {
                **o.spitInterfacePathWith({
                    "type": "lag",
                } | self.processInterfaceCommon(o))
            }
        }

    def processInterfaceLagInfo(self, o: InterfaceType):
        return {
            self._interfaces_key: {
                **o.getParent(InterfaceType).spitInterfacePathWith({
                    "type": "lag_member",
                    "lag_parent": o.getName(),
                })
            }
        }

    @accept.register
    def _(self, o: InterfaceType):
        if isinstance(o.getParent(), VLANType):
            # guard: do not process VLAN interface info
            return
        if isinstance(o.getParent(), L2VPNTerminationType):
            return self.processL2VPNTerminationInterface(o)
        if o.isSubInterface():
            return self.processSubInterface(o)
        if o.isLagInterface():
            return self.processLagMember(o)
        if type(o.getParent()) == InterfaceType: # interface in interface is lag info
            return self.processInterfaceLagInfo(o)
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

    def processL2VPNTerminationVLAN(self, o: VLANType):
        encapsulation = {}
        encap_type = self.getAssociatedEncapType(o.getParent(L2VPNType))
        if encap_type:
            encapsulation = {"encapsulation": encap_type}
        linked_interface = head(
            list(
                filter(
                    lambda i: i.getParent(DeviceType) == o.getParent(DeviceType),
                    o.getInterfacesAsTagged()
                )
            )
        )
        return {
            self._interfaces_key: {
                **linked_interface.spitInterfacePathWith({} | encapsulation)
            }
        }

    @accept.register
    def _(self, o: VLANType):
        if isinstance(o.getParent(), L2VPNTerminationType):
            return self.processL2VPNTerminationVLAN(o)
        parent_interface = o.getParent(InterfaceType)
        if parent_interface and o == parent_interface.getUntaggedVLAN():
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

    def processFecTag(self, o: TagType):
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
                    **parent_interface.spitInterfacePathWith({
                        "gigether": {
                            "fec": {
                                "off": "none",
                                "baser": "fec74",
                                "rs": "fec91",
                            }[o.getTagValue()]
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
        if o.getTagName() == "fec":
            return self.processFecTag(o)
