from functools import singledispatchmethod

from cosmo.types import IPAddressType, DeviceType
from cosmo.visitors import AbstractNoopNetboxTypesVisitor


class CpeRouterExporterVisitor(AbstractNoopNetboxTypesVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: IPAddressType):
        primary_ip4 = o.getParent(DeviceType)["primary_ip4"]
        if primary_ip4 and primary_ip4.getIPAddress() == o.getIPAddress():
            return # skip
        ip_interface = o.getIPInterfaceObject()
        return type(ip_interface), ip_interface.network.with_prefixlen
