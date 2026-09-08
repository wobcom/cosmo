import abc
from abc import ABC


class AbstractNoopNetboxTypesVisitor(abc.ABC):
    def accept(self, o):
        # use raise NotImplementedError(f"unsupported type {o}")
        # when you're adding new types and you want to check your
        # visitor gets everything
        return


class AbstractRouterExporterVisitor(AbstractNoopNetboxTypesVisitor, ABC):
    _interfaces_key = "interfaces"
    _mgmt_vrf_description = "MGMT-ROUTING-INSTANCE"
    _l2circuits_key = "l2circuits"
    _pools_key = "pools"
    _allowed_core_mtus = [9216, 9586, 9116]
