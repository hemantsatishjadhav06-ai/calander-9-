"""The server the browser tests run against: ``python -m tests.e2e.server``.

The web app and the worker in one process on 127.0.0.1, with ``config.settings.e2e``, its own
database, the faked team (``fakes``), the mocked platforms (``mocks``), a socket guard
(``netguard``), a seeded world (``seed``) and named, typed fixtures and probes (``registry``,
``steps/``) served under ``/__e2e__/`` by the e2e URL conf only. Importing this package has no side
effects; ``__main__`` installs everything.
"""
