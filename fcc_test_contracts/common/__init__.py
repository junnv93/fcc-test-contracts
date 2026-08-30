"""Shared application-layer modules used by multiple web entrypoints.

This package owns SSOT artifacts that Session API + Headless API must share
without leaking into the infrastructure layer. Modules here MUST stay
dependency-free (no ``fastapi``, ``PySide6``, ``pyvisa``, ``openpyxl``,
``pandas``, ``sqlalchemy``).
"""
