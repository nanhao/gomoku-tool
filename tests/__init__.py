"""Test package for gomoku-tool.

Pytest discovers every ``test_*.py`` module below this package; the fakes in
:mod:`tests.fakes` replace the engine, Redis and gomoku-ui at the process
boundary, so the business layer is exercised without any I/O.
"""
