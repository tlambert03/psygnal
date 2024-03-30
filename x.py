from psygnal import Signal


class T:
    """Doc."""

    sig = Signal(int, str)


t = T()


@t.sig.connect
def on_sig(a: int, b: int):
    """doc."""
    pass
