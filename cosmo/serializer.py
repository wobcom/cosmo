from deepmerge import Merger

from cosmo.common import deepsort, DeviceSerializationError
from cosmo.types import DeviceType, CosmoLoopbackType
from cosmo.switchvisitor import SwitchDeviceExporterVisitor
from cosmo.routervisitor import RouterDeviceExporterVisitor



class RouterSerializer:
    def __init__(self, device, l2vpn_list, loopbacks):
        try:
            match device["platform"]["manufacturer"]["slug"]:
                case 'juniper':
                    self.mgmt_routing_instance = "mgmt_junos"
                    self.mgmt_interface = "fxp0"
                    self.bmc_interface = None
                case 'rtbrick':
                    self.mgmt_routing_instance = "mgmt"
                    self.mgmt_interface = "ma1"
                    self.bmc_interface = "bmc0"
                case other:
                    raise DeviceSerializationError(f"unsupported platform vendor: {other}")
                    return
        except KeyError as ke:
            raise KeyError(f"missing key in device info, can't continue.") from ke

        self.device = device
        self.l2vpn_list = l2vpn_list
        self.loopbacks = loopbacks

        self.l2vpns = {}
        self.l3vpns = {}
        self.routing_instances = {}

    def serialize(self):
        device_stub = {}
        # like always_merger but with append_unique strategy
        # for lists
        merger = Merger(
            [
                (list, ["append_unique"]),
                (dict, ["merge"]),
                (set, ["union"]),
            ],
            ["override"],
            ["override"]
        )
        self.device['l2vpn_list'] = self.l2vpn_list
        # breakpoint()
        visitor = RouterDeviceExporterVisitor(
            loopbacks_by_device={k: CosmoLoopbackType(v) for k, v in self.loopbacks.items()},
            asn=9136,
        )
        for value in iter(DeviceType(self.device)):
            new = visitor.accept(value)
            if new:
                device_stub = merger.merge(device_stub, new)
        return deepsort(device_stub)


class SwitchSerializer:
    def __init__(self, device):
        self.device = device

    def serialize(self):
        device_stub = {}
        # like always_merger but with append_unique strategy
        # for lists
        merger = Merger(
            [
                (list, ["append_unique"]),
                (dict, ["merge"]),
                (set, ["union"]),
            ],
            ["override"],
            ["override"]
        )
        for value in iter(DeviceType(self.device)):
            new = SwitchDeviceExporterVisitor().accept(value)
            if new:
                device_stub = merger.merge(device_stub, new)
        return deepsort(device_stub)
