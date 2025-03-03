import abc
from functools import singledispatchmethod


class AbstractNoopNetboxTypesVisitor(abc.ABC):
    @singledispatchmethod
    def accept(self, o):
        raise NotImplementedError(f"unsupported type {o}")

    @accept.register
    def _(self, o: int):
        return

    @accept.register
    def _(self, o: None):
        return

    @accept.register
    def _(self, o: str):
        return

    @accept.register
    def _(self, o: dict) -> dict:
        return {}

    @accept.register
    def _(self, o: list) -> list:
        return []
