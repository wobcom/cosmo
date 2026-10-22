import ipaddress
from multimethod import multimethod as singledispatchmethod

from cosmo import log
from cosmo.abstractroutervisitor import AbstractRouterExporterVisitor
from cosmo.common import (
    head,
    L2VPNSerializationError,
    DeviceSerializationError,
    DEFAULT_LOGICAL_MTU,
    IEEE8023_HDR_BYTES,
    IEEE8021Q_HDR_BYTES,
    DEFAULT_PHY_MTU,
)
from cosmo.config.cosmo_config import CosmoConfig
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
        self, *args, loopbacks: LoopbackHelper, cosmo_config: CosmoConfig, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.loopbacks = loopbacks
        self._cosmo_config = cosmo_config
        self.asn = self._cosmo_config["asn"]

    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    def getL2VpnTypeTerminationObjectFrom(
        self, o: L2VPNType
    ) -> AbstractL2VpnTypeTerminationVisitor:
        return L2VpnVisitorClassFactoryFromL2VpnTypeObject(o).get()(
            associated_l2vpn=o,
            loopbacks=self.loopbacks,
            cosmo_config=self._cosmo_config,
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

    def isCompliantInterface(self, o: InterfaceType):
        if o.getAssociatedDevice() != o.getParent(
            DeviceType
        ):  # guard: reject interfaces associated to other devices
            return
        phy = o.getPhysicalInterfaceByFilter()
        if not phy:
            raise L2VPNSerializationError(
                "cannot find physical interface attached to L2VPN termination", on=o
            )
        current_media_mtu = int(phy.getMTU() or DEFAULT_PHY_MTU)
        manual_media_mtu = phy.getMTU() is not None or False
        if phy != o:  # sub interface
            l2vpn_type = self.getL2VpnTypeTerminationObjectFrom(o.getParent(L2VPNType))
            encap_type = l2vpn_type.getChosenEncapType(o)
            encap_supplementary_bytes = (
                encap_type.supplementaryHeaderBytes() if encap_type else 0
            )
            current_logical_mtu = int(o.getMTU() or DEFAULT_LOGICAL_MTU)
            manual_logical_mtu = o.getMTU() is not None or False
            min_target_media_mtu = DEFAULT_PHY_MTU + encap_supplementary_bytes
            # if the logical MTU is too high relatively to media MTU,
            # it will automatically be capped to the appropriate value, taking into account
            # protocol overhead. this may result in an effective logical MTU lower than the
            # "standard" 1500 bytes, especially in cases where encapsulations such as
            # vlan-bridge and vlan-ccc are used.
            if (
                current_media_mtu < min_target_media_mtu
            ):  # logical mtu insufficient to avoid clamping
                log.warn(
                    f"media MTU of {current_media_mtu} is insufficient for {l2vpn_type.getNetboxTypeName()}. "
                    f"customer traffic will be clamped below standard size.",
                    o,
                )
            if (
                current_logical_mtu + IEEE8023_HDR_BYTES > current_media_mtu
            ):  # clamping active
                if (
                    manual_logical_mtu and manual_media_mtu
                ):  # clamping active and both media MTU and logical MTU are configured by user
                    # generation should be aborted if a configured physical MTU clamps a configured logical MTU
                    # and is not effective.
                    raise L2VPNSerializationError(
                        f"Mismatched L2VPN MTU configuration, check physical and "
                        f"logical interface MTU please. Expected {min_target_media_mtu}, got {current_media_mtu} "
                        f"for encap type {encap_type}",
                        on=o,
                    )
                else:  # clamping active without above specific case
                    # user should be warned if a higher configured logical MTU is clamped and not effective,
                    # as not to break existing configurations.
                    log.warn(
                        f"logical MTU of {current_logical_mtu} will be clamped by media "
                        f"MTU of {current_media_mtu}, please check your configuration",
                        on=o,
                    )

    @accept.register
    def _(self, o: L2VPNType):
        self.isCompliantWANL2VPN(o)

    @accept.register
    def _(self, o: InterfaceType):
        self.isCompliantInterface(o)

    @accept.register
    def _(self, o: VLANType):
        pass  # TODO


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
