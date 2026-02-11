import multiprocessing


def get_client_mp_context(method=None):
    # this will set and return the global context, by default
    # since method is None. the reason why we use this
    # boilerplate is to have an anchor point for
    # monkeypatching the multiprocessing context
    # during tests.
    return multiprocessing.get_context(method=method)
