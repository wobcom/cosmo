import ipaddress
import warnings
from functools import singledispatchmethod

from cosmo.abstractroutervisitor import AbstractRouterExporterVisitor
from cosmo.common import head
from cosmo.l2vpnhelpertypes import AbstractP2PL2VpnTypeTerminationVisitor, AbstractAnyToAnyL2VpnTypeTerminationVisitor
from cosmo.types import L2VPNType, InterfaceType, VLANType, CosmoLoopbackType, L2VPNTerminationType, DeviceType


class AbstractL2VPNVisitor(AbstractRouterExporterVisitor):
    def __init__(self, *args, loopbacks_by_device: dict[str, CosmoLoopbackType]=None, asn: int=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.loopbacks_by_device = loopbacks_by_device
        self.asn = asn

    _typename_to_type_class = {
        c.getNetboxTypeName(): c for c in [
            *AbstractP2PL2VpnTypeTerminationVisitor.__subclasses__(),
            *AbstractAnyToAnyL2VpnTypeTerminationVisitor.__subclasses__()
        ]
    }

    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    def getAssociatedTypeObject(self, o: L2VPNType):
        return self._typename_to_type_class.get(o.getType().lower())(
            loopbacks_by_device=self.loopbacks_by_device, asn=self.asn
        )


class RouterL2VPNValidatorVisitor(AbstractL2VPNVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    def isCompliantWANL2VPN(self, o: L2VPNType) -> bool:
        terminations = o.getTerminations()
        l2vpn_type = self.getAssociatedTypeObject(o)
        if not l2vpn_type.isValidNumberOfTerminations(len(terminations)):
            warnings.warn(f"for {o.getName()}: "
                          f"{l2vpn_type.getInvalidNumberOfTerminationsErrorMessage(len(terminations))}")
            return False
        if any([not isinstance(t, l2vpn_type.getAcceptedTerminationTypes()) for t in terminations]):
            warnings.warn(f"Found unsupported L2VPN termination in \"{o.getName()}\". "
                          f"Accepted types are: {l2vpn_type.getAcceptedTerminationTypes()}")
            return False
        return True

    @accept.register
    def _(self, o: L2VPNType):
        if o.getName().startswith("WAN"):
            self.isCompliantWANL2VPN(o)


class RouterL2VPNExporterVisitor(AbstractL2VPNVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: InterfaceType):
        l2vpn_type = self.getAssociatedTypeObject(o.getParent(L2VPNType))
        # guard: processed l2vpn should have at least 1 termination belonging
        # to current device.
        if o in o.getParent(DeviceType).getInterfaces():
            return l2vpn_type.processInterfaceTypeTermination(o)

    @accept.register
    def _(self, o: VLANType):
        l2vpn_type = self.getAssociatedTypeObject(o.getParent(L2VPNType))
        # guard: processed l2vpn should have at least 1 termination belonging
        # to current device. if no termination passes the test, then l2vpn
        # is not processed.
        device_interfaces = o.getParent(DeviceType).getInterfaces()
        if (
                o.getInterfacesAsUntagged() in device_interfaces or
                o.getInterfacesAsTagged() in device_interfaces
        ):
            return l2vpn_type.processVLANTypeTermination(o)
