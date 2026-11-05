#!/usr/bin/env python3
"""Entry point for the CARLA 0.9.16 GUI Control Panel."""

import sys
import os

# Allow imports from the carla_gui package root
sys.path.insert(0, os.path.dirname(__file__))

from gui.app import launch

if __name__ == "__main__":
    launch()
