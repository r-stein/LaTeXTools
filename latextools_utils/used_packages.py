import re

try:
    from ..getTeXRoot import get_tex_root
    from .analysis import get_analysis, objectview
    from . import cache
except:
    from getTeXRoot import get_tex_root
    from latextools_utils.analysis import get_analysis, objectview
    from latextools_utils import cache

_PKG_CACHE = "used_packages"


def used_package_names(view):
    """return all used package names as a list of string"""
    pkg = _get_used_packages(view)
    return [p.package for p in pkg]


def used_packages(view):
    """
    Returns a list of all used packages with their options
    Each package object has the attribute "package" and the attribute "args"
    """
    return _get_used_packages(view)


def _get_used_packages(view):
    tex_root = get_tex_root(view)
    if not tex_root:
        return

    def create_packages():
        ana = get_analysis(tex_root)
        return list(_create_used_packages(ana))

    pkg = cache.cache(tex_root, _PKG_CACHE, create_packages)
    return pkg


def _create_used_packages(ana):
    used_packages = ana.filter_commands(["usepackage", "Requirepackage"])

    def as_list(s):
        return re.sub(r"\s*,\s*", ",", s).split(",") if s else []

    for c in used_packages:
        for p in as_list(c.args):
            yield objectview({"package": p, "args": as_list(c.optargs)})
