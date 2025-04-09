from abc import abstractmethod, ABCMeta
from typing import Self

from cosmo.types import AbstractNetboxType


class AbstractLogLevel(metaclass=ABCMeta):
    name: str = "abstract_log_level"
    def __str__(self):
        return f"[{self.name.upper()}]"

class InfoLogLevel(AbstractLogLevel):
    name = "info"
class WarningLogLevel(AbstractLogLevel):
    name = "warning"
class ErrorLogLevel(AbstractLogLevel):
    name = "error"


O = object | AbstractNetboxType | None # object-being-logged-on type
M = tuple[AbstractLogLevel, str, O] # message type

class AbstractLoggingStrategy(metaclass=ABCMeta):
    @abstractmethod
    def flush(self): # this is for async and sync logging
        pass
    @abstractmethod
    def info(self, message: str, on: O):
        pass
    @abstractmethod
    def warn(self, message: str, on: O):
        pass
    @abstractmethod
    def error(self, message: str, on: O):
        pass


class JsonLoggingStrategy(AbstractLoggingStrategy):
    info_queue: list[M] = []
    warning_queue: list[M] = []
    error_queue: list[M] = []

    @staticmethod
    def _toJSON(m: M) -> dict:
        loglevel, message, obj = m
        obj_dict = {}
        if obj is not None:
            obj_dict = { "object": obj }
        return {
            "level": loglevel.name,
            "message": message,
            **obj_dict,
        }

    def info(self, message: str, on: O):
        self.info_queue.append((InfoLogLevel(), message, on))

    def warn(self, message: str, on: O):
        self.warning_queue.append((WarningLogLevel(), message, on))

    def error(self, message: str, on: O):
        self.error_queue.append((ErrorLogLevel(), message, on))

    def flush(self):
        # JSON-RPC like
        res = {}
        if len(self.warning_queue) + len(self.error_queue) == 0:
            res = {
                "result": list(map(self._toJSON, self.info_queue)),
            }
        else:
            res = {
                "error": list(map(self._toJSON, self.error_queue)),
                "warning": list(map(self._toJSON, self.warning_queue)),
            }
        print(res)


class HumanReadableLoggingStrategy(AbstractLoggingStrategy):
    def info(self, message: str, on: O):
        print(f"{InfoLogLevel()} {message}")

    def warn(self, message: str, on: O):
        print(f"{WarningLogLevel()} {message}")

    def error(self, message: str, on: O):
        print(f"{ErrorLogLevel()} {message}")

    def flush(self):
        pass


class CosmoLogger:
    strategy: AbstractLoggingStrategy

    def setLoggingStrategy(self, strategy: AbstractLoggingStrategy) -> Self:
        self.strategy = strategy
        return self

    def flush(self) -> Self:
        self.strategy.flush()
        return self

    def getLoggingStrategy(self) -> AbstractLoggingStrategy:
        return self.strategy

    def info(self, message: str, on: O):
        self.strategy.info(message, on)

    def warn(self, message: str, on: O):
        self.strategy.warn(message, on)

    def error(self, message: str, on: O):
        self.strategy.error(message, on)


def info(string: str) -> None:
    logger.info(string, None)


logger = CosmoLogger().setLoggingStrategy(HumanReadableLoggingStrategy())
