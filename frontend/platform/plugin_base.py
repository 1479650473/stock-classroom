# -*- coding: utf-8 -*-
"""Plugin interface and platform services for stock-classroom."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QWidget


class PluginRegion(Enum):
    LEFT = "left"
    RIGHT = "right"
    TOPBAR = "topbar"


class PlatformBus(QObject):
    """Signal bus for inter-plugin communication."""
    open_kline = pyqtSignal(str, str)
    status_message = pyqtSignal(str)
    log_message = pyqtSignal(str)
    refresh_current = pyqtSignal()
    data_update_progress = pyqtSignal(str, object)


@dataclass
class PlatformServices:
    """Services injected into each plugin by the platform."""
    db_path: str
    cache_path: str
    bus: PlatformBus

    def status(self, msg: str):
        self.bus.status_message.emit(msg)

    def log(self, msg: str):
        self.bus.log_message.emit(msg)

    def open_kline(self, code: str, name: str):
        self.bus.open_kline.emit(code, name)


class IPlugin(ABC):
    """Every feature module must implement this interface."""

    def __init__(self):
        self._services = None
        self._widget = None

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique plugin identifier, e.g. 'market'."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Display name shown in nav bar, e.g. '市场'."""
        ...

    @property
    @abstractmethod
    def icon(self) -> str:
        """Unicode emoji shown above name in nav bar."""
        ...

    @property
    @abstractmethod
    def region(self) -> PluginRegion:
        """Which area of the platform this plugin occupies."""
        ...

    def set_services(self, services: PlatformServices):
        self._services = services

    @abstractmethod
    def create_widget(self) -> QWidget:
        """Create and return the plugin's main widget. Called once."""
        ...

    @property
    def widget(self) -> QWidget:
        if self._widget is None:
            self._widget = self.create_widget()
        return self._widget

    def on_activate(self):
        """Called when the plugin's tab is selected."""
        pass

    def on_deactivate(self):
        """Called when the plugin's tab is deselected."""
        pass

    def refresh(self):
        """Refresh data on demand."""
        pass

    def create_companion_widget(self) -> "QWidget | None":
        """Optional companion widget shown in right panel when this plugin is active.
        Return None to keep the default right behaviour (e.g. K-line chart)."""
        return None
