import abc
from abc import abstractmethod
from enum import IntEnum, auto

from cosmo.types import AbstractNetboxType


class LogLevel(IntEnum):
    INFO = 0
    WARN = auto()
    ERROR = auto()


O = object | AbstractNetboxType | None # object-being-logged-on type
M = tuple[LogLevel, str, O] # message type

class AbstractLoggingStrategy(metaclass=abc.ABCMeta):
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
    queue: list[M] = [] # list of log messages

    def info(self, message: str, on: O):
        self.queue.append((LogLevel.INFO, message, on))

    def warn(self, message: str, on: O):
        self.queue.append((LogLevel.WARN, message, on))

    def error(self, message: str, on: O):
        self.queue.append((LogLevel.ERROR, message, on))

    def flush(self):
        pass # TODO

class HumanReadableLoggingStrategy(AbstractLoggingStrategy):
    def info(self, message: str, on: O):
        print('[INFO] ' + message)

    def warn(self, message: str, on: O):
        print('[WARNING] ' + message)

    def error(self, message: str, on: O):
        print('[ERROR] ' + message)

    def flush(self):
        pass


class CosmoLogger:
    strategy: AbstractLoggingStrategy

    def setLoggingStrategy(self, strategy: AbstractLoggingStrategy):
        self.strategy = strategy

    def flush(self):
        self.strategy.flush()

    def getLoggingStrategy(self):
        return self.strategy

    def info(self, message: str, on: O):
        self.strategy.info(message, on)

    def warn(self, message: str, on: O):
        self.strategy.warn(message, on)

    def error(self, message: str, on: O):
        self.strategy.error(message, on)


logger = CosmoLogger()


def info(string: str) -> None:
    logger.info(string, None)
