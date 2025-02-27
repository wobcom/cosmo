import ipaddress
import warnings
from functools import singledispatchmethod

from cosmo.abstractroutervisitor import AbstractRouterExporterVisitor
from cosmo.common import head
from cosmo.types import L2VPNType, InterfaceType, VLANType, CosmoLoopbackType, L2VPNTerminationType, DeviceType


class RouterL2VPNValidatorVisitor(AbstractRouterExporterVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

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
            warnings.warn(
                f"Found non-interface termination in L2VPN {o.getName()}, ignoring... "
                f"VPWS only supports interface terminations."
            )
            return False
        return True

    @accept.register
    def _(self, o: L2VPNType):
        if o.getName().startswith("WAN"):
            self.isCompliantWANL2VPN(o)


class RouterL2VPNExporterVisitor(AbstractRouterExporterVisitor):
    def __init__(self, *args, loopbacks_by_device: dict[str, CosmoLoopbackType], asn: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.loopbacks_by_device = loopbacks_by_device
        self.asn = asn

    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @staticmethod
    def getAssociatedEncapType(o: InterfaceType | VLANType) -> str|None:
        # TODO: move me in manufacturer strategy?
        l2vpn_type = o.getParent(L2VPNType).getType().lower()
        is_eligible_for_vlan_encap = False
        is_eligible_for_ethernet_ccc_encap = False
        if isinstance(o, VLANType):
            is_eligible_for_vlan_encap = True
        elif isinstance(o, InterfaceType) and (len(o.getTaggedVLANS()) or o.getUntaggedVLAN()):
            is_eligible_for_vlan_encap = True
        elif isinstance(o, InterfaceType) and not (len(o.getTaggedVLANS()) or o.getUntaggedVLAN()):
            root_name = o.getSubInterfaceParentInterfaceName() if o.isSubInterface() else o.getName()
            sub_units = list(filter( # costlier check it is then
                lambda i: i.getName().startswith(root_name) and i.isSubInterface(),
                o.getParent(DeviceType).getInterfaces()
            ))
            if len(sub_units) == 1: # we can use ethernet ccc encap only when there's 1 sub interface
                is_eligible_for_ethernet_ccc_encap = True
        if l2vpn_type in ["vpws", "evpl"] and is_eligible_for_vlan_encap:
            return "vlan-ccc"
        elif l2vpn_type in ["vpws", "epl", "evpl"] and is_eligible_for_ethernet_ccc_encap:
            return "ethernet-ccc"
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
                            "local_label": 1_000_000 + int(local.getParent(L2VPNTerminationType).getID()),
                            "remote_label": 1_000_000 + int(remote.getParent(L2VPNTerminationType).getID()),
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
                    "route_distinguisher": f"{self.asn}:{str(parent_l2vpn.getIdentifier())}",
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
        return {
            self._vrf_key: {
                parent_l2vpn.getName().replace("WAN: ", ""): {
                    "interfaces": [ o.getName() ],
                    "description": f"VPWS: {parent_l2vpn.getName().replace('WAN: VS_', '')}",
                    "instance_type": "evpn-vpws",
                    "route-distinguisher": f"{self.asn}:{str(parent_l2vpn.getIdentifier())}",
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

    def processL2vpnVxlanTerminationInterface(self, o: InterfaceType):
        def spitNameForInterfaces(int_or_vlan: InterfaceType|VLANType):
            if isinstance(int_or_vlan, InterfaceType):
                return int_or_vlan.getName()
        parent_l2vpn = o.getParent(L2VPNType)
        vlan_id = None
        if o.getUntaggedVLAN():
            vlan_id = o.getUntaggedVLAN().getVID()
        return {
            self._vrf_key: {
                parent_l2vpn.getName().replace("WAN: ", ""): {
                    "description": f"Virtual Switch {parent_l2vpn.getName().replace('WAN: VS_', '')}",
                    "instance-type": "virtual-switch",
                    "route_distinguisher": f"{self.asn}:{str(parent_l2vpn.getIdentifier())}",
                    "vrf_target": f"target:1:{str(parent_l2vpn.getIdentifier())}",
                    "protocols": {
                        "evpn": {
                            "vni": [ parent_l2vpn.getIdentifier() ]
                        }
                    },
                    "bridge_domains": [
                        {
                            # I have to do this, otherwise deepmerge will assume non-uniqueness and we'll have
                            # duplicated bridge_domains. this is because we're within a dict within a list.
                            "interfaces": [ spitNameForInterfaces(iov) for iov in parent_l2vpn.getTerminations() ],
                            "vlan_id": vlan_id,
                            "name": parent_l2vpn.getName(),
                            "vxlan": {
                                "ingress_node_replication": True,
                                "vni": parent_l2vpn.getIdentifier(),
                            }
                        }
                    ]
                }
            }
        }

    def processL2VPNTerminationInterface(self, o: InterfaceType):
        parent_l2vpn = o.getParent(L2VPNType)
        device = parent_l2vpn.getParent(DeviceType)
        # guard: processed L2VPN should have at least one termination belonging to current device
        # if no termination passes this test, then L2VPN is not processed.
        if not o in device.getInterfaces():
            return
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
        elif l2vpn_type in ["vxlan-evpn", "vxlan_evpn"]:
            optional_attrs = self.processL2vpnVxlanTerminationInterface(o)
        elif l2vpn_type in ["vpws"]:
            optional_attrs = self.processL2vpnVpwsTerminationInterface(o)
        interface_attr = o.spitInterfacePathWith(encapsulation)
        if encap_type == "ethernet-ccc" and o.isSubInterface():
            # ethernet-ccc encapsulation attr is always on interface, not unit
            interface_attr = {o.getSubInterfaceParentInterfaceName(): encapsulation}
        return {
            self._interfaces_key: {
                **interface_attr
            }
        } | optional_attrs

    def processL2VPNTerminationVLAN(self, o: VLANType):
        parent_l2vpn = o.getParent(L2VPNType)
        device = parent_l2vpn.getParent(DeviceType)
        # guard: processed L2VPN should have at least one termination belonging to current device
        # if no termination passes this test, then L2VPN is not processed.
        if (o.getInterfacesAsUntagged() not in device.getInterfaces() or
                o.getInterfacesAsTagged() not in device.getInterfaces()):
            return
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
    def _(self, o: InterfaceType):
        return self.processL2VPNTerminationInterface(o)

    @accept.register
    def _(self, o: VLANType):
        return self.processL2VPNTerminationVLAN(o)
