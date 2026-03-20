from pathlib import Path

try:
    from importlib.metadata import version
    __version__ = version("stock-analysis")
except Exception:
    # 套件未以 editable mode 安裝時，直接從 pyproject.toml 讀取
    import tomllib
    _pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if _pyproject.exists():
        with open(_pyproject, "rb") as f:
            __version__ = tomllib.load(f)["project"]["version"]
    else:
        __version__ = "0.0.0"
