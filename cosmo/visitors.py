import abc
from functools import singledispatchmethod


class AbstractNoopNetboxTypesVisitor(abc.ABC):
    @singledispatchmethod
    def accept(self, o):
        raise NotImplementedError(f"unsupported type {o}")

    @accept.register
    def _(self, o: int):
        pass

    @accept.register
    def _(self, o: None):
        pass

    @accept.register
    def _(self, o: str):
        pass

    @accept.register
    def _(self, o: dict) -> dict:
        pass

    @accept.register
    def _(self, o: list) -> list:
        pass
