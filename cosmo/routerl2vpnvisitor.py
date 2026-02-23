import ipaddress
from multimethod import multimethod as singledispatchmethod

from cosmo.abstractroutervisitor import AbstractRouterExporterVisitor
from cosmo.common import head, L2VPNSerializationError
from cosmo.l2vpnhelpertypes import (
    L2VpnVisitorClassFactoryFromL2VpnTypeObject,
    AbstractL2VpnTypeTerminationVisitor,
)
from cosmo.loopbacks import LoopbackHelper
from cosmo.netbox_types import (
    L2VPNType,
    InterfaceType,
    VLANType,
    CosmoLoopbackType,
    L2VPNTerminationType,
    DeviceType,
)


class AbstractL2VPNVisitor(AbstractRouterExporterVisitor):
    def __init__(
        self,
        *args,
        loopbacks: LoopbackHelper,
        asn: int,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.loopbacks = loopbacks
        self.asn = asn

    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    def getL2VpnTypeTerminationObjectFrom(
        self, o: L2VPNType
    ) -> AbstractL2VpnTypeTerminationVisitor:
        return L2VpnVisitorClassFactoryFromL2VpnTypeObject(o).get()(
            associated_l2vpn=o,
            loopbacks=self.loopbacks,
            asn=self.asn,
        )


class RouterL2VPNValidatorVisitor(AbstractL2VPNVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    def isCompliantWANL2VPN(self, o: L2VPNType):
        terminations = o.getTerminations()
        identifier = o.getIdentifier()
        l2vpn_type = self.getL2VpnTypeTerminationObjectFrom(o)
        if not l2vpn_type.isValidRawName(o.getName()):
            raise L2VPNSerializationError(f'L2VPN "{o.getName()}" is incorrectly named')
        if not l2vpn_type.isValidNumberOfTerminations(len(terminations)):
            raise L2VPNSerializationError(
                f"for {o.getName()}: "
                f"{l2vpn_type.getInvalidNumberOfTerminationsErrorMessage(len(terminations))}"
            )
        if any(
            [
                not isinstance(t, l2vpn_type.getAcceptedTerminationTypes())
                for t in terminations
            ]
        ):
            raise L2VPNSerializationError(
                f'Found unsupported L2VPN termination in "{o.getName()}". '
                f"Accepted types are: {l2vpn_type.getAcceptedTerminationTypes()}"
            )

    @accept.register
    def _(self, o: L2VPNType):
        self.isCompliantWANL2VPN(o)


class RouterL2VPNExporterVisitor(AbstractL2VPNVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: InterfaceType):
        l2vpn_type = self.getL2VpnTypeTerminationObjectFrom(o.getParent(L2VPNType))
        # guard: processed l2vpn should have at least 1 termination belonging
        # to current device.
        if o in o.getParent(DeviceType).getInterfaces():
            return l2vpn_type.processInterfaceTypeTermination(o)

    @accept.register
    def _(self, o: VLANType):
        l2vpn_type = self.getL2VpnTypeTerminationObjectFrom(o.getParent(L2VPNType))
        # guard: processed l2vpn should have at least 1 termination belonging
        # to current device. if no termination passes the test, then l2vpn
        # is not processed.
        device_interfaces = o.getParent(DeviceType).getInterfaces()
        if any(i in device_interfaces for i in o.getInterfacesAsUntagged()) or any(
            i in device_interfaces for i in o.getInterfacesAsTagged()
        ):
            return l2vpn_type.processVLANTypeTermination(o)
