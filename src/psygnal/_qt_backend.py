"""Qt backend for psygnal SignalGroups.

Provides a QObject-backed implementation of the SignalGroup API, allowing
users to define signals once as a SignalGroup and get automatic Qt fallback.
"""

from __future__ import annotations

import warnings
from functools import cache
from inspect import Parameter, Signature
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from psygnal._group import SignalGroup

if TYPE_CHECKING:
    from collections.abc import Callable, Container, Iterator
    from contextlib import AbstractContextManager

    from psygnal._signal import ReducerFunc

_QT_NATIVE_TYPES = frozenset({int, float, str, bool, bytes})


def _detect_qt_backend() -> str:
    """Return 'qt' if qtpy is available and a QApplication exists, else 'psygnal'."""
    try:
        from qtpy.QtWidgets import QApplication
    except (ImportError, RuntimeError):
        return "psygnal"
    if QApplication.instance() is not None:
        return "qt"
    return "psygnal"


def _psygnal_type_to_qt(annotation: Any) -> type:
    """Map a psygnal Signal parameter annotation to a Qt-compatible type."""
    if annotation is Parameter.empty:
        return object
    if annotation in _QT_NATIVE_TYPES:
        return annotation
    return object


@cache
def _create_qobject_class(signal_group_cls: type) -> type:
    """Create a QObject subclass with QtCore.Signal attrs matching the group."""
    from qtpy import QtCore

    attrs: dict[str, Any] = {}
    for name, sig in signal_group_cls._psygnal_signals.items():
        qt_types = tuple(
            _psygnal_type_to_qt(p.annotation) for p in sig.signature.parameters.values()
        )
        attrs[name] = QtCore.Signal(*qt_types)

    cls_name = f"_Qt{signal_group_cls.__name__}"
    return type(cls_name, (QtCore.QObject,), attrs)


