from functools import singledispatchmethod
from cosmo.visitors import AbstractNoopNetboxTypesVisitor


class RouterDeviceExporterVisitor(AbstractNoopNetboxTypesVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)
