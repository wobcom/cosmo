import abc
from copy import deepcopy
from functools import singledispatchmethod


class AbstractNoopNetboxTypesVisitor(abc.ABC):
    def __init__(self, *args, **kwargs):
        for c in AbstractNoopNetboxTypesVisitor.__subclasses__():
            self.accept.register(
                c,
                lambda self, o: self._dictLikeTemplateMethod(o)
            )

    @singledispatchmethod
    def accept(self, o):
        raise NotImplementedError(f"unsupported type {o}")

    @accept.register
    def _(self, o: int):
        return o

    @accept.register
    def _(self, o: None):
        return o

    @accept.register
    def _(self, o: str):
        return o

    def _dictLikeTemplateMethod(self, o):
        breakpoint()
        o = deepcopy(o)
        keys = list(o.keys())
        for key in keys:
            self._mutateDictKVTemplateMethod(o, key)
        return o

    def _mutateDictKVTemplateMethod(self, o, key):
        o[key] = self.accept(o[key])

    @accept.register
    def _(self, o: dict) -> dict:
        return self._dictLikeTemplateMethod(o)

    @accept.register
    def _(self, o: list) -> list:
        o = deepcopy(o)
        for i, v in enumerate(o):
            o[i] = self.accept(v)
        return o
