from __future__ import annotations


APP_STYLE_SHEET = """
QWidget {
    background: #F0FDFA;
    color: #134E4A;
    font-family: "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    font-size: 13px;
}

QMainWindow {
    background: #F0FDFA;
}

QFrame#Card {
    background: #FFFFFF;
    border: 1px solid #CCFBF1;
    border-radius: 14px;
}

QFrame#KpiCard {
    background: #FFFFFF;
    border: 1px solid #99F6E4;
    border-radius: 14px;
}

QLabel#CardTitle,
QLabel#PanelTitle {
    color: #0F766E;
    font-size: 14px;
    font-weight: 700;
}

QLabel#KpiTitle {
    color: #0F766E;
    font-size: 12px;
    font-weight: 600;
}

QLabel#KpiValue {
    color: #134E4A;
    font-size: 24px;
    font-weight: 700;
}

QLabel#KpiHint {
    color: #0F766E;
    font-size: 11px;
}

QLabel#BadgeLabel {
    border-radius: 10px;
    padding: 4px 10px;
    font-weight: 600;
}

QLabel#Banner {
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 600;
}

QLineEdit,
QSpinBox,
QComboBox,
QPlainTextEdit,
QTableView,
QTabWidget::pane {
    background: #FFFFFF;
    border: 1px solid #BEE3DB;
    border-radius: 10px;
}

QLineEdit,
QSpinBox,
QComboBox {
    min-height: 38px;
    padding: 0 10px;
    selection-background-color: #14B8A6;
}

QPlainTextEdit {
    padding: 10px;
}

QPushButton {
    min-height: 40px;
    border: 1px solid #0D9488;
    border-radius: 10px;
    padding: 0 14px;
    background: #0D9488;
    color: #FFFFFF;
    font-weight: 600;
}

QPushButton:hover {
    background: #0F766E;
}

QPushButton:disabled {
    background: #CBD5E1;
    border-color: #CBD5E1;
    color: #F8FAFC;
}

QPushButton[variant="secondary"] {
    background: #FFFFFF;
    color: #0D9488;
}

QPushButton[variant="secondary"]:hover {
    background: #F0FDFA;
}

QPushButton[variant="accent"] {
    background: #F97316;
    border-color: #F97316;
}

QPushButton[variant="accent"]:hover {
    background: #EA580C;
}

QPushButton:focus,
QLineEdit:focus,
QSpinBox:focus,
QComboBox:focus,
QTableView:focus,
QPlainTextEdit:focus {
    border: 2px solid #F97316;
}

QHeaderView::section {
    background: #CCFBF1;
    color: #0F766E;
    border: none;
    border-bottom: 1px solid #99F6E4;
    padding: 8px;
    font-weight: 700;
}

QTableView {
    gridline-color: #E6FFFA;
    selection-background-color: #CCFBF1;
    selection-color: #134E4A;
}

QTabBar::tab {
    background: #CCFBF1;
    border: 1px solid #99F6E4;
    border-bottom: none;
    padding: 10px 16px;
    margin-right: 4px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}

QTabBar::tab:selected {
    background: #FFFFFF;
    color: #0F766E;
}

QGroupBox {
    border: 1px solid #CCFBF1;
    border-radius: 12px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: 700;
}

QGroupBox::title {
    left: 12px;
    padding: 0 4px;
}
"""
