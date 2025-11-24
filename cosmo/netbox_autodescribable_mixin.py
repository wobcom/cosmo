from abc import ABCMeta
from collections.abc import MutableMapping
from typing import Self, Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .autodesc import AbstractComposableAutoDescription


class AutoDescribableMixin(MutableMapping, metaclass=ABCMeta):
    _auto_desc_key = "_autodesc"

    def getAutoDescription(self) -> Optional["AbstractComposableAutoDescription"]:
        return self.get(self._auto_desc_key)

    def hasAnAutoDescription(self) -> bool:
        return self.getAutoDescription() is not None

    def setAutoDescription(self, desc: "AbstractComposableAutoDescription") -> Self:
        self[self._auto_desc_key] = desc
        return self
