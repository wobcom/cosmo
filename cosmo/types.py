import abc


class AbstractNetboxType(abc.ABC, dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__mappings = {}
        for c in AbstractNetboxType.__subclasses__():
            self.__mappings.update(c.register())
        for k, v in self.items():
            self[k] = self.convert(v)

    def convert(self, item):
        if isinstance(item, dict):
            if "__typename" in item.keys():
                c = self.__mappings[item["__typename"]]
                return c({k: self.convert(v) for k,v in item.items()})
            else:
                return item
        elif isinstance(item, list):
            replacement = []
            for i in item:
                replacement.append(self.convert(i))
            return replacement
        else:
            return item

    @classmethod
    def _getNetboxType(cls):
        # classes should have the same name as the type name
        # if not, you can override in parent class
        return cls.__name__

    @classmethod
    def register(cls) -> dict:
        return {cls._getNetboxType(): cls}

    def __repr__(self):
        return self._getNetboxType()


class DeviceType(AbstractNetboxType):
    pass


class DeviceTypeType(AbstractNetboxType):
    pass


class PlatformType(AbstractNetboxType):
    pass


class ManufacturerType(AbstractNetboxType):
    pass


class IPAddressType(AbstractNetboxType):
    pass


class InterfaceType(AbstractNetboxType):
    pass


class VRFType(AbstractNetboxType):
    pass


class TagType(AbstractNetboxType):
    pass


class VLANType(AbstractNetboxType):
    pass
