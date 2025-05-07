from abc import ABC

from cosmo.netbox_types import CosmoLoopbackType
from cosmo.visitors import AbstractNoopNetboxTypesVisitor


class AbstractRouterExporterVisitor(AbstractNoopNetboxTypesVisitor, ABC):
    _vrf_key = "routing_instances"
    _interfaces_key = "interfaces"
    _mgmt_vrf_name = "MGMT-ROUTING-INSTANCE"
    _l2circuits_key = "l2circuits"
    _pools_key = "pools"
    _allowed_core_mtus = [9216, 9600, 9230, 9586, 9116]
