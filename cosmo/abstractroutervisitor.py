from abc import ABC

from cosmo.visitors import AbstractNoopNetboxTypesVisitor


class AbstractRouterExporterVisitor(AbstractNoopNetboxTypesVisitor, ABC):
    _vrf_key = "routing_instances"
    _interfaces_key = "interfaces"
    _mgmt_vrf_name = "MGMT-ROUTING-INSTANCE"
    _l2circuits_key = "l2circuits"
    _vpws_authorized_terminations_n = 2
