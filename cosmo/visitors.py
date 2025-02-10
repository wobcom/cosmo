import abc
from .common import without_keys
from functools import singledispatchmethod, wraps


def dictlike(fun):
    @wraps(fun)
    def wrapper(self, *args, **kwargs):
        return self._dictLikeTemplateMethod(fun(self, *args, **kwargs))
    return wrapper


class AbstractNoopNetboxTypesVisitor(abc.ABC):
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
        for key in list(without_keys(o,"__parent").keys()):
            o[key] = self.accept(o[key])
        return o

    @accept.register
    def _(self, o: dict) -> dict:
        return self._dictLikeTemplateMethod(o)

    @accept.register
    def _(self, o: list) -> list:
        for i, v in enumerate(o):
            o[i] = self.accept(v)
        return o
