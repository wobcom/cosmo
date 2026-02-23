import json
import sys
from abc import abstractmethod, ABCMeta
from typing import Self

from termcolor import colored

from cosmo.common import AbstractRecoverableError, JsonOutputType
from cosmo.netbox_types import AbstractNetboxType


class AbstractLogLevel(metaclass=ABCMeta):
    name: str = "abstract_log_level"

    def __str__(self):
        return self.name.upper()


class DebugLogLevel(AbstractLogLevel):
    name = "debug"


class InfoLogLevel(AbstractLogLevel):
    name = "info"


class WarningLogLevel(AbstractLogLevel):
    name = "warning"


class ErrorLogLevel(AbstractLogLevel):
    name = "error"


O = object | AbstractNetboxType | None  # object-being-logged-on type
M = tuple[AbstractLogLevel, str, O]  # message type


class AbstractLoggingStrategy(metaclass=ABCMeta):
    @abstractmethod
    def flush(self):  # this is for async and sync logging
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
    def debug(self, message: str, on: O):
        pass

    @abstractmethod
    def exceptionHook(
        self, exception: type[BaseException], value: BaseException, traceback
    ):
        pass


class JsonLoggingStrategy(AbstractLoggingStrategy):
    info_queue: list[M] = []
    warning_queue: list[M] = []
    error_queue: list[M] = []

    @staticmethod
    def _messageToJSON(m: M):
        log_level, message, obj = m
        return {
            "level": log_level.name,
            "message": message,
            "object": (
                obj.getMetaInfo().toJSON()
                if isinstance(obj, AbstractNetboxType)
                else {"type": type(obj).__name__, "value": str(obj)}
            ),
        }

    def info(self, message: str, on: O):
        self.info_queue.append((InfoLogLevel(), message, on))

    def warn(self, message: str, on: O):
        self.warning_queue.append((WarningLogLevel(), message, on))

    def error(self, message: str, on: O):
        self.error_queue.append((ErrorLogLevel(), message, on))

    def debug(self, message: str, on: O):
        self.error_queue.append((DebugLogLevel(), message, on))

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

    def exceptionHook(
        self, exception: type[BaseException], value: BaseException, traceback
    ):
        if isinstance(exception, AbstractRecoverableError):
            self.warn(str(value), None)
        else:
            self.error(str(value), None)


class HumanReadableLoggingStrategy(AbstractLoggingStrategy):
    def __init__(self, *args, show_debug: bool, netbox_instance_url: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.nb_instance_url = netbox_instance_url
        self.show_debug = show_debug

    def formatMessage(self, m: M) -> str:
        log_level, message, obj = m
        match log_level:
            case DebugLogLevel():
                color = "magenta"
            case InfoLogLevel():
                color = "blue"
            case WarningLogLevel():
                color = "yellow"
            case ErrorLogLevel():
                color = "red"
            case _:
                color = "white"

        # Type Ignore is fixed with termcolor v3.
        log_level_colored = colored(log_level, color)  # type: ignore
        default_log = f"[{log_level_colored}] {message}"
        match obj:
            case AbstractNetboxType():
                meta_info = obj.getMetaInfo()
                full_url = meta_info.getFullObjectURL(self.nb_instance_url)
                return (
                    f"[{log_level_colored}]"
                    f" [{meta_info.device_display_name.lower()}]"
                    f" [{meta_info.display_name}] "
                    f"{message}\n" + colored(f"🌐 {full_url}", "light_blue")
                )
            case None:
                return default_log
            case str() | object():
                return f"[{log_level_colored}] [{obj}] {message}"
            case _:
                return default_log

    def info(self, message: str, on: O):
        print(self.formatMessage((InfoLogLevel(), message, on)))

    def warn(self, message: str, on: O):
        print(self.formatMessage((WarningLogLevel(), message, on)))

    def error(self, message: str, on: O):
        print(self.formatMessage((ErrorLogLevel(), message, on)))

    def debug(self, message: str, on: O):
        if self.show_debug:
            print(self.formatMessage((DebugLogLevel(), message, on)))

    def flush(self):
        pass

    def exceptionHook(
        self, exception: type[BaseException], value: BaseException, traceback
    ):
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

    def debug(self, message: str, on: O):
        self.strategy.debug(message, on)

    def processHandledException(
        self, exception: BaseException
    ):  # for try/catch blocks to use
        self.exceptionHook(type(exception), exception, None, recovered=True)

    def exceptionHook(
        self,
        exception: type[BaseException],
        value: BaseException,
        traceback,
        recovered=False,
    ):
        self.strategy.exceptionHook(exception, value, traceback)
        if not recovered:
            # not recoverable because uncaught (we've been called from sys.excepthook,
            # since recovered is False by default). we're stopping the interpreter NOW.
            self.flush()


def info(message: str, on: O = None) -> None:
    logger.info(message, on)


def warn(message: str, on: O) -> None:
    logger.warn(message, on)


def error(message: str, on: O) -> None:
    logger.error(message, on)


def debug(message: str, on: O = None) -> None:
    logger.debug(message, on)


logger = CosmoLogger()
