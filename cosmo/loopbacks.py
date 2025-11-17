from dataclasses import dataclass

from cosmo.common import DeviceSerializationError
from cosmo.netbox_types import CosmoLoopbackType


@dataclass
class LoopbackHelper:
    loopbacks: dict[str, CosmoLoopbackType]

    def getByDevice(self, device_name) -> CosmoLoopbackType:
        loopback = self.loopbacks.get(device_name)
        if not isinstance(loopback, CosmoLoopbackType):
            raise DeviceSerializationError(
                f"Couldn't find the loopback for device {device_name}"
            )

        return loopback
