import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt


class SearchAndReplacePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.panel = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.action = QAction(QIcon(icon_path), 'Search and Replace', self.iface.mainWindow())
        self.action.triggered.connect(self.run)

        if hasattr(self.iface, 'addToolBarIcon'):
            self.iface.addToolBarIcon(self.action)
        if hasattr(self.iface, 'addPluginToMenu'):
            self.iface.addPluginToMenu('&Search and Replace', self.action)
        elif hasattr(self.iface, 'editMenu'):
            self.iface.editMenu().addAction(self.action)

    def unload(self):
        if self.panel is not None:
            self.panel.cleanup()
            self.iface.removeDockWidget(self.panel)
            self.panel.deleteLater()
            self.panel = None

        if hasattr(self.iface, 'removeToolBarIcon'):
            self.iface.removeToolBarIcon(self.action)
        if hasattr(self.iface, 'removePluginMenu'):
            self.iface.removePluginMenu('&Search and Replace', self.action)
        elif hasattr(self.iface, 'editMenu'):
            self.iface.editMenu().removeAction(self.action)

    def run(self):
        if self.panel is None:
            from .search_and_replace_dialog import SearchAndReplacePanel
            self.panel = SearchAndReplacePanel(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.panel)
        else:
            self.panel.setVisible(not self.panel.isVisible())
