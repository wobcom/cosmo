from abc import ABCMeta, abstractmethod


class TobagoAbstractTerminationType(metaclass=ABCMeta):
    def __init__(self, data: dict):
        self._store = data

    @classmethod
    def accepts(cls, termination_type: str) -> bool:
        return cls.getTypeName() == termination_type

    @classmethod
    @abstractmethod
    def getTypeName(cls) -> str:
        pass

    @abstractmethod
    def __str__(self):
        pass


class TobagoDeviceNameTrait(metaclass=ABCMeta):
    def __init__(self, data: dict):
        self._store = data

    def __str__(self):
        return f"{self._store['device']['name']},  {self._store['name']}"


class TobagoCircuitTerminationType(TobagoAbstractTerminationType):
    @classmethod
    def getTypeName(cls) -> str:
        return "circuits.circuittermination"

    def __str__(self):
        return f"circuit {self._store['display']}"


class TobagoInterfaceTerminationType(
    TobagoDeviceNameTrait, TobagoAbstractTerminationType
):
    @classmethod
    def getTypeName(cls) -> str:
        return "dcim.interface"


class TobagoFrontPortTerminationType(
    TobagoDeviceNameTrait, TobagoAbstractTerminationType
):
    @classmethod
    def getTypeName(cls) -> str:
        return "dcim.frontport"


class TobagoRearPortTerminationType(
    TobagoDeviceNameTrait, TobagoAbstractTerminationType
):
    @classmethod
    def getTypeName(cls) -> str:
        return "dcim.rearport"


class TobagoConsolePortTerminationType(
    TobagoDeviceNameTrait, TobagoAbstractTerminationType
):
    @classmethod
    def getTypeName(cls) -> str:
        return "dcim.consoleport"


class TobagoConsoleServerPortTerminationType(
    TobagoDeviceNameTrait, TobagoAbstractTerminationType
):
    @classmethod
    def getTypeName(cls) -> str:
        return "dcim.consoleserverport"
