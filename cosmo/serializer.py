from typing import Never

from deepmerge import Merger

from cosmo.common import (
    deepsort,
    DeviceSerializationError,
    AbstractRecoverableError,
    head,
    CosmoOutputType,
)
from cosmo.log import error
from cosmo.netbox_types import DeviceType, CosmoLoopbackType
from cosmo.switchvisitor import SwitchDeviceExporterVisitor
from cosmo.routervisitor import RouterDeviceExporterVisitor


class RouterSerializer:
    def __init__(self, device, l2vpn_list, loopbacks, asn):
        self.device = device
        self.l2vpn_list = l2vpn_list
        self.loopbacks = loopbacks
        self.asn = asn

        self.l2vpns = {}
        self.l3vpns = {}
        self.routing_instances = {}
        self.allow_private_ips = False

    def allowPrivateIPs(self):
        self.allow_private_ips = True
        return self

    def serialize(self) -> CosmoOutputType | Never:
        device_stub: CosmoOutputType = {}
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
        self.device["l2vpn_list"] = self.l2vpn_list
        # breakpoint()
        visitor = RouterDeviceExporterVisitor(
            loopbacks_by_device={
                k: CosmoLoopbackType(v) for k, v in self.loopbacks.items()
            },
            asn=self.asn,
        )
        if self.allow_private_ips:
            visitor.allowPrivateIPs()
        latest_errors: list[AbstractRecoverableError] = []
        device = DeviceType(self.device)
        for value in iter(device):
            try:
                new = visitor.accept(value)
                if new:
                    device_stub = merger.merge(device_stub, new)
            except AbstractRecoverableError as e:
                error(f'serialization error "{e}"', value)
                latest_errors.append(e)
                continue  # continue, process as much as possible
        if latest_errors:
            first_error = head(latest_errors)
            # do not return if error during processing
            raise DeviceSerializationError(str(first_error), on=device) from first_error
        return deepsort(device_stub)


class SwitchSerializer:
    def __init__(self, device):
        self.device = device

    def serialize(self) -> CosmoOutputType | Never:
        device_stub: CosmoOutputType = {}
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
        latest_errors: list[AbstractRecoverableError] = []
        device = DeviceType(self.device)
        for value in iter(device):
            try:
                new = SwitchDeviceExporterVisitor().accept(value)
                if new:
                    device_stub = merger.merge(device_stub, new)
            except AbstractRecoverableError as e:
                error(f'serialization error "{e}"', value)
                latest_errors.append(e)
                continue
        if latest_errors:
            first_error = head(latest_errors)
            raise DeviceSerializationError(str(first_error), on=device) from first_error
        return deepsort(device_stub)