class QtSignalProxy:
    """Wraps a Qt bound signal to provide a SignalInstance-like API."""

    def __init__(
        self,
        qt_signal: Any,
        name: str,
        signature: Signature,
    ) -> None:
        self._qt_signal = qt_signal
        self._name = name
        self._signature = signature
        self._is_blocked = False
        self._is_paused = False
        self._args_queue: list[tuple[Any, ...]] = []
        # maps id(slot) -> (slot, wrapper) for disconnect-by-ref
        self._slot_map: dict[int, tuple[Callable, Callable]] = {}
        self._relay_fn: Callable | None = None

    @property
    def name(self) -> str:
        """Name of this signal."""
        return self._name

    @property
    def signature(self) -> Signature:
        """Signature supported by this signal."""
        return self._signature

    def connect(self, slot: Callable, **kwargs: Any) -> Callable:
        """Connect a slot to this signal."""
        if kwargs.get("priority", 0) != 0:
            warnings.warn(
                "priority is not supported by QtSignalProxy and will be ignored",
                UserWarning,
                stacklevel=2,
            )

        def _wrapper(*args: Any) -> None:
            if self._is_blocked:
                return
            if self._is_paused:
                self._args_queue.append(args)
                return
            slot(*args)

        self._slot_map[id(slot)] = (slot, _wrapper)
        self._qt_signal.connect(_wrapper)
        return slot

    def disconnect(self, slot: Callable | None = None, missing_ok: bool = True) -> None:
        """Disconnect a slot from this signal."""
        if slot is None:
            for _orig, wrapper in list(self._slot_map.values()):
                try:
                    self._qt_signal.disconnect(wrapper)
                except (RuntimeError, TypeError):
                    pass
            self._slot_map.clear()
            return

        key = id(slot)
        if key in self._slot_map:
            _orig, wrapper = self._slot_map.pop(key)
            try:
                self._qt_signal.disconnect(wrapper)
            except (RuntimeError, TypeError):
                if not missing_ok:
                    raise
        elif not missing_ok:
            raise ValueError(f"slot is not connected: {slot}")

    def emit(self, *args: Any, **kwargs: Any) -> None:
        """Emit this signal."""
        if self._is_blocked:
            return
        if self._is_paused:
            self._args_queue.append(args)
            return
        self._qt_signal.emit(*args)

    def block(self, exclude: Container[str | Any] = ()) -> None:
        """Block this signal from emitting."""
        self._is_blocked = True

    def unblock(self) -> None:
        """Unblock this signal."""
        self._is_blocked = False

    def blocked(self) -> AbstractContextManager[None]:
        """Context manager to temporarily block this signal."""
        return _QtProxyBlocker(self)

    def pause(self) -> None:
        """Pause this signal, collecting emissions for later."""
        self._is_paused = True

    def resume(self, reducer: ReducerFunc | None = None, initial: Any = None) -> None:
        """Resume this signal, re-emitting collected args."""
        self._is_paused = False
        if not self._args_queue:
            return
        if reducer is not None:
            import inspect
            from functools import reduce as functools_reduce

            if len(inspect.signature(reducer).parameters) == 1:
                args = reducer(self._args_queue)
            else:
                if initial is None:
                    args = functools_reduce(reducer, self._args_queue)
                else:
                    args = functools_reduce(reducer, self._args_queue, initial)
            self._qt_signal.emit(*args)
        else:
            for args in self._args_queue:
                self._qt_signal.emit(*args)
        self._args_queue.clear()

    def paused(
        self,
        reducer: ReducerFunc | None = None,
        initial: Any = None,
    ) -> AbstractContextManager[None]:
        """Context manager to temporarily pause this signal."""
        return _QtProxyPauser(self, reducer, initial)

    def connect_setattr(self, *args: Any, **kwargs: Any) -> None:
        """Not supported for Qt backend."""
        raise NotImplementedError("connect_setattr is not supported by QtSignalProxy")

    def connect_setitem(self, *args: Any, **kwargs: Any) -> None:
        """Not supported for Qt backend."""
        raise NotImplementedError("connect_setitem is not supported by QtSignalProxy")


class _QtProxyBlocker:
    """Context manager to block/unblock a QtSignalProxy."""

    def __init__(self, proxy: QtSignalProxy) -> None:
        self._proxy = proxy
        self._was_blocked = proxy._is_blocked

    def __enter__(self) -> None:
        self._proxy.block()

    def __exit__(self, *args: Any) -> None:
        if not self._was_blocked:
            self._proxy.unblock()


class _QtProxyPauser:
    """Context manager to pause/resume a QtSignalProxy."""

    def __init__(
        self,
        proxy: QtSignalProxy,
        reducer: ReducerFunc | None,
        initial: Any,
    ) -> None:
        self._proxy = proxy
        self._was_paused = proxy._is_paused
        self._reducer = reducer
        self._initial = initial

    def __enter__(self) -> None:
        self._proxy.pause()

    def __exit__(self, *args: Any) -> None:
        if not self._was_paused:
            self._proxy.resume(self._reducer, self._initial)


