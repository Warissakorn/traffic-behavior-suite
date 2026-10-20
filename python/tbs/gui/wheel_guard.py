"""Keep wheel scrolling from changing form values, including focused fields."""
from PySide6.QtCore import QObject, QEvent, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (QApplication, QWidget, QAbstractSpinBox, QComboBox,
                              QSlider, QDial, QLineEdit, QAbstractScrollArea)


class FormWheelGuard(QObject):
    def eventFilter(self, receiver, event):
        if event.type() != QEvent.Type.Wheel or not isinstance(receiver, QWidget):
            return False
        controls = (QAbstractSpinBox, QComboBox, QSlider, QDial)
        control = receiver
        if isinstance(receiver, QLineEdit):
            # Editable combos and spin boxes deliver some events to their editor.
            while control is not None and not isinstance(control, controls):
                control = control.parentWidget()
        if not isinstance(control, controls):
            return False
        parent = control.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                viewport = parent.viewport()
                forwarded = QWheelEvent(
                    QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                    event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                    event.buttons(), event.modifiers(), event.phase(), event.inverted(),
                    event.source(), event.pointingDevice())
                QApplication.sendEvent(viewport, forwarded)
                break
            parent = parent.parentWidget()
        event.accept()
        return True


def install_wheel_guard():
    app = QApplication.instance()
    if app is not None and not hasattr(app, '_tbs_form_wheel_guard'):
        guard = FormWheelGuard(app)
        app.installEventFilter(guard)
        app._tbs_form_wheel_guard = guard
