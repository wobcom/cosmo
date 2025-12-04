from abc import ABCMeta
from typing import Never, Callable

from deepmerge import Merger

from cosmo.autodescvisitor import MutatingAutoDescVisitor
from cosmo.common import (
    deepsort,
    DeviceSerializationError,
    AbstractRecoverableError,
    head,
    CosmoOutputType,
)
from cosmo.features import features
from cosmo.log import error
from cosmo.netbox_types import DeviceType, CosmoLoopbackType, AbstractNetboxType
from cosmo.loopbacks import LoopbackHelper
from cosmo.netbox_types import DeviceType, CosmoLoopbackType
from cosmo.switchvisitor import SwitchDeviceExporterVisitor
from cosmo.routervisitor import RouterDeviceExporterVisitor


class AbstractSerializer(metaclass=ABCMeta):
    def __init__(self, device):
        self.device = DeviceType(device)

    @staticmethod
    def getMerger():
        # like always_merger but with append_unique strategy
        # for lists
        merger = Merger(
            [
                (list, ["append_unique"]),
                (dict, ["merge"]),
                (set, ["union"]),
            ],
            ["override"],
            ["override"],
        )
        return merger

    @staticmethod
    def autoDescPreprocess(_: CosmoOutputType, value: AbstractNetboxType):
        if not features.featureIsEnabled("interface-auto-descriptions"):
            return  # early return / skip
        MutatingAutoDescVisitor().accept(value)

    def walk(
        self,
        device_stub: CosmoOutputType,
        item_f: Callable[[CosmoOutputType, AbstractNetboxType], None],
    ) -> list[AbstractRecoverableError]:
        latest_errors: list[AbstractRecoverableError] = []
        for value in iter(self.device):
            try:
                item_f(device_stub, value)
            except AbstractRecoverableError as e:
                error(f'serialization error "{e}"', value)
                latest_errors.append(e)
                continue
        return latest_errors

    def processErrors(self, latest_errors):
        if latest_errors:
            first_error = head(latest_errors)
            raise DeviceSerializationError(
                str(first_error), on=self.device
            ) from first_error


class RouterSerializer(AbstractSerializer):
    def __init__(self, device, l2vpn_list, loopbacks, asn):
        super().__init__(device)
        self.l2vpn_list = l2vpn_list
        self.device["l2vpn_list"] = self.l2vpn_list
        self.device = DeviceType(self.device)
        self.loopbacks = loopbacks
        self.asn = asn

        self.l2vpns = {}
        self.l3vpns = {}
        self.routing_instances = {}
        self.allow_private_ips = False

        loopbacks = {
            key: CosmoLoopbackType(**loopback)
            for (key, loopback) in self.loopbacks.items()
        }
        loopback_helper = LoopbackHelper(loopbacks)
        self.router_device_export_visitor = RouterDeviceExporterVisitor(
            loopbacks=loopback_helper,
            asn=self.asn,
        )
        if self.allow_private_ips:
            self.router_device_export_visitor.allowPrivateIPs()

    def allowPrivateIPs(self):
        self.router_device_export_visitor.allowPrivateIPs()
        return self

    def routerExport(self, device_stub: CosmoOutputType, value: AbstractNetboxType):
        new = self.router_device_export_visitor.accept(value)
        if new:
            device_stub = self.getMerger().merge(device_stub, new)

    def serialize(self) -> CosmoOutputType | Never:
        device_stub: CosmoOutputType = {}
        latest_errors: list[AbstractRecoverableError] = []
        latest_errors.extend(self.walk(device_stub, self.autoDescPreprocess))
        latest_errors.extend(self.walk(device_stub, self.routerExport))
        self.processErrors(latest_errors)
        return deepsort(device_stub)


class SwitchSerializer(AbstractSerializer):
    def switchExport(self, device_stub: CosmoOutputType, value: AbstractNetboxType):
        new = SwitchDeviceExporterVisitor().accept(value)
        if new:
            device_stub = self.getMerger().merge(device_stub, new)

    def serialize(self) -> CosmoOutputType | Never:
        device_stub: CosmoOutputType = {}
        latest_errors: list[AbstractRecoverableError] = []
        latest_errors.extend(self.walk(device_stub, self.autoDescPreprocess))
        latest_errors.extend(self.walk(device_stub, self.switchExport))
        self.processErrors(latest_errors)
        return deepsort(device_stub)
