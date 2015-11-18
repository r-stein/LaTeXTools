import sublime
import sublime_plugin
import re

try:
    from .latextools_utils import analysis
    from .getRegion import get_Region
    from . import latex_cwl_completions
except:
    from latextools_utils import analysis
    from getRegion import get_Region
    import latex_cwl_completions


class LatexSelfDefinedCommandCompletion(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, locations):
        point = locations[0]
        if not view.score_selector(point, "text.tex.latex"):
            return []

        # environment completion for \begin{ and \end{
        line = view.substr(get_Region(view.line(point).a, point))
        if re.match(r".*\\(?:(begin)|(end))\{[^\}]*$", line):
            ana = analysis.get_analysis(view)
            com = ana.filter_commands(["newenvironment", "renewenvironment"])
            return [(c.args + "\tself-defined", c.args) for c in com]

        # only complete if it is a command
        bpoint = point - len(prefix)
        char_before = view.substr(sublime.Region(bpoint - 1, bpoint))
        if char_before != "\\":
            return []
        ana = analysis.get_analysis(view)
        com = ana.filter_commands(["newcommand", "renewcommand"])

        res = [(c.args + "\tself-defined", _parse_command(c)) for c in com]
        return res


def _parse_command(c):
    if not c.optargs2:
        return c.args + "{}"
    try:
        arg_count = int(c.optargs2)
        has_opt = bool(c.optargs2a)
        s = c.args
        if has_opt:
            s += "[{0}]".format(c.optargs2a)
            arg_count -= 1
        elif arg_count == 0:
            return s + "{}"
        s += "{arg}" * arg_count
        return latex_cwl_completions.parse_keyword(s)
    except:
        return c.args + "{}"
