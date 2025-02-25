import warnings
from abc import ABC, abstractmethod
from functools import singledispatchmethod

from cosmo.abstractroutervisitor import AbstractRouterExporterVisitor
from cosmo.types import L2VPNType, InterfaceType, VLANType


class RouterL2VPNValidatorVisitor(AbstractRouterExporterVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    def isCompliantWANL2VPN(self, o: L2VPNType) -> bool:
        terminations = o.getTerminations()
        if o.getType().lower() == "vpws" and len(terminations) != self._vpws_authorized_terminations_n:
            warnings.warn(
                "VPWS circuits are only allowed to have two terminations. "
                f"{o.getName()} has {len(terminations)} terminations, ignoring..."
            )
            return False
        if any([not isinstance(t, (InterfaceType, VLANType)) for t in terminations]):
            warnings.warn(f"Found unsupported L2VPN termination in {o.getName()}, ignoring...")
            return False
        if o.getType().lower() == "vpws" and any([not isinstance(t, InterfaceType) for t in terminations]):
            return False
        return True

    @accept.register
    def _(self, o: L2VPNType):
        if not o.getName().startswith("WAN") and self.isCompliantWANL2VPN(o):
            return
