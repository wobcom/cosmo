from os import PathLike
from pathlib import Path
from string import Template
from abc import ABC, abstractmethod
from typing import Optional, Union, Protocol, TypeVar, Sequence

APP_NAME = "cosmo"


class AbstractRecoverableError(Exception, ABC):
    def __init__(self, text: str, on: Optional[object] = None, *args):
        super().__init__(text, *args)
        self.associated_object = on


class DeviceSerializationError(AbstractRecoverableError):
    pass


class InterfaceSerializationError(AbstractRecoverableError):
    pass


class StaticRouteSerializationError(AbstractRecoverableError):
    pass


class L2VPNSerializationError(AbstractRecoverableError):
    pass


class AutoDescriptionError(AbstractRecoverableError):
    pass


# recursive type for the shape of cosmo output. use it when specifying something that
# the visitors will export.
CosmoOutputType = dict[
    str, str | dict[str, "CosmoOutputType"] | list[str] | list["CosmoOutputType"]
]

JsonOutputType = CosmoOutputType

T_contra = TypeVar("T_contra", contravariant=True)


class Comparable(Protocol[T_contra]):
    @abstractmethod
    def __lt__(self: T_contra, other: T_contra) -> bool:
        pass


# from https://gist.github.com/M-Bryant/049d9e45bf0b749bc715de9eb70b22fc
def strictly_decreasing(l: Sequence[Comparable]) -> bool:
    return all(x > y for x, y in zip(l, l[1:]))


# next() can raise StopIteration, so that's why I use this function
# FIXME: should be head[T](l: list[T]) -> Optional[T]
def head(l):
    return None if not l else l[0]


def deepsort(e):
    if isinstance(e, list):
        return sorted(deepsort(v) for v in e)
    elif isinstance(e, dict):
        return {k: deepsort(v) for k, v in e.items()}
    return e


def without_keys(d, keys) -> dict:
    if type(keys) != list:
        keys = [keys]
    return {k: v for k, v in d.items() if k not in keys}


class FileTemplate(Template):
    def __init__(self, template_file_path: str | bytes | PathLike):
        with open(template_file_path, "r") as template_file:
            template = template_file.read()
            super().__init__(template)
