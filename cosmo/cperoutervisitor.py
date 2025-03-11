from functools import singledispatchmethod

from cosmo.types import IPAddressType, DeviceType
from cosmo.visitors import AbstractNoopNetboxTypesVisitor


class CpeRouterIPVisitor(AbstractNoopNetboxTypesVisitor):
    def __init__(self, ip_networks) -> None:
        super().__init__()
        
        self.ip_networks = ip_networks
        
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: IPAddressType):
        ipo = o.getIPInterfaceObject()
        
        for ipn in self.ip_networks:
            if o.getIPInterfaceObject() in ipn:
                return ipo

        return None

class CpeRouterExporterVisitor(AbstractNoopNetboxTypesVisitor):
    """
    This visitor creates a list of networks which are exported from the router
    via unnumbered bgp. We allow all configured IP networks on a CPE to be
    exported. By definition the primary IP is our management IP and this IP
    should not be allowed to be exported via BGP from the router.
    """

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
