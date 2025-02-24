import ipaddress
import re
import warnings
from functools import singledispatchmethod
from ipaddress import IPv4Interface, IPv6Interface

from cosmo.common import head, InterfaceSerializationError
from cosmo.cperoutervisitor import CpeRouterExporterVisitor
from cosmo.manufacturers import AbstractManufacturer
from cosmo.types import L2VPNType, VRFType, CosmoLoopbackType, InterfaceType, TagType, VLANType, DeviceType, \
    L2VPNTerminationType, IPAddressType, CosmoStaticRouteType
from cosmo.visitors import AbstractNoopNetboxTypesVisitor


class RouterDeviceExporterVisitor(AbstractNoopNetboxTypesVisitor):
    _interfaces_key = "interfaces"
    _vrf_key = "routing_instances"
    _mgmt_vrf_name = "MGMT-ROUTING-INSTANCE"
    _l2circuits_key = "l2circuits"
    _vpws_authorized_terminations_n = 2

    def __init__(self, loopbacks_by_device: dict[str, CosmoLoopbackType], my_asn: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.my_asn = my_asn
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
    def getAssociatedEncapType(o: InterfaceType | VLANType) -> str|None:
        # TODO: move me in manufacturer strategy?
        l2vpn_type = o.getParent(L2VPNType).getType().lower()
        is_eligible_for_vlan_encap = False
        if isinstance(o, VLANType):
            is_eligible_for_vlan_encap = True
        elif isinstance(o, InterfaceType) and (len(o.getTaggedVLANS()) or o.getUntaggedVLAN()):
            is_eligible_for_vlan_encap = True
        if l2vpn_type in ["vpws", "evpl"] and is_eligible_for_vlan_encap:
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

    def processL2vpnMplsEvpnTerminationInterface(self, o: InterfaceType):
        parent_l2vpn = o.getParent(L2VPNType)
        return {
            self._vrf_key: {
                parent_l2vpn.getName().replace("WAN: ", ""): {
                    "interfaces": [ o.getName() ],
                    "description": f"MPLS-EVPN: {parent_l2vpn.getName().replace('WAN: VS_', '')}",
                    "instance_type": "evpn",
                    "protocols": {
                        "evpn": {},
                    },
                    "route_distinguisher": f"{self.my_asn}:{str(parent_l2vpn.getIdentifier())}",
                    "vrf_target": f"target:1:{str(parent_l2vpn.getIdentifier())}",
                }
            }
        }

    def processL2vpnVpwsTerminationInterface(self, o: InterfaceType):
        parent_l2vpn = o.getParent(L2VPNType)
        # find local end
        local = next(filter(
            lambda i: (
                isinstance(i, InterfaceType)
                and i.getAssociatedDevice() == o.getParent(DeviceType)
            ),
            parent_l2vpn.getTerminations()
        ))
        # remote end is the other one
        remote = next(filter(
            lambda i: i != local,
            parent_l2vpn.getTerminations()
        ))
        breakpoint()
        return {
            self._vrf_key: {
                parent_l2vpn.getName().replace("WAN: ", ""): {
                    "interfaces": [ o.getName() ],
                    "description": f"VPWS: {parent_l2vpn.getName().replace('WAN: VS_', '')}",
                    "instance_type": "evpn-vpws",
                    "route-distinguisher": f"{self.my_asn}:{str(parent_l2vpn.getIdentifier())}",
                    "vrf-target": f"target:1:{str(parent_l2vpn.getIdentifier())}",
                    "protocols": {
                        "evpn": {
                            "interfaces": {
                                o.getName(): {
                                    "vpws_service_id": {
                                        "local": int(local.getID()),
                                        "remote": int(remote.getID()),
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

    def processL2VPNTerminationInterface(self, o: InterfaceType):
        # TODO: guard: check it belongs to current device
        parent_l2vpn = o.getParent(L2VPNType)
        optional_attrs = {}
        encapsulation = {}
        if not o.isSubInterface():
            return
        encap_type = self.getAssociatedEncapType(o)
        if encap_type:
            encapsulation = {"encapsulation": encap_type}
        l2vpn_type = parent_l2vpn.getType().lower()
        if l2vpn_type in ["evpl", "epl"]:
            optional_attrs = self.processL2vpnEplEvplTerminationInterface(o)
        elif l2vpn_type in ["mpls-evpn", "mpls_evpn"]:
            optional_attrs = self.processL2vpnMplsEvpnTerminationInterface(o)
        elif l2vpn_type in ["vpws"]:
            optional_attrs = self.processL2vpnVpwsTerminationInterface(o)
        return {
            self._interfaces_key: {
                **o.spitInterfacePathWith({} | encapsulation)
            }
        } | optional_attrs

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

    def processL2VPNTerminationVLAN(self, o: VLANType):
        encapsulation = {}
        encap_type = self.getAssociatedEncapType(o)
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

    def processBgpCpeTag(self, o: TagType):
        linked_interface = o.getParent(InterfaceType)
        group_name = "CPE_" + linked_interface.getName().replace(".", "-").replace("/","-")
        vrf_name = "default"
        policy_v4 = {
            "import_list": []
        }
        policy_v6 = {
            "import_list": []
        }
        if linked_interface.getVRF():
            vrf_name = linked_interface.getVRF().getName()
        if vrf_name == "default":
            policy_v4["export"] = "DEFAULT_V4"
            policy_v6["export"] = "DEFAULT_V6"
        if linked_interface.hasParentInterface():
            parent_interface = next(filter(
                lambda interface: interface == linked_interface["parent"],
                o.getParent(DeviceType).getInterfaces()
            ))
            cpe = head(parent_interface.getConnectedEndpoints())
            if not cpe:
                warnings.warn(
                    f"Interface {linked_interface.getName()} has bgp:cpe tag "
                    "on it without a connected device, skipping..."
                )
            else:
                cpe = DeviceType(cpe["device"])
                v4_import, v6_import = set(), set() # unique
                for item in iter(cpe):
                    ret = CpeRouterExporterVisitor().accept(item)
                    if not ret:
                        continue
                    af, prefix = ret
                    if af and af is IPv4Interface:
                        v4_import.add(prefix)
                    elif af and af is IPv6Interface:
                        v6_import.add(prefix)
                policy_v4["import_list"] = list(v4_import)
                policy_v6["import_list"] = list(v6_import)
        return {
            self._vrf_key: {
                vrf_name: {
                    "protocols": {
                        "bgp": {
                            "groups": {
                                group_name: {
                                    "any_as": True,
                                    "link_local_nexthop_only": True,
                                    "neighbors": [
                                        {"interface": linked_interface.getName()}
                                    ],
                                    "family": {
                                        "ipv4_unicast": {
                                            "extended_nexthop": True,
                                            "policy": policy_v4,
                                        },
                                        "ipv6_unicast": {
                                            "policy": policy_v6,
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
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
            return self.processBgpCpeTag(o)
        if o.getTagName() in ["policer", "policer_in", "policer_out"]:
            return self.processPolicerTag(o)
        if o.getTagName() == "edge":
            return self.processEdgeTag(o)