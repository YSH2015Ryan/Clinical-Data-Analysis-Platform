"""软件版本采集（§77/§78 可复现性；report 附录与 Analysis Manifest 共用单一事实源）。"""

import importlib.metadata
import platform

APP_VERSION = "0.1.0"

_SOFTWARE_PACKAGES = [
    "scikit-learn",
    "lifelines",
    "scikit-survival",
    "numpy",
    "pandas",
    "matplotlib",
    "jinja2",
    "weasyprint",
    "python-docx",
]


def software_versions() -> dict[str, str]:
    """运行环境软件版本：app + python + 关键库（缺装包跳过，不报错）。"""
    versions = {"app": APP_VERSION, "python": platform.python_version()}
    for pkg in _SOFTWARE_PACKAGES:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            continue
    return versions
