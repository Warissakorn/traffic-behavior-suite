import os
import sys
import tempfile
from pathlib import Path


def main(smoke=False):
    if smoke:
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont
    from .main_window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Traffic Behavior Suite")
    font = QFont()
    font.setFamilies(["Tahoma","Leelawadee UI","Noto Sans Thai","Segoe UI","sans-serif"])
    font.setPointSize(10)
    app.setFont(font)
    app.setStyle("Fusion")
    app.setStyleSheet("QWidget{font-size:13px;} QMainWindow{background:#f1f5fa;} QPushButton{padding:9px 14px;} QListWidget{background:#e6edf7;} QLineEdit,QPlainTextEdit,QTableWidget{background:white;} QProgressBar{min-height:22px;}")
    window = MainWindow()
    window.show()
    if not smoke:
        code = app.exec()
        for service in [window.preview_tasks,window.result_tasks,window.export_tasks]:
            service.stop()
        import shiboken6
        shiboken6.delete(window)
        return code
    temporary = tempfile.TemporaryDirectory(prefix="tbs-gui-smoke-")
    window.output_path.setText(str(Path(temporary.name)/"output"))
    state = {"status": None}
    def finished(status,message):
        state["status"] = status
        QTimer.singleShot(200,app.quit)
    window.job.finished.connect(finished)
    QTimer.singleShot(0,window.start_demo)
    def timeout():
        state["status"] = "timeout"
        window.job.force_stop()
        QTimer.singleShot(300,app.quit)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(timeout)
    timer.start(60000)
    app.exec()
    timer.stop()
    for service in [window.preview_tasks,window.result_tasks,window.export_tasks]:
        service.stop()
    window.dirty = False
    window.close()
    # Dispose scenes/pixmaps and stopped QThreads while QApplication still exists.
    # Keeping window↔signal closure cycles until interpreter shutdown can destroy
    # Qt resources after the application on some platforms.
    import shiboken6
    shiboken6.delete(window)
    temporary.cleanup()
    print(f"GUI worker smoke: {state['status']}")
    return 0 if state["status"]=="completed" else 2
