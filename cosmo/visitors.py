import abc
from functools import singledispatchmethod


class AbstractNoopNetboxTypesVisitor(abc.ABC):
    @singledispatchmethod
    def accept(self, o):
        # use raise NotImplementedError(f"unsupported type {o}")
        # when you're adding new types and you want to check your
        # visitor gets everything
        return

    @accept.register
    def _(self, o: dict) -> dict:
        return {}

    @accept.register
    def _(self, o: list) -> list:
        return []