class _QSignalGroupRelay:
    """Relay that connects a single callback to all Qt signals in a group."""

    def __init__(self, group: QSignalGroup) -> None:
        self._group = group
        self._slots: list[Callable] = []

    def connect(self, slot: Callable, **kwargs: Any) -> Callable:
        """Connect a slot to be called on any signal emission."""
        self._slots.append(slot)
        if len(self._slots) == 1:
            self._connect_all()
        return slot

    def disconnect(self, slot: Callable | None = None, missing_ok: bool = True) -> None:
        """Disconnect a slot from the relay."""
        if slot is None:
            self._slots.clear()
            self._disconnect_all()
            return
        try:
            self._slots.remove(slot)
        except ValueError:
            if not missing_ok:
                raise ValueError(f"slot is not connected: {slot}") from None
        if not self._slots:
            self._disconnect_all()

    def _connect_all(self) -> None:
        from psygnal._group import EmissionInfo

        for _name, proxy in self._group._proxies.items():

            def _make_relay(p: QtSignalProxy) -> Callable:
                def _relay(*args: Any) -> None:
                    if p._is_blocked:
                        return
                    info = EmissionInfo(signal=p, args=args)
                    for s in self._slots:
                        s(info)

                return _relay

            relay_fn = _make_relay(proxy)
            proxy._qt_signal.connect(relay_fn)
            proxy._relay_fn = relay_fn

    def _disconnect_all(self) -> None:
        for proxy in self._group._proxies.values():
            if proxy._relay_fn is not None:
                try:
                    proxy._qt_signal.disconnect(proxy._relay_fn)
                except (RuntimeError, TypeError):
                    pass
                proxy._relay_fn = None

    @property
    def name(self) -> str:
        """Name of the relay."""
        return "all"

    def block(self, exclude: Container[str | Any] = ()) -> None:
        """Block all signals."""
        self._group.block(exclude=exclude)

    def unblock(self) -> None:
        """Unblock all signals."""
        self._group.unblock()

    def blocked(
        self, exclude: Container[str | Any] = ()
    ) -> AbstractContextManager[None]:
        """Context manager to block all signals."""
        return self._group.blocked(exclude=exclude)

    def pause(self) -> None:
        """Pause all signals."""
        self._group.pause()

    def resume(self, reducer: ReducerFunc | None = None, initial: Any = None) -> None:
        """Resume all signals."""
        self._group.resume(reducer=reducer, initial=initial)

    def paused(
        self, reducer: ReducerFunc | None = None, initial: Any = None
    ) -> AbstractContextManager[None]:
        """Context manager to pause all signals."""
        return self._group.paused(reducer=reducer, initial=initial)


