from functools import singledispatchmethod

from cosmo.types import L2VPNType, VRFType, CosmoLoopbackType
from cosmo.visitors import AbstractNoopNetboxTypesVisitor


class RouterDeviceExporterVisitor(AbstractNoopNetboxTypesVisitor):
    def __init__(self, l2vpn_list: list[L2VPNType], vrf_list: list[VRFType],
                 loopback_list: list[CosmoLoopbackType], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.l2vpn_list = l2vpn_list
        self.vrf_list = vrf_list
        self.loopback_list = loopback_list

    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)
