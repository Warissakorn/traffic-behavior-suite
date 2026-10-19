"""Wheel events scroll forms but never edit their values, even with focus."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
import numpy as np
import shiboken6
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QScrollArea, QWidget, QVBoxLayout, QLabel,
                              QSpinBox, QDoubleSpinBox, QComboBox, QSlider)
from tbs.gui.wheel_guard import install_wheel_guard
from tbs.gui.preview import Canvas


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    install_wheel_guard()
    return app


def wheel(widget, delta=-120):
    position = widget.rect().center()
    event = QWheelEvent(QPointF(position), QPointF(widget.mapToGlobal(position)),
                        QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


@pytest.mark.parametrize('kind', ['integer', 'decimal', 'combo', 'editable_combo', 'slider', 'spin_editor', 'combo_editor'])
@pytest.mark.parametrize('focused', [False, True])
def test_wheel_preserves_value_and_scrolls_parent(app, kind, focused):
    scroll = QScrollArea()
    content = QWidget()
    layout = QVBoxLayout(content)
    if kind in {'integer', 'spin_editor'}:
        field = QSpinBox()
        field.setValue(50)
    elif kind == 'decimal':
        field = QDoubleSpinBox()
        field.setValue(50.5)
    elif kind == 'slider':
        field = QSlider(Qt.Orientation.Horizontal)
        field.setValue(50)
    else:
        field = QComboBox()
        field.addItems(['A', 'B', 'C', 'D'])
        field.setCurrentIndex(1)
        field.setEditable(kind in {'editable_combo', 'combo_editor'})
    layout.addWidget(field)
    for index in range(30):
        layout.addWidget(QLabel(f'Row {index}'))
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    scroll.resize(340, 240)
    scroll.show()
    if focused:
        field.setFocus()
    else:
        scroll.setFocus()
    app.processEvents()
    current = field.currentIndex if isinstance(field, QComboBox) else field.value
    before = current()
    receiver = field.lineEdit() if kind in {'spin_editor', 'combo_editor'} else field
    assert scroll.verticalScrollBar().value() == 0
    wheel(receiver)
    assert current() == before
    assert scroll.verticalScrollBar().value() > 0
    scroll.verticalScrollBar().setValue(0)
    QTest.keyClick(field, Qt.Key.Key_Down)
    assert current() != before  # Deliberate keyboard edits still work.
    shiboken6.delete(scroll)


def test_wheel_is_blocked_without_a_parent_scroll_area(app):
    field = QSpinBox()
    field.setValue(50)
    field.show()
    field.setFocus()
    wheel(field)
    assert field.value() == 50
    shiboken6.delete(field)


def test_combo_popup_can_scroll_without_committing_another_value(app):
    field = QComboBox()
    field.addItems([f'Item {index}' for index in range(60)])
    field.setMaxVisibleItems(5)
    field.show()
    field.showPopup()
    app.processEvents()
    before = field.currentIndex()
    wheel(field.view().viewport())
    assert field.currentIndex() == before
    assert field.view().verticalScrollBar().value() > 0
    field.hidePopup()
    shiboken6.delete(field)


def test_wheel_still_zooms_video_canvas(app):
    canvas = Canvas()
    canvas.resize(640, 400)
    canvas.show()
    canvas.set_image(np.zeros((120, 320, 3), np.uint8))
    app.processEvents()
    before = canvas.transform().m11()
    wheel(canvas.viewport(), 120)
    assert canvas.transform().m11() > before
    shiboken6.delete(canvas)