class QSignalGroup(SignalGroup):
    """QObject-backed SignalGroup.

    Wraps a QObject instance, exposing signals as QtSignalProxy objects.
    Implements the SignalGroup container API so it can be used as a drop-in
    replacement for a psygnal SignalGroup.
    """

    # class-level: set by _create_qsignal_group_class
    _qobject_class: type | None = None
    _signal_definitions: dict[str, Any] | None = None

    def __init__(self, instance: Any = None) -> None:
        if self._qobject_class is None:
            raise TypeError(
                "Cannot instantiate QSignalGroup directly. "
                "Use SignalGroup.for_backend('qt') instead."
            )
        # NOTE: intentionally skip SignalGroup.__init__
        self._qobject = self._qobject_class()
        self._instance = instance

        self._proxies: dict[str, QtSignalProxy] = {}
        for name, sig in self._signal_definitions.items():  # type: ignore[union-attr]
            qt_bound_signal = getattr(self._qobject, name)
            proxy_sig = sig.signature
            self._proxies[name] = QtSignalProxy(qt_bound_signal, name, proxy_sig)

        self._psygnal_relay = _QSignalGroupRelay(self)
        self._sig_was_blocked: dict[str, bool] = {}

    @property
    def instance(self) -> Any:
        """Object that owns this QSignalGroup."""
        return self._instance

    @property
    def all(self) -> _QSignalGroupRelay:
        """Relay that can connect to all signals in this group."""
        return self._psygnal_relay

    @property
    def signals(self) -> MappingProxyType[str, QtSignalProxy]:
        """A mapping of signal names to QtSignalProxy instances."""
        return MappingProxyType(self._proxies)

    def __iter__(self) -> Iterator[str]:
        """Yield signal names."""
        return iter(self._proxies)

    def __len__(self) -> int:
        """Return number of signals."""
        return len(self._proxies)

    def __contains__(self, item: str) -> bool:
        """Return True if the group contains a signal with the given name."""
        return item in self._proxies

    def __getitem__(self, item: str) -> QtSignalProxy:
        """Get a signal proxy by name."""
        return self._proxies[item]

    def __getattr__(self, name: str) -> Any:
        """Get a signal proxy by attribute access."""
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._proxies[name]
        except KeyError:
            raise AttributeError(
                f"'{type(self).__name__}' has no signal named '{name}'"
            ) from None

    def __repr__(self) -> str:
        """Return repr(self)."""
        name = type(self).__name__
        return f"<QSignalGroup {name!r} with {len(self)} signals>"

    def connect(self, slot: Callable | None = None, **kwargs: Any) -> Any:
        """Connect a slot to be called on any signal emission (via relay)."""
        if slot is None:

            def _decorator(s: Callable) -> Callable:
                return self._psygnal_relay.connect(s, **kwargs)

            return _decorator
        return self._psygnal_relay.connect(slot, **kwargs)

    def disconnect(self, slot: Callable | None = None, missing_ok: bool = True) -> None:
        """Disconnect slot from all signals."""
        for proxy in self._proxies.values():
            proxy.disconnect(slot, missing_ok=True)
        self._psygnal_relay.disconnect(slot, missing_ok=missing_ok)

    def block(self, exclude: Container[str | Any] = ()) -> None:
        """Block all signals from emitting."""
        for name, proxy in self._proxies.items():
            if name in exclude or proxy in exclude:
                continue
            self._sig_was_blocked[name] = proxy._is_blocked
            proxy.block()

    def unblock(self) -> None:
        """Unblock all signals."""
        for name, proxy in self._proxies.items():
            if not self._sig_was_blocked.pop(name, False):
                proxy.unblock()

    def blocked(
        self, exclude: Container[str | Any] = ()
    ) -> AbstractContextManager[None]:
        """Context manager to block all signals."""
        return _QSignalGroupBlocker(self, exclude=exclude)

    def pause(self) -> None:
        """Pause all signals."""
        for proxy in self._proxies.values():
            proxy.pause()

    def resume(self, reducer: ReducerFunc | None = None, initial: Any = None) -> None:
        """Resume all signals."""
        for proxy in self._proxies.values():
            proxy.resume(reducer=reducer, initial=initial)

    def paused(
        self, reducer: ReducerFunc | None = None, initial: Any = None
    ) -> AbstractContextManager[None]:
        """Context manager to pause all signals."""
        return _QSignalGroupPauser(self, reducer, initial)


class _QSignalGroupBlocker:
    """Context manager to block/unblock a QSignalGroup."""

    def __init__(self, group: QSignalGroup, exclude: Container[str | Any] = ()) -> None:
        self._group = group
        self._exclude = exclude

    def __enter__(self) -> None:
        self._group.block(exclude=self._exclude)

    def __exit__(self, *args: Any) -> None:
        self._group.unblock()


class _QSignalGroupPauser:
    """Context manager to pause/resume a QSignalGroup."""

    def __init__(
        self,
        group: QSignalGroup,
        reducer: ReducerFunc | None,
        initial: Any,
    ) -> None:
        self._group = group
        self._reducer = reducer
        self._initial = initial

    def __enter__(self) -> None:
        self._group.pause()

    def __exit__(self, *args: Any) -> None:
        self._group.resume(self._reducer, self._initial)


@cache
def _create_qsignal_group_class(signal_group_cls: type) -> type[QSignalGroup]:
    """Create a QSignalGroup subclass for a given SignalGroup subclass."""
    qobj_cls = _create_qobject_class(signal_group_cls)
    sig_defs = signal_group_cls._psygnal_signals

    cls_name = f"Qt{signal_group_cls.__name__}"
    # Use type() directly to create the class. __init_subclass__ from
    # SignalGroup will fire but that's fine — it will just find no Signal
    # descriptors on this class.
    new_cls = type(
        cls_name,
        (QSignalGroup,),
        {
            "_qobject_class": qobj_cls,
            "_signal_definitions": sig_defs,
        },
    )
    return new_cls
