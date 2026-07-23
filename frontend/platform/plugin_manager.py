# -*- coding: utf-8 -*-
"""Plugin discovery, registration, activation, and error isolation."""

import os, json, importlib, sys, traceback
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QStackedWidget
)

from .plugin_base import IPlugin, PluginRegion, PlatformServices


class ErrorBoundary(QWidget):
    """Wraps a plugin widget. If creation fails, shows error + retry button."""

    def __init__(self, plugin_id: str, factory, parent=None):
        super().__init__(parent)
        self._plugin_id = plugin_id
        self._factory = factory
        self._content = None

        self._stack = QStackedWidget(self)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.addWidget(self._stack)

        self._error_widget = self._build_error_widget()
        self._stack.addWidget(self._error_widget)

        self._build()

    def _build_error_widget(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#0D1117;")
        lo = QVBoxLayout(w)
        lo.setAlignment(Qt.AlignCenter)
        lo.setSpacing(12)

        icon = QLabel("⚠")
        icon.setStyleSheet("font-size:36px;color:#D4A574;background:transparent;border:none;")
        icon.setAlignment(Qt.AlignCenter)
        lo.addWidget(icon)

        msg = QLabel("插件加载失败")
        msg.setStyleSheet("color:#E6EDF3;font-size:15px;font-weight:600;background:transparent;border:none;")
        msg.setAlignment(Qt.AlignCenter)
        lo.addWidget(msg)

        self._err_label = QLabel("")
        self._err_label.setStyleSheet("color:#8B949E;font-size:12px;background:transparent;border:none;")
        self._err_label.setAlignment(Qt.AlignCenter)
        self._err_label.setWordWrap(True)
        lo.addWidget(self._err_label)

        retry = QPushButton("重试")
        retry.setFixedSize(80, 28)
        retry.setCursor(Qt.PointingHandCursor)
        retry.setStyleSheet(
            "QPushButton{background:rgba(212,165,116,0.10);color:#D4A574;"
            "border:1px solid #D4A574;border-radius:6px;font-size:12px;}"
            "QPushButton:hover{background:rgba(212,165,116,0.18);}")
        retry.clicked.connect(self._build)
        retry_lo = QVBoxLayout()
        retry_lo.setAlignment(Qt.AlignCenter)
        retry_lo.addWidget(retry)
        lo.addLayout(retry_lo)

        return w

    def _build(self):
        try:
            self._content = self._factory()
            idx = self._stack.addWidget(self._content)
            self._stack.setCurrentIndex(idx)
        except Exception as e:
            traceback.print_exc()
            self._err_label.setText(str(e))
            self._stack.setCurrentIndex(0)

    @property
    def content(self) -> QWidget:
        return self._content


class PluginManager:
    """Discovery, registration, activation, and error isolation for plugins."""

    def __init__(self, config_path: str, scan_dir: str):
        self._plugins: Dict[str, IPlugin] = {}
        self._boundaries: Dict[str, ErrorBoundary] = {}
        self._active: Dict[PluginRegion, str] = {}
        self._config = {}
        self._nav_order: List[str] = []

        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        self._nav_order = self._config.get("nav_order", [])

        self.discover(scan_dir)

    def discover(self, scan_dir: str):
        """Scan scan_dir for plugin packages and instantiate them."""
        if not os.path.isdir(scan_dir):
            return

        # Ensure project root is in sys.path for frontend.* imports
        parent_dir = os.path.dirname(os.path.abspath(scan_dir))
        project_dir = os.path.dirname(parent_dir)
        if project_dir not in sys.path:
            sys.path.insert(0, project_dir)

        discovered = {}  # plugin_id -> IPlugin

        for entry in sorted(os.listdir(scan_dir)):
            full = os.path.join(scan_dir, entry)
            if not os.path.isdir(full):
                continue
            plugin_file = os.path.join(full, "plugin.py")
            if not os.path.isfile(plugin_file):
                continue

            try:
                module_name = f"frontend.plugins.{entry}.plugin"
                mod = importlib.import_module(module_name)
                for name in dir(mod):
                    obj = getattr(mod, name)
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, IPlugin)
                        and obj is not IPlugin
                    ):
                        inst = obj()
                        discovered[inst.plugin_id] = inst
            except Exception as e:
                traceback.print_exc()
                print(f"[PluginManager] Failed to load plugin from {entry}: {e}")

        # Register in config order
        for pid in self._nav_order:
            if pid in discovered:
                self.register(discovered.pop(pid))

        # Register any remaining discovered plugins
        for pid, plugin in discovered.items():
            self.register(plugin)

    def register(self, plugin: IPlugin):
        """Validate and register a plugin instance."""
        if not isinstance(plugin, IPlugin):
            raise TypeError(f"Expected IPlugin, got {type(plugin)}")
        pid = plugin.plugin_id
        if not pid:
            raise ValueError("Plugin ID must not be empty")
        self._plugins[pid] = plugin

    def inject_services(self, services: PlatformServices):
        """Inject platform services into all registered plugins."""
        for plugin in self._plugins.values():
            plugin.set_services(services)

    def get_nav_items(self) -> List[Tuple[str, str, str, PluginRegion]]:
        """Return nav items in configured order: (id, name, icon, region)."""
        items = []
        for pid in self._nav_order:
            if pid in self._plugins:
                p = self._plugins[pid]
                items.append((pid, p.name, p.icon, p.region))
        return items

    def activate(self, plugin_id: str):
        """Activate a plugin by ID. Deactivates current in same region first."""
        if plugin_id not in self._plugins:
            return

        plugin = self._plugins[plugin_id]
        region = plugin.region

        # Deactivate current in same region
        current_id = self._active.get(region)
        if current_id and current_id != plugin_id and current_id in self._plugins:
            try:
                self._plugins[current_id].on_deactivate()
            except Exception:
                pass

        # Ensure widget is created
        boundary = self._boundaries.get(plugin_id)
        if boundary is None:
            boundary = ErrorBoundary(plugin_id, lambda p=plugin: p.widget)
            self._boundaries[plugin_id] = boundary

        # Activate
        self._active[region] = plugin_id
        try:
            plugin.on_activate()
        except Exception:
            traceback.print_exc()

    def get_widget(self, plugin_id: str) -> Optional[QWidget]:
        """Get the error-wrapped widget for a plugin. Returns None if unknown."""
        boundary = self._boundaries.get(plugin_id)
        if boundary is None and plugin_id in self._plugins:
            plugin = self._plugins[plugin_id]
            boundary = ErrorBoundary(plugin_id, lambda p=plugin: p.widget)
            self._boundaries[plugin_id] = boundary
        return boundary

    def get_plugin(self, plugin_id: str) -> Optional[IPlugin]:
        return self._plugins.get(plugin_id)

    def active_id(self, region: PluginRegion) -> Optional[str]:
        return self._active.get(region)

    def all_plugins(self) -> Dict[str, IPlugin]:
        return dict(self._plugins)

    def refresh_current(self, region: PluginRegion = None):
        """Refresh the currently active plugin(s). If no region, refresh all active."""
        if region:
            pid = self._active.get(region)
            if pid and pid in self._plugins:
                try:
                    self._plugins[pid].refresh()
                except Exception:
                    traceback.print_exc()
        else:
            for pid in self._active.values():
                if pid in self._plugins:
                    try:
                        self._plugins[pid].refresh()
                    except Exception:
                        traceback.print_exc()

    def shutdown_all(self):
        """Gracefully shut down all registered plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.on_deactivate()
            except Exception:
                pass
