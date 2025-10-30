from multimethod import multimethod as singledispatchmethod

from cosmo.autodesc import (
    AbstractComposableAutoDescription,
    PhysicalInterfaceContainerDescription,
)
from cosmo.common import head
from cosmo.netbox_types import InterfaceType
from cosmo.visitors import AbstractNoopNetboxTypesVisitor


class MutatingAutoDescVisitor(AbstractNoopNetboxTypesVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: InterfaceType):
        auto_description_classes: list[type[AbstractComposableAutoDescription]] = (
            AbstractComposableAutoDescription.__subclasses__()
        )
        auto_descriptions: list[AbstractComposableAutoDescription] = []
        for c in auto_description_classes:
            auto_descriptions.append(c(o))
        auto_descriptions.sort(reverse=True)
        # TODO check if strictly decreasing, if not -> conflict should raise error
        auto_description = head(auto_descriptions)
        if (
            not auto_description.getPriority()
            > AbstractComposableAutoDescription.NOT_MATCHED
        ):
            return
        if o.isSubInterface() and auto_description:
            physical = o.getPhysicalInterfaceByFilter()
            physical.setAutoDescription(
                PhysicalInterfaceContainerDescription(
                    interface=physical,
                    description=physical.getAutoDescription(),
                ).add(auto_description)
            )
        o.setAutoDescription(auto_description)
