import abc


class AbstractNoopNetboxTypesVisitor(abc.ABC):
    def accept(self, o):
        # use raise NotImplementedError(f"unsupported type {o}")
        # when you're adding new types and you want to check your
        # visitor gets everything
        return
