import ipaddress
import warnings
from abc import abstractmethod, ABCMeta
from functools import singledispatchmethod
from typing import TypeVar

from cosmo.abstractroutervisitor import AbstractRouterExporterVisitor
from cosmo.common import head
from cosmo.types import InterfaceType, VLANType, AbstractNetboxType, DeviceType, L2VPNType, CosmoLoopbackType, \
    L2VPNTerminationType


# FIXME simplify this!
class AbstractEncapCapability(metaclass=ABCMeta):
    @singledispatchmethod
    def accept(self, o):
        warnings.warn(f"cannot find suitable encapsulation for type {type(o)}")


class EthernetCccEncapCapability(AbstractEncapCapability, metaclass=ABCMeta):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: InterfaceType):
        if len(o.getTaggedVLANS()) or o.getUntaggedVLAN():
            return
        root_name = o.getSubInterfaceParentInterfaceName() if o.isSubInterface() else o.getName()
        sub_units = list(filter( # costlier check it is then
            lambda i: i.getName().startswith(root_name) and i.isSubInterface(),
            o.getParent(DeviceType).getInterfaces()
        ))
        if len(sub_units) == 1:
            return "ethernet-ccc"


class VlanCccEncapCapability(AbstractEncapCapability, metaclass=ABCMeta):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: VLANType):
        return "vlan-ccc"

    @accept.register
    def _(self, o: InterfaceType):
        # If there is at least one tagged VLAN on the interface or Untagged is not a "unit 0"...
        if len(o.getTaggedVLANS()) or o.getUntaggedVLAN():
            return "vlan-ccc"


class VlanBridgeEncapCapability(AbstractEncapCapability, metaclass=ABCMeta):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: InterfaceType|VLANType):
        return "vlan-bridge"




# generic supported termination types. it's this shape so that it can be directly used by isinstance()
T = tuple[type[AbstractNetboxType]|type[AbstractNetboxType]]|type[AbstractNetboxType]|None

