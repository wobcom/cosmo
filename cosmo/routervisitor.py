import ipaddress
import re
import warnings
from functools import singledispatchmethod

from cosmo.abstractroutervisitor import AbstractRouterExporterVisitor
from cosmo.common import InterfaceSerializationError
from cosmo.manufacturers import AbstractManufacturer
from cosmo.routerbgpcpevisitor import RouterBgpCpeExporterVisitor
from cosmo.routerl2vpnvisitor import RouterL2VPNValidatorVisitor, RouterL2VPNExporterVisitor
from cosmo.types import L2VPNType, VRFType, CosmoLoopbackType, InterfaceType, TagType, VLANType, DeviceType, \
    L2VPNTerminationType, IPAddressType, CosmoStaticRouteType


class RouterDeviceExporterVisitor(AbstractRouterExporterVisitor):
    def __init__(self, loopbacks_by_device: dict[str, CosmoLoopbackType], my_asn: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.my_l2vpn_exporter = RouterL2VPNExporterVisitor(loopbacks_by_device=loopbacks_by_device, my_asn=my_asn)
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
    def _(self, o: L2VPNType):
        # Note: I have to use composition since singledispatchmethod does not work well with inheritance
        return RouterL2VPNValidatorVisitor().accept(o)

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
            },
            self._l2circuits_key: {
                # this one should always exist
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
                f"Private IP {o.getIPAddress()} used on interface {parent_interface.getName()} "
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

    @accept.register
    def _(self, o: CosmoLoopbackType):
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
        # easy checks first, narrow down afterward
        if not o.getUntaggedVLAN() and not o.getUnitNumber() == 0:
            # costlier checks it is then
            device = o.getParent(DeviceType)
            parent_interface = next(filter(
                lambda i: i.getName() == o.getSubInterfaceParentInterfaceName(),
                device.getInterfaces()
            ))
            all_parent_sub_interfaces = list(filter(
                lambda i: i.getName().startswith(parent_interface.getName()) and i.isSubInterface(),
                device.getInterfaces()
            ))
            parent_interface_type = parent_interface.getAssociatedType()
            # cases where no VLAN is authorized: we have only one sub interface, or it's a loopback or virtual
            if len(all_parent_sub_interfaces) > 1 and parent_interface_type not in [ "loopback", "virtual" ]:
                warnings.warn(f"Sub interface {o.getName()} does not have a access VLAN configured!")

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
            return self.my_l2vpn_exporter.accept(o)
        if o.isSubInterface():
            return self.processSubInterface(o)
        if o.isLagInterface():
            return self.processLagMember(o)
        # interface in interface is lag info
        if type(o.getParent()) == InterfaceType and "lag" in o.getParent().keys() and o.getParent()["lag"] == o:
            return self.processInterfaceLagInfo(o)
        else:
            return {
                self._interfaces_key: {
                    **o.spitInterfacePathWith(self.processInterfaceCommon(o))
                }
            }

    def getRouterId(self, o: DeviceType) -> str:
        return str(ipaddress.ip_interface(self.loopbacks_by_device[o.getName()].getIpv4()).ip)

    @accept.register
    def _(self, o: VRFType):
        parent_interface = o.getParent(InterfaceType)
        router_id = self.getRouterId(o.getParent(DeviceType))
        if o.getRouteDistinguisher():
            rd = router_id + ":" + o.getRouteDistinguisher()
        elif len(o.getExportTargets()):
            rd = router_id + ":" + o.getID()
        else:
            rd = None
        return {
            self._vrf_key: {
                o.getName(): {
                    "interfaces": [ parent_interface.getName() ],
                    "description": o.getDescription(),
                    "instance_type": "vrf",
                    "route_distinguisher": rd,
                    "import_targets": [target.getName() for target in o.getImportTargets()],
                    "export_targets": [target.getName() for target in o.getExportTargets()],
                    "routing_options": {
                        # should always have this key present
                    },
                }
            }
        }

    @staticmethod
    def processStaticRouteCommon(o: CosmoStaticRouteType):
        next_hop = None
        if o.getNextHop():
            next_hop = str(o.getNextHop().getIPInterfaceObject().ip)
        elif o.getInterface():
            next_hop = o.getInterface().getName()
        if o.getPrefixFamily() == 4:
            table = f"{o.getVRF().getName()}.inet.0"
        else:
            table = f"{o.getVRF().getName()}.inet6.0"
        return {
            "routing_options": {
                "rib": {
                    table: {
                        "static": {
                            o.getPrefix(): {
                                               "next_hop": next_hop,
                                           } | (
                                               {"metric": o.getMetric()} if o.getMetric() else {}
                                           )
                        }
                    }
                }
            }
        }

    @accept.register
    def _(self, o: CosmoStaticRouteType):
        if o.getVRF():
            return {
                # vrf-wide static route
                self._vrf_key: {
                    o.getVRF().getName(): {
                        **self.processStaticRouteCommon(o)
                    }
                }
            }
        else:
            return {
                # device-wide static route
                **self.processStaticRouteCommon(o)
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
        if isinstance(o.getParent(), L2VPNTerminationType):
            return self.my_l2vpn_exporter.accept(o)
        parent_interface = o.getParent(InterfaceType)
        if (
                parent_interface and o == parent_interface.getUntaggedVLAN()
                # guard: skip VLAN processing if it is in L2VPN termination. should reappear in device.
                and not isinstance(parent_interface.getParent(), L2VPNTerminationType)
        ):
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

    def processPolicerTag(self, o: TagType):
        parent_interface = o.getParent(InterfaceType)
        policer_in, policer_out = {}, {}
        if o.getTagName() in ["policer_in", "policer"]:
            policer_in = {
                "input": f"POLICER_{o.getTagValue()}"
            }
        if o.getTagName() in ["policer_out", "policer"]:
            policer_out = {
                "output": f"POLICER_{o.getTagValue()}"
            }
        return {
            self._interfaces_key: {
                **parent_interface.spitInterfacePathWith({
                    "policer": {} | policer_in | policer_out
                })
            }
        }

    def processEdgeTag(self, o: TagType):
        parent_interface = o.getParent(InterfaceType)
        optional_sampling = {}
        if not any([
            t.getTagName() == "disable_sampling" or (t.getTagName() == "edge" and t.getTagValue() == "customer")
            for t in parent_interface.getTags()
        ]):
            optional_sampling = { "sampling": True }
        return {
            self._interfaces_key: {
                **parent_interface.spitInterfacePathWith({
                    "families": {
                        "inet": {
                            "filters": ["input-list [ EDGE_FILTER ]"],
                            "policer": [] + (["arp POLICER_IXP_ARP"] if o.getTagValue() == "peering-ixp" else [])
                        } | optional_sampling,
                        "inet6": {
                            "filters": ["input-list [ EDGE_FILTER_V6 ]"]
                        } | optional_sampling,
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
        if o.getTagName() == "bgp" and o.getTagValue() == "cpe":
            return RouterBgpCpeExporterVisitor().accept(o)
        if o.getTagName() in ["policer", "policer_in", "policer_out"]:
            return self.processPolicerTag(o)
        if o.getTagName() == "edge":
            return self.processEdgeTag(o)