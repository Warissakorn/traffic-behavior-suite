"""A quiet desktop palette with compact controls and clear primary actions."""
STYLE = """
QMainWindow { background: #f3f5f8; }
QWidget { color: #253247; }
QLabel#brand { font-size: 18px; font-weight: 600; }
QLabel#sectionTitle { font-size: 17px; font-weight: 600; }
QLabel#muted { color: #64748b; }
QLabel#error { color: #b42318; }
QPushButton { background: #ffffff; border: 1px solid #d7dee8; border-radius: 5px; padding: 6px 10px; }
QPushButton:hover { background: #edf3fc; border-color: #a8bdd9; }
QPushButton:pressed { background: #dbe7f6; }
QPushButton:disabled { color: #98a2b3; background: #f2f4f7; }
QPushButton#primary { color: #ffffff; background: #2563eb; border-color: #2563eb; font-weight: 600; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:disabled { color: #e3e9f5; background: #93b4ef; border-color: #93b4ef; }
QListWidget#navigation { background: #edf1f7; border: 0; border-radius: 6px; padding: 5px; }
QListWidget#navigation::item { padding: 10px 8px; margin-bottom: 3px; border-radius: 5px; }
QListWidget#navigation::item:selected { color: #1d4ed8; background: #dce8fb; font-weight: 600; }
QLineEdit, QPlainTextEdit, QTableWidget, QComboBox, QDoubleSpinBox { background: #ffffff; border: 1px solid #d7dee8; border-radius: 4px; }
QLineEdit, QComboBox, QDoubleSpinBox { padding: 5px; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #2563eb; }
QTableWidget { gridline-color: #edf1f7; selection-background-color: #e3edfc; selection-color: #253247; }
QHeaderView::section { background: #f0f3f8; border: 0; border-bottom: 1px solid #d7dee8; padding: 6px; font-weight: 600; }
QTabWidget::pane { border: 1px solid #d7dee8; border-radius: 5px; background: #ffffff; }
QTabBar::tab { padding: 7px 12px; color: #64748b; }
QTabBar::tab:selected { color: #1d4ed8; font-weight: 600; }
QScrollArea { border: 0; background: transparent; }
QSplitter::handle { background: #e0e6ef; }
QSplitter::handle:horizontal { width: 5px; }
QProgressBar { border: 1px solid #d7dee8; border-radius: 5px; background: #ffffff; min-height: 20px; text-align: center; }
QProgressBar::chunk { background: #3b82f6; border-radius: 4px; }
QStatusBar { color: #64748b; border-top: 1px solid #e0e6ef; }
"""