# FIXME simplify this!
class AbstractL2VpnTypeTerminationVisitor(AbstractRouterExporterVisitor, metaclass=ABCMeta):
    def __init__(self, *args, associated_l2vpn: L2VPNType, loopbacks_by_device: dict[str, CosmoLoopbackType],
                 asn: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.associated_l2vpn = associated_l2vpn
        self.loopbacks_by_device = loopbacks_by_device
        self.asn = asn

    def __repr__(self):
        return f"{self.__class__.__name__}({self.associated_l2vpn})"

    @staticmethod
    @abstractmethod
    def getNetboxTypeName() -> str:
        pass

    @staticmethod
    @abstractmethod
    def getAcceptedTerminationTypes() -> T:
        pass

    @staticmethod
    @abstractmethod
    def getSupportedEncapTraits() -> list[type[AbstractEncapCapability]]:
        pass

    @abstractmethod
    def isValidNumberOfTerminations(self, i: int):
        pass

    @classmethod
    def getInvalidNumberOfTerminationsErrorMessage(cls, i: int):
        return f"{cls.getNetboxTypeName().upper()}: {i} is not a valid number of terminations, ignoring..."

    def getChosenEncapType(self, o: AbstractNetboxType) -> str | None:
        chosen_encap = head(list(filter(
            lambda encap: encap is not None,
            [t().accept(o) for t in self.getSupportedEncapTraits()]
        )))
        return chosen_encap

    def processInterfaceTypeTermination(self, o: InterfaceType) -> dict | None:
        warnings.warn(f"{self.getNetboxTypeName().upper()} L2VPN does not support {type(o)} terminations.")
        return

    def processVLANTypeTermination(self, o: VLANType) -> dict | None:
        warnings.warn(f"{self.getNetboxTypeName().upper()} L2VPN does not support {type(o)} terminations.")
        return

    def spitInterfaceEncapFor(self, o: VLANType|InterfaceType):
        encap_type = self.getChosenEncapType(o)
        inner_info = {"encapsulation": encap_type} if encap_type else {} # encap type is optional!
        if encap_type == "ethernet-ccc" and isinstance(o, InterfaceType) and o.isSubInterface():
            return {  # ethernet-ccc is on physical interface
                self._interfaces_key: {
                    o.getSubInterfaceParentInterfaceName(): inner_info
                }
            }
        elif isinstance(o, InterfaceType): # other types are on virtual interface
            return {
                self._interfaces_key: {
                    **o.spitInterfacePathWith(inner_info)
                }
            }
        elif isinstance(o, VLANType):
            linked_interfaces = list(
                    filter(
                        lambda i: i.getAssociatedDevice() == o.getParent(DeviceType),
                        [
                            *o.getInterfacesAsUntagged(),
                            *o.getInterfacesAsTagged(),
                        ]
                    )
            )
            interface_props = {}
            for i in linked_interfaces:
                interface_props = interface_props | i.spitInterfacePathWith(inner_info)
            return {
                self._interfaces_key: interface_props
            }


class AbstractP2PL2VpnTypeTerminationVisitor(AbstractL2VpnTypeTerminationVisitor, metaclass=ABCMeta):
    _p2p_authorized_terminations_n = 2

    def isValidNumberOfTerminations(self, i: int):
        return i == self._p2p_authorized_terminations_n

    @classmethod
    def getInvalidNumberOfTerminationsErrorMessage(cls, i: int):
        return (f"{cls.getNetboxTypeName().upper()} circuits are only allowed to have "
                f"{cls._p2p_authorized_terminations_n} terminations. "
                f"{super().getInvalidNumberOfTerminationsErrorMessage(i)}")


class AbstractAnyToAnyL2VpnTypeTerminationVisitor(AbstractL2VpnTypeTerminationVisitor, metaclass=ABCMeta):
    _any_to_any_min_terminations_n = 1

    def isValidNumberOfTerminations(self, i: int):
        return i >= self._any_to_any_min_terminations_n

    @classmethod
    def getInvalidNumberOfTerminationsErrorMessage(cls, i: int):
        return (f"{cls.getNetboxTypeName().upper()} circuits should have at least "
                f"{cls._any_to_any_min_terminations_n} terminations. "
                f"{super().getInvalidNumberOfTerminationsErrorMessage(i)}")


#                                    |  so that it does not appear in subclasses of any2any
#                                    v or p2p since we're enumerating from there
class AbstractEPLEVPLL2VpnTypeCommon(AbstractL2VpnTypeTerminationVisitor, metaclass=ABCMeta):
    def processInterfaceTypeTermination(self, o: InterfaceType):
        parent_l2vpn = o.getParent(L2VPNType)
        local = next(filter(
            lambda i: (
                    isinstance(i, InterfaceType)
                    and i == o
            ),
            parent_l2vpn.getTerminations()
        ))
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
        } | self.spitInterfaceEncapFor(o)


# for MRO, common need to be 1st
class EPLL2VpnTypeTerminationVisitorAbstract(AbstractEPLEVPLL2VpnTypeCommon, AbstractP2PL2VpnTypeTerminationVisitor):
    @staticmethod
    def getSupportedEncapTraits() -> list[type[AbstractEncapCapability]]:
        return [ # order is important!
            VlanCccEncapCapability,
            EthernetCccEncapCapability,
        ]

    @staticmethod
    def getNetboxTypeName() -> str:
        return "epl"

    @staticmethod
    def getAcceptedTerminationTypes() -> T:
        return InterfaceType


# for MRO, common need to be 1st
class EVPLL2VpnTypeTerminationVisitorAbstract(AbstractEPLEVPLL2VpnTypeCommon, AbstractP2PL2VpnTypeTerminationVisitor):
    @staticmethod
    def getSupportedEncapTraits() -> list[type[AbstractEncapCapability]]:
        return [
            VlanCccEncapCapability,
            EthernetCccEncapCapability,
        ]

    @staticmethod
    def getNetboxTypeName() -> str:
        return "evpl"

    @staticmethod
    def getAcceptedTerminationTypes() -> T:
        return InterfaceType


