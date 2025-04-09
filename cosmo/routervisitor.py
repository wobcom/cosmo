import ipaddress
import re
import warnings
from functools import singledispatchmethod
from typing import Optional

import deepmerge

from cosmo.abstractroutervisitor import AbstractRouterExporterVisitor
from cosmo.common import InterfaceSerializationError, head, StaticRouteSerializationError
from cosmo.manufacturers import AbstractManufacturer, ManufacturerFactoryFromDevice
from cosmo.routerbgpcpevisitor import RouterBgpCpeExporterVisitor
from cosmo.routerl2vpnvisitor import RouterL2VPNValidatorVisitor, RouterL2VPNExporterVisitor
from cosmo.netbox_types import L2VPNType, VRFType, CosmoLoopbackType, InterfaceType, TagType, VLANType, DeviceType, \
    L2VPNTerminationType, IPAddressType, CosmoStaticRouteType, DeviceTypeType, PlatformType


class RouterDeviceExporterVisitor(AbstractRouterExporterVisitor):
    def __init__(self, loopbacks_by_device: dict[str, CosmoLoopbackType], asn: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Note: I have to use composition since singledispatchmethod does not work well with inheritance
        self.l2vpn_exporter = RouterL2VPNExporterVisitor(loopbacks_by_device=loopbacks_by_device, asn=asn)
        self.l2vpn_validator = RouterL2VPNValidatorVisitor(loopbacks_by_device=loopbacks_by_device, asn=asn)
        self.bgpcpe_exporter = RouterBgpCpeExporterVisitor()
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
        return self.l2vpn_validator.accept(o)

    @accept.register
    def _(self, o: DeviceType):
        if not o.isCompositeRoot(): # not root, do not process!
            return
        manufacturer = ManufacturerFactoryFromDevice(o).get()
        return {
            "serial": o.getSerial(),
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
    def _(self, o: DeviceTypeType):
        return {
            "device_model": o.getSlug(),
        }

    @accept.register
    def _(self, o: PlatformType):
        return {
            "platform": o.getSlug(),
        }

    def processMgmtInterfaceIPAddress(self, o: IPAddressType):
        manufacturer = ManufacturerFactoryFromDevice(o.getParent(DeviceType)).get()
        return {
            self._vrf_key: {
                manufacturer.getRoutingInstanceName(): {
                    "routing_options": {
                        "rib": {
                            f"{manufacturer.getRoutingInstanceName()}.inet.0": {
                                "static": {
                                    "0.0.0.0/0": {
                                        "next_hop": str(o.getIPInterfaceObject().network[1]),
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

    @accept.register
    def _(self, o: IPAddressType):
        manufacturer = ManufacturerFactoryFromDevice(o.getParent(DeviceType)).get()
        optional_attrs = {}
        if not o.hasParentAboveWithType(InterfaceType):
            return
        parent_interface = o.getParent(InterfaceType)
        if not parent_interface.isSubInterface():
            raise InterfaceSerializationError(
                f"You seem to have configured an IP directly on interface {parent_interface.getName()}. "
                f"This is forbidden. Please make a virtual interface, assign the IP(s) on it and retry!"
            )
        if not (o.isGlobal() or
                self.allow_private_ips or
                parent_interface.getVRF() or
                manufacturer.isManagementInterface(parent_interface)):
            raise InterfaceSerializationError(
                f"Private IP {o.getIPAddress()} used on interface {parent_interface.getName()} "
                f"in default VRF for device {o.getParent(DeviceType).getName()}. Did you forget to configure a VRF?"
            )
        if manufacturer.isManagementInterface(parent_interface) and parent_interface.isSubInterface():
            optional_attrs = self.processMgmtInterfaceIPAddress(o)
        if (
                parent_interface.isLoopback()
                and not o.getIPInterfaceObject().network.prefixlen == o.getIPInterfaceObject().max_prefixlen
                and not parent_interface.getVRF() # only force /32 loopback in default vrf
        ):
            raise InterfaceSerializationError(f"IP {o.getIPAddress()} is not a valid loopback IP address.")
        ip_version = o.getIPInterfaceObject().version
        role = {}
        ipv6_ra = {}
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
        if parent_interface.getCustomFields().get("ipv6_ra", False) and ip_version == 6:
            ipv6_ra = { "ipv6_ra": True }
        return {
            self._interfaces_key: {
                **parent_interface.spitInterfacePathWith({
                    "families": {
                        {4: "inet", 6: "inet6"}[ip_version]: {
                            "address": {
                               o.getIPInterfaceObject().with_prefixlen: role
                            }
                        } | ipv6_ra
                    }
                })
            }
        } | optional_attrs

    @accept.register
    def _(self, o: CosmoLoopbackType):
        pass

    @staticmethod
    def processInterfaceCommon(o: InterfaceType):
        description = o.getDescription()
        edge_tag = head(list(filter(lambda t: t.getTagName().lower() == "edge", o.getTags())))
        if edge_tag:
            match edge_tag.getTagValue():
                case "customer":
                    description = f"Customer: {description}"
                case "upstream":
                    description = f"Transit: {description}"
                case _:
                    description = f"Peering: {description}"
        return {
        } | ({"shutdown": True} if not o.isEnabled() else {}) \
          | ({"description": description} if o.getDescription() else {}) \
          | ({"mtu": o.getMTU()} if o.getMTU() else {}) \
          | ({"type": o.getAssociatedType()} if not o.isSubInterface() else {}) \
          | ({"mac_address": o.getMACAddress()} if o.getMACAddress() and o.isSubInterface() else {})

    def processSubInterface(self, o: InterfaceType):
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
        # specific outer_tag case -> we cannot process the "virtual" untagged vlan
        # via type hinting / visitor, since it does not exist in the composite
        # tree, and is only represent by outer_tag CF.
        # outer_tag should only appear on a sub-interface, hence why we process it
        # through this specific case.
        optional_interface_attrs = {}
        optional_root_interface_attrs = {}
        if "outer_tag" in o.getCustomFields() and o.getUntaggedVLAN():
            optional_interface_attrs = { "vlan": o.getUntaggedVLAN().getVID() }
            if o.getUnitNumber() == 0: # native vlan
                optional_root_interface_attrs = {
                    self._interfaces_key: {
                        o.getSubInterfaceParentInterfaceName(): {
                            "native_vlan": o.getUntaggedVLAN().getVID()
                        }
                    }
                }
        return deepmerge.always_merger.merge({
            self._interfaces_key: {
                **o.spitInterfacePathWith({
                    **self.processInterfaceCommon(o),
                    **optional_interface_attrs,
                })
            }
        }, optional_root_interface_attrs)


    def processInterfaceLagInfo(self, o: InterfaceType):
        return {
            self._interfaces_key: {
                **o.spitInterfacePathWith({
                    **self.processInterfaceCommon(o),
                    "type": "lag", # dict priority
                })
            }
        }

    def processLagMember(self, o: InterfaceType):
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
        if o.hasParentAboveWithType(VLANType):
            # guard: do not process VLAN interface info
            return
        if o.hasParentAboveWithType(L2VPNTerminationType):
            return self.l2vpn_exporter.accept(o)
        if o.isSubInterface():
            return self.processSubInterface(o)
        if o.isLagInterface():
            return self.processInterfaceLagInfo(o)
        # interface in interface is lag info
        if o.hasParentAboveWithType(InterfaceType):
            if "lag" in o.getParent(InterfaceType).keys() and o.getParent(InterfaceType)["lag"] == o:
                return self.processLagMember(o)
            return # guard: do not process (can be connected_endpoint, parent, etc...)
        return {
            self._interfaces_key: {
                **o.spitInterfacePathWith(self.processInterfaceCommon(o))
            }
        }

    def getRouterId(self, o: DeviceType) -> str:
        return str(ipaddress.ip_interface(str(self.loopbacks_by_device[o.getName()].getIpv4())).ip)

    @accept.register
    def _(self, o: VRFType):
        parent_interface = o.getParent(InterfaceType)
        if not parent_interface.isSubInterface():
            return # guard: do not process root interface
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
        table = str()
        next_hop_ipaddr_object = o.getNextHop()
        interface_object = o.getInterface()
        vrf_object = o.getVRF()
        if isinstance(next_hop_ipaddr_object, IPAddressType):
            next_hop = str(next_hop_ipaddr_object.getIPInterfaceObject().ip)
        elif isinstance(interface_object, InterfaceType):
            next_hop = interface_object.getName()
        if isinstance(vrf_object, VRFType):
            if o.getPrefixFamily() == 4:
                table = f"{vrf_object.getName()}.inet.0"
            elif o.getPrefixFamily() == 6:
                table = f"{vrf_object.getName()}.inet6.0"
            else:
                raise StaticRouteSerializationError(
                    f"Cannot find associated VRF for {o}! Please check Netbox data."
                )
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
        vrf_object = o.getVRF()
        if isinstance(vrf_object, VRFType):
            return {
                # vrf-wide static route
                self._vrf_key: {
                    vrf_object.getName(): {
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
        elif parent_interface.isSubInterface() and parent_interface.isEnabled():
            optional_root_interface_attrs = {}
            if parent_interface.getUnitNumber == 0:
                optional_root_interface_attrs = {
                    self._interfaces_key: {
                        parent_interface.getSubInterfaceParentInterfaceName(): {
                            "native_vlan": o.getVID()
                        }
                    }
                }
            return deepmerge.always_merger.merge({
                self._interfaces_key: {
                    **parent_interface.spitInterfacePathWith({
                        **self.processInterfaceCommon(parent_interface),
                        "vlan": o.getVID()
                    }),
                }
            }, optional_root_interface_attrs)

    @accept.register
    def _(self, o: VLANType):
        if o.hasParentAboveWithType(L2VPNTerminationType):
            return self.l2vpn_exporter.accept(o)
        parent_interface = o.getParent(InterfaceType)
        if (
                parent_interface and o == parent_interface.getUntaggedVLAN()
                # guard: skip VLAN processing if it is in L2VPN termination. should reappear in device.
                and not parent_interface.hasParentAboveWithType(L2VPNTerminationType)
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
        optional_arp_policer = {}
        if not any([
            t.getTagName() == "disable_sampling" or (t.getTagName() == "edge" and t.getTagValue() == "customer")
            for t in parent_interface.getTags()
        ]):
            optional_sampling = { "sampling": True }
        if o.getTagValue() == "peering-ixp":
            optional_arp_policer = { "policer": ["arp POLICER_IXP_ARP"]}
        return {
            self._interfaces_key: {
                **parent_interface.spitInterfacePathWith({
                    "families": {
                        "inet": {
                            "filters": ["input-list [ EDGE_FILTER ]"],
                        } | optional_sampling | optional_arp_policer,
                        "inet6": {
                            "filters": ["input-list [ EDGE_FILTER_V6 ]"]
                        } | optional_sampling,
                    }
                })
            }
        }

    def processUrpfTag(self, o: TagType):
        parent_interface = o.getParent(InterfaceType)
        ipv6_rpf = {}
        ipv4_rpf = {}
        if o.getTagValue() == "disable": # do not process, urpf is disabled
            return
        if any(map( # any short-circuits
            lambda i: i.getIPInterfaceObject().version == 4,
            parent_interface.getIPAddresses()
        )):
            ipv4_rpf = {
                "inet": {
                    "rpf_check": {
                        "mode": o.getTagValue()
                    }
                }
            }
        if any(map( # any short-circuits
            lambda i: i.getIPInterfaceObject().version == 6,
            parent_interface.getIPAddresses()
        )):
            ipv6_rpf = {
                "inet6": {
                    "rpf_check": {
                        "mode": o.getTagValue()
                    }
                }
            }
        if not len(ipv4_rpf)+len(ipv6_rpf):
            return
        return {
            self._interfaces_key: {
                **parent_interface.spitInterfacePathWith({
                    "families": {
                    } | ipv6_rpf | ipv4_rpf
                })
            }
        }

    def processCoreTag(self, o: TagType):
        interface = o.getParent(InterfaceType)
        parent_interface = head(list(filter( # as in, netbox parent
            lambda i: i.getName() == interface.getSubInterfaceParentInterfaceName(),
            interface.getParent(DeviceType).getInterfaces()
        )))
        sonderlocke = any(map(
            lambda i: i.getTagName() == "sonderlocke" and i.getTagValue() == "mtu", interface.getTags()
        ))
        parent_mtu = parent_interface.getMTU() if parent_interface else None
        mtu = interface.getMTU() or parent_mtu
        if not sonderlocke and mtu is not None and mtu not in self._allowed_core_mtus:
            warnings.warn(
                f"Interface {interface.getName()} on device {interface.getParent(DeviceType).getName()} "
                f"has MTU {mtu} set, which is not one of the allowed values for core interfaces."
            )
        return {
            self._interfaces_key: {
                **interface.spitInterfacePathWith({
                    "families": {
                        "iso": {},
                        "mpls": {},
                    }
                })
            }
        }

    def processDhcpTag(self, o: TagType):
        parent_interface = o.getParent(InterfaceType)
        return {
            self._interfaces_key: {
                **parent_interface.spitInterfacePathWith({
                    "dhcp_profile": [ o.getTagValue() ],
                })
            }
        }

    def processBreakoutTag(self, o: TagType):
        interface = o.getParent(InterfaceType)
        
        if interface.isSubInterface(): 
            warnings.warn(f"Interface {interface.getName()} is a sub-interface, breakout tag needs to be set on parent interface.")
        
        return {
            self._interfaces_key: {
                **interface.spitInterfacePathWith({
                    "breakout": o.getTagValue(),
                })
            }
        }

    def processBgpUnnumberedTag(self, o: TagType):
        parent_interface = o.getParent(InterfaceType)
        opt_unnumbered_interface = {}
        if parent_interface.getVRF():
            loopback_interface = head(list(filter(
                lambda i: i.getName().startswith('lo') and i.getVRF() == parent_interface.getVRF(),
                parent_interface.getParent(DeviceType).getInterfaces()
            )))
            opt_unnumbered_interface = {"unnumbered_interface": loopback_interface.getName()}
        return {
            self._interfaces_key: {
                **parent_interface.spitInterfacePathWith({
                    "unnumbered": True,
                    **opt_unnumbered_interface
                })
            }
        }

    def processAccessTag(self, o: TagType):
        parent_interface = o.getParent(InterfaceType)
        return {
            self._interfaces_key: {
                **parent_interface.spitInterfacePathWith({
                    "port_profile": [ o.getTagValue() ]
                })
            }
        }

    @accept.register
    def _(self, o: TagType):
        match o.getTagName().lower():
            case "autoneg":
                return self.processAutonegTag(o)
            case "speed":
                return self.processSpeedTag(o)
            case "fec":
                return self.processFecTag(o)
            case "urpf":
                return self.processUrpfTag(o)
            case "policer"|"policer_in"|"policer_out":
                return self.processPolicerTag(o)
            case "dhcp":
                return self.processDhcpTag(o)
            case "edge":
                return self.processEdgeTag(o)
            case "core":
                return self.processCoreTag(o)
            case "breakout":
                return self.processBreakoutTag(o)
            case "sonderlocke":
                pass # ignore, as it is treated in "core" tag handler
            case "access":
                return self.processAccessTag(o)
            case "unnumbered":
                return self.processBgpUnnumberedTag(o)
            case "bgp":
                if o.getTagValue() == "cpe":
                    return self.bgpcpe_exporter.accept(o)
                else:
                    warnings.warn(f"unkown bgp tag {o.getTagValue()}")
            case _:
                warnings.warn(f"unknown tag {o.getTagName()}")
