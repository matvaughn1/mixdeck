"""Mixdeck: a PipeWire mixer with X-Touch control.

    python -m mixdeck            open the window
    python -m mixdeck --hidden   start in the tray (used at login)
"""
import os
import signal
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

HERE = os.path.dirname(os.path.abspath(__file__))
SOCKET = "mixdeck-" + str(os.getuid())


def already_running():
    """If Mixdeck is already up, ask it to show its window and return True."""
    s = QLocalSocket()
    s.connectToServer(SOCKET)
    if s.waitForConnected(300):
        s.write(b"show")
        s.waitForBytesWritten(300)
        s.disconnectFromServer()
        return True
    return False


def main():
    hidden = "--hidden" in sys.argv
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv)
    app.setApplicationName("Mixdeck")
    app.setDesktopFileName("mixdeck")
    app.setQuitOnLastWindowClosed(False)
    icon = QIcon(os.path.join(HERE, "icon.svg"))
    app.setWindowIcon(icon)

    if already_running():
        return 0
    QLocalServer.removeServer(SOCKET)
    server = QLocalServer()
    server.listen(SOCKET)

    from .backend import Backend
    backend = Backend()

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(os.path.join(HERE, "qml", "Main.qml")))
    if not engine.rootObjects():
        backend.shutdown()
        return 1
    win = engine.rootObjects()[0]

    def show():
        win.show()
        win.raise_()
        win.requestActivate()

    def on_connection():
        conn = server.nextPendingConnection()
        if conn:
            conn.readyRead.connect(show)
    server.newConnection.connect(on_connection)

    def quit_app():
        backend.shutdown()
        app.quit()

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(icon)
        tray.setToolTip("Mixdeck")
        menu = QMenu()
        act_show = QAction("Open Mixdeck", menu, triggered=show)
        act_quit = QAction("Quit", menu, triggered=quit_app)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_quit)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: (win.setVisible(not win.isVisible()) if win.isVisible() else show())
                               if reason == QSystemTrayIcon.Trigger else None)
        tray.show()
    else:
        # No tray: closing the window quits
        app.setQuitOnLastWindowClosed(True)
        app.aboutToQuit.connect(backend.shutdown)

    if not hidden or tray is None:
        show()

    signal.signal(signal.SIGTERM, lambda *_: quit_app())
    signal.signal(signal.SIGINT, lambda *_: quit_app())
    # let Python see signals while Qt's loop runs
    from PySide6.QtCore import QTimer
    tick = QTimer(interval=500, timeout=lambda: None)
    tick.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