class VPWSL2VpnTypeTerminationVisitor(AbstractP2PL2VpnTypeTerminationVisitor):
    @staticmethod
    def getSupportedEncapTraits() -> list[type[AbstractEncapCapability]]:
        return [
            VlanCccEncapCapability,
            EthernetCccEncapCapability,
        ]

    @staticmethod
    def getNetboxTypeName() -> str:
        return "vpws"

    @staticmethod
    def getAcceptedTerminationTypes() -> T:
        return InterfaceType

    def processInterfaceTypeTermination(self, o: InterfaceType) -> dict | None:
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
                    "interfaces": [o.getName()],
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
        } | self.spitInterfaceEncapFor(o)


class VXLANEVPNL2VpnTypeTerminationVisitor(AbstractAnyToAnyL2VpnTypeTerminationVisitor):
    @staticmethod
    def getSupportedEncapTraits() -> list[type[AbstractEncapCapability]]:
        return [VlanBridgeEncapCapability]

    @staticmethod
    def getNetboxTypeName() -> str:
        return "vxlan"

    @staticmethod
    def getAcceptedTerminationTypes() -> T:
        return VLANType

    def processVLANTypeTermination(self, o: VLANType) -> dict | None:
        def spitNameForInterfaces(int_or_vlan: InterfaceType | VLANType):
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
                            "vni": [parent_l2vpn.getIdentifier()]
                        }
                    },
                    "bridge_domains": [
                        {
                            # I have to do this, otherwise deepmerge will assume non-uniqueness and we'll have
                            # duplicated bridge_domains. this is because we're within a dict within a list.
                            "interfaces": [spitNameForInterfaces(iov) for iov in parent_l2vpn.getTerminations()],
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
        } | self.spitInterfaceEncapFor(o)


class MPLSEVPNL2VpnTypeTerminationVisitor(AbstractAnyToAnyL2VpnTypeTerminationVisitor):
    @staticmethod
    def getSupportedEncapTraits() -> list[type[AbstractEncapCapability]]:
        return [VlanBridgeEncapCapability]

    @staticmethod
    def getNetboxTypeName() -> str:
        return "mpls-evpn" # no netbox3 retro-compatibility, sorry!

    @staticmethod
    def getAcceptedTerminationTypes() -> T:
        return InterfaceType, VLANType

    def processTerminationCommon(self, o: InterfaceType|VLANType) -> dict|None:
        parent_l2vpn = o.getParent(L2VPNType)
        interface_names = None
        if isinstance(o, InterfaceType):
            interface_names = [o.getName()]
        elif isinstance(o, VLANType):
            interface_names = list(map(
                lambda i: i.getName(),
                (
                    filter(
                        lambda i: i.getAssociatedDevice() == o.getParent(DeviceType),
                        [
                            *o.getInterfacesAsUntagged(),
                            *o.getInterfacesAsTagged(),
                        ]
                    )
                )
            ))

        return {
            self._vrf_key: {
                parent_l2vpn.getName().replace("WAN: ", ""): {
                    "interfaces": interface_names,
                    "description": f"MPLS-EVPN: {parent_l2vpn.getName().replace('WAN: VS_', '')}",
                    "instance_type": "evpn",
                    "protocols": {
                        "evpn": {},
                    },
                    "route_distinguisher": f"{self.asn}:{str(parent_l2vpn.getIdentifier())}",
                    "vrf_target": f"target:1:{str(parent_l2vpn.getIdentifier())}",
                }
            }
        } | self.spitInterfaceEncapFor(o)

    def processInterfaceTypeTermination(self, o: InterfaceType) -> dict | None:
        return self.processTerminationCommon(o)

    def processVLANTypeTermination(self, o: VLANType) -> dict | None:
        return self.processTerminationCommon(o)
