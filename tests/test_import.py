"""Import-level smoke test for the built extension. Opens no window."""

import sys


def main() -> int:
    import rome

    assert hasattr(rome, "App"), "rome.App is missing"
    assert hasattr(rome, "RomeError"), "rome.RomeError is missing"
    assert issubclass(rome.RomeError, Exception), "RomeError is not an exception type"
    assert isinstance(rome.__version__, str) and rome.__version__, "bad __version__"

    print(f"rome {rome.__version__} imported from {rome.__file__}")
    print(f"python {sys.version.split()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
