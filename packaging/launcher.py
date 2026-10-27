"""Точка входа собранной программы (PyInstaller): запускает интерфейс ЖелезоЧек."""

import sys

from hwcheck.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
