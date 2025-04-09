import json
import sys
from abc import abstractmethod, ABCMeta
from typing import Self

from cosmo.common import AbstractRecoverableError, JsonOutputType
from cosmo.netbox_types import AbstractNetboxType


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
    @abstractmethod
    def exceptionHook(self, exception: type[BaseException], value: BaseException, traceback):
        pass


class JsonLoggingStrategy(AbstractLoggingStrategy):
    info_queue: list[M] = []
    warning_queue: list[M] = []
    error_queue: list[M] = []

    @staticmethod
    def _messageToJSON(m: M):
        loglevel, message, obj = m
        return {
            "level": loglevel.name,
            "message": message,
            "object": (obj.toJSON() if isinstance(obj, AbstractNetboxType) else {
                "type": "cosmo_string", "value": str(obj)
            }),
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
                "result": list(map(self._messageToJSON, self.info_queue)),
            }
        else:
            res = {
                "error": list(map(self._messageToJSON, self.error_queue)),
                "warning": list(map(self._messageToJSON, self.warning_queue)),
            }
        print(json.dumps(res))

    def exceptionHook(self, exception: type[BaseException], value: BaseException, traceback):
        if isinstance(exception, AbstractRecoverableError):
            self.warn(str(value), None)
        else:
            self.error(str(value), None)


class HumanReadableLoggingStrategy(AbstractLoggingStrategy):
    @staticmethod
    def formatObject(obj: O):
        return f" on {str(obj)}: " if obj else " "

    def info(self, message: str, on: O):
        print(f"{InfoLogLevel()}{self.formatObject(on)}{message}")

    def warn(self, message: str, on: O):
        print(f"{WarningLogLevel()}{self.formatObject(on)}{message}")

    def error(self, message: str, on: O):
        print(f"{ErrorLogLevel()}{self.formatObject(on)}{message}")

    def flush(self):
        pass

    def exceptionHook(self, exception: type[BaseException], value: BaseException, traceback):
        sys.__excepthook__(exception, value, traceback)


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

    def processHandledException(self, exception: BaseException): # for try/catch blocks to use
        self.exceptionHook(type(exception), exception, None, recovered=True)

    def exceptionHook(self, exception: type[BaseException], value: BaseException, traceback, recovered=False):
        self.strategy.exceptionHook(exception, value, traceback)
        if not recovered:
            # not recoverable because uncaught (we've been called from sys.excepthook,
            # since recovered is False by default). we're stopping the interpreter NOW.
            self.flush()


def info(message: str, on: O = None) -> None:
    logger.info(message, on)

def warn(message: str, on: O) -> None:
    logger.warn(message, on)

def error(message: str, on:O) -> None:
    logger.error(message, on)

logger = CosmoLogger().setLoggingStrategy(HumanReadableLoggingStrategy())
