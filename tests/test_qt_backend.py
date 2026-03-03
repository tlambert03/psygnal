"""Tests for the Qt backend system."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from psygnal import Signal, SignalGroup

pytest.importorskip("qtpy")


class MySignals(SignalGroup):
    changed = Signal(int)
    toggled = Signal(bool)
    updated = Signal(str, int)
    no_args = Signal()


# ---------------------------------------------------------------------------
# for_backend routing
# ---------------------------------------------------------------------------


def test_for_backend_psygnal():
    cls = MySignals.for_backend("psygnal")
    assert cls is MySignals


def test_for_backend_qt(qapp):
    cls = MySignals.for_backend("qt")
    assert cls is not MySignals
    assert issubclass(cls, SignalGroup)  # virtual subclass


def test_for_backend_auto_no_qapp():
    """Without a QApplication, auto should return psygnal."""
    with patch("psygnal._qt_backend._detect_qt_backend", return_value="psygnal"):
        cls = MySignals.for_backend("auto")
    assert cls is MySignals


def test_for_backend_auto_with_qapp(qapp):
    cls = MySignals.for_backend("auto")
    # Should detect Qt
    assert cls is not MySignals


def test_for_backend_caching(qapp):
    cls1 = MySignals.for_backend("qt")
    cls2 = MySignals.for_backend("qt")
    assert cls1 is cls2


# ---------------------------------------------------------------------------
# QSignalGroup instantiation and container API
# ---------------------------------------------------------------------------


def test_qsignal_group_instantiation(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    assert len(group) == 4
    assert "changed" in group
    assert "toggled" in group
    assert "updated" in group
    assert "no_args" in group
    assert "nonexistent" not in group


def test_qsignal_group_iter(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    names = list(group)
    assert set(names) == {"changed", "toggled", "updated", "no_args"}


def test_qsignal_group_getitem(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    proxy = group["changed"]
    assert proxy.name == "changed"
    with pytest.raises(KeyError):
        group["nonexistent"]


def test_qsignal_group_getattr(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    proxy = group.changed
    assert proxy.name == "changed"
    with pytest.raises(AttributeError):
        group.nonexistent  # noqa: B018


def test_qsignal_group_isinstance(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    assert isinstance(group, SignalGroup)


def test_qsignal_group_signals_property(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    sigs = group.signals
    assert set(sigs.keys()) == {"changed", "toggled", "updated", "no_args"}


def test_qsignal_group_repr(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    r = repr(group)
    assert "QSignalGroup" in r
    assert "4 signals" in r


# ---------------------------------------------------------------------------
# QtSignalProxy connect / emit / disconnect
# ---------------------------------------------------------------------------


def test_proxy_connect_emit(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.changed.connect(mock)
    group.changed.emit(42)
    mock.assert_called_once_with(42)


def test_proxy_emit_multiple_args(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.updated.connect(mock)
    group.updated.emit("hello", 5)
    mock.assert_called_once_with("hello", 5)


def test_proxy_emit_no_args(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.no_args.connect(mock)
    group.no_args.emit()
    mock.assert_called_once_with()


def test_proxy_disconnect_specific(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.changed.connect(mock)
    group.changed.disconnect(mock)
    group.changed.emit(1)
    mock.assert_not_called()


def test_proxy_disconnect_all(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock1 = Mock()
    mock2 = Mock()
    group.changed.connect(mock1)
    group.changed.connect(mock2)
    group.changed.disconnect()
    group.changed.emit(1)
    mock1.assert_not_called()
    mock2.assert_not_called()


def test_proxy_disconnect_missing_ok(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    # Should not raise
    group.changed.disconnect(mock, missing_ok=True)
    # Should raise
    with pytest.raises(ValueError, match="not connected"):
        group.changed.disconnect(mock, missing_ok=False)


def test_proxy_multiple_slots(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock1 = Mock()
    mock2 = Mock()
    group.changed.connect(mock1)
    group.changed.connect(mock2)
    group.changed.emit(7)
    mock1.assert_called_once_with(7)
    mock2.assert_called_once_with(7)


def test_proxy_signature(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    sig = group.changed.signature
    params = list(sig.parameters.values())
    assert len(params) == 1
    assert params[0].annotation is int


# ---------------------------------------------------------------------------
# Block / unblock / blocked
# ---------------------------------------------------------------------------


def test_proxy_block_unblock(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.changed.connect(mock)

    group.changed.block()
    group.changed.emit(1)
    mock.assert_not_called()

    group.changed.unblock()
    group.changed.emit(2)
    mock.assert_called_once_with(2)


def test_proxy_blocked_context(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.changed.connect(mock)

    with group.changed.blocked():
        group.changed.emit(1)
    mock.assert_not_called()

    group.changed.emit(2)
    mock.assert_called_once_with(2)


def test_group_block_unblock(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock_changed = Mock()
    mock_toggled = Mock()
    group.changed.connect(mock_changed)
    group.toggled.connect(mock_toggled)

    group.block()
    group.changed.emit(1)
    group.toggled.emit(True)
    mock_changed.assert_not_called()
    mock_toggled.assert_not_called()

    group.unblock()
    group.changed.emit(2)
    group.toggled.emit(False)
    mock_changed.assert_called_once_with(2)
    mock_toggled.assert_called_once_with(False)


def test_group_block_with_exclude(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock_changed = Mock()
    mock_toggled = Mock()
    group.changed.connect(mock_changed)
    group.toggled.connect(mock_toggled)

    group.block(exclude=("changed",))
    group.changed.emit(1)
    group.toggled.emit(True)
    mock_changed.assert_called_once_with(1)
    mock_toggled.assert_not_called()

    group.unblock()


def test_group_blocked_context(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.changed.connect(mock)

    with group.blocked():
        group.changed.emit(1)
    mock.assert_not_called()

    group.changed.emit(2)
    mock.assert_called_once_with(2)


# ---------------------------------------------------------------------------
# Pause / resume / paused
# ---------------------------------------------------------------------------


def test_proxy_pause_resume(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.changed.connect(mock)

    group.changed.pause()
    group.changed.emit(1)
    group.changed.emit(2)
    mock.assert_not_called()

    group.changed.resume()
    assert mock.call_count == 2
    mock.assert_any_call(1)
    mock.assert_any_call(2)


def test_proxy_paused_context(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.changed.connect(mock)

    with group.changed.paused():
        group.changed.emit(10)
        group.changed.emit(20)
    assert mock.call_count == 2


def test_proxy_pause_resume_with_reducer(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.changed.connect(mock)

    group.changed.pause()
    group.changed.emit(1)
    group.changed.emit(2)
    group.changed.emit(3)
    # Reducer that sums the values
    group.changed.resume(reducer=lambda a, b: (a[0] + b[0],), initial=(0,))
    mock.assert_called_once_with(6)


def test_group_pause_resume(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.changed.connect(mock)

    group.pause()
    group.changed.emit(1)
    group.changed.emit(2)
    mock.assert_not_called()

    group.resume()
    assert mock.call_count == 2


def test_group_paused_context(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.changed.connect(mock)

    with group.paused():
        group.changed.emit(1)
        group.changed.emit(2)
    assert mock.call_count == 2


# ---------------------------------------------------------------------------
# .all relay
# ---------------------------------------------------------------------------


def test_relay_connect_emit(qapp):
    from psygnal._group import EmissionInfo

    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.all.connect(mock)

    group.changed.emit(42)
    assert mock.call_count == 1
    info = mock.call_args[0][0]
    assert isinstance(info, EmissionInfo)
    assert info.args == (42,)
    assert info.signal is group.changed


def test_relay_multiple_signals(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.all.connect(mock)

    group.changed.emit(1)
    group.toggled.emit(True)
    assert mock.call_count == 2


def test_relay_disconnect(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.all.connect(mock)
    group.all.disconnect(mock)

    group.changed.emit(1)
    mock.assert_not_called()


def test_relay_disconnect_all(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock1 = Mock()
    mock2 = Mock()
    group.all.connect(mock1)
    group.all.connect(mock2)
    group.all.disconnect()

    group.changed.emit(1)
    mock1.assert_not_called()
    mock2.assert_not_called()


# ---------------------------------------------------------------------------
# Group-level connect / disconnect
# ---------------------------------------------------------------------------


def test_group_connect_disconnect(qapp):
    from psygnal._group import EmissionInfo

    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.connect(mock)

    group.changed.emit(5)
    assert mock.call_count == 1
    info = mock.call_args[0][0]
    assert isinstance(info, EmissionInfo)

    group.disconnect(mock)
    group.changed.emit(6)
    assert mock.call_count == 1


def test_group_connect_decorator(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()

    @group.connect()
    def handler(info):
        mock(info)

    group.changed.emit(1)
    mock.assert_called_once()


# ---------------------------------------------------------------------------
# connect_setattr / connect_setitem raise NotImplementedError
# ---------------------------------------------------------------------------


def test_proxy_connect_setattr_raises(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    with pytest.raises(NotImplementedError):
        group.changed.connect_setattr()


def test_proxy_connect_setitem_raises(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()
    with pytest.raises(NotImplementedError):
        group.changed.connect_setitem()


# ---------------------------------------------------------------------------
# SignalTester works with Qt backend
# ---------------------------------------------------------------------------


def test_signal_tester_with_qt_proxy(qapp):
    from psygnal.testing import SignalTester

    cls = MySignals.for_backend("qt")
    group = cls()
    tester = SignalTester(group.changed)

    with tester:
        group.changed.emit(42)

    tester.assert_emitted()
    tester.assert_emitted_once()
    tester.assert_emitted_once_with(42)


def test_signal_tester_with_qt_group(qapp):
    from psygnal.testing import SignalTester

    cls = MySignals.for_backend("qt")
    group = cls()
    tester = SignalTester(group)

    with tester:
        group.changed.emit(99)

    tester.assert_emitted()


# ---------------------------------------------------------------------------
# _detect_qt_backend
# ---------------------------------------------------------------------------


def test_detect_qt_backend_no_qt():
    with patch.dict("sys.modules", {"qtpy": None, "qtpy.QtWidgets": None}):
        from psygnal._qt_backend import _detect_qt_backend

        # Force re-evaluation by calling directly; the patched import will fail
        result = _detect_qt_backend()
        assert result == "psygnal"


def test_detect_qt_backend_with_qapp(qapp):
    from psygnal._qt_backend import _detect_qt_backend

    result = _detect_qt_backend()
    assert result == "qt"


# ---------------------------------------------------------------------------
# priority warning
# ---------------------------------------------------------------------------


def test_priority_warning(qapp):
    cls = MySignals.for_backend("qt")
    group = cls()

    with pytest.warns(UserWarning, match="priority"):
        group.changed.connect(lambda x: None, priority=1)


# ---------------------------------------------------------------------------
# emit blocked at proxy level during emit
# ---------------------------------------------------------------------------


def test_emit_blocked_at_emit_time(qapp):
    """Ensure block/unblock in wrapper prevents delivery to slot."""
    cls = MySignals.for_backend("qt")
    group = cls()
    mock = Mock()
    group.changed.connect(mock)

    group.changed.block()
    # Emit goes to Qt but wrapper intercepts
    group.changed.emit(1)
    mock.assert_not_called()

    group.changed.unblock()
    group.changed.emit(2)
    mock.assert_called_once_with(2)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_cannot_instantiate_base_qsignal_group(qapp):
    from psygnal._qt_backend import QSignalGroup

    with pytest.raises(TypeError, match="Cannot instantiate"):
        QSignalGroup()


def test_instance_property(qapp):
    cls = MySignals.for_backend("qt")
    sentinel = object()
    group = cls(instance=sentinel)
    assert group.instance is sentinel
