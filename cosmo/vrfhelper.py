from abc import ABCMeta, abstractmethod


class IAsnDataHandler(metaclass=ABCMeta):
    @abstractmethod
    def getASN(self) -> int:
        pass


class TVRFHelpers(IAsnDataHandler, metaclass=ABCMeta):
    ASN2B_MAX = 65535 # https://datatracker.ietf.org/doc/rfc1930/

    def assembleRT(self, rt_id: int) -> str:
        asn = str(self.getASN()) if self.getASN() <= self.ASN2B_MAX else f"{self.getASN()}L"
        return f"target:{asn}:{str(rt_id)}"
