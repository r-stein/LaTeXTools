import sublime
import sublime_plugin
import re

try:
    from .latextools_utils import analysis, cache
    from .getTeXRoot import get_tex_root
    from .getRegion import get_Region
    from . import latex_cwl_completions
except:
    from latextools_utils import analysis, cache
    from getTeXRoot import get_tex_root
    from getRegion import get_Region
    import latex_cwl_completions


class LatexSelfDefinedCommandCompletion(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, locations):
        point = locations[0]
        if not view.score_selector(point, "text.tex.latex"):
            return []

        tex_root = get_tex_root(view)

        # environment completion for \begin{ and \end{
        line = view.substr(get_Region(view.line(point).a, point))
        if re.match(r".*\\(?:(begin)|(end))\{[^\}]*$", line):
            return cache.cache(tex_root, "own_env_completion",
                               lambda:
                               [(c.args + "\tself-defined", c.args) for c in
                                analysis.get_analysis(tex_root)
                                        .filter_commands([
                                            "newenvironment",
                                            "renewenvironment"])])

        def create_completion():
            ana = analysis.get_analysis(tex_root)
            com = ana.filter_commands(["newcommand", "renewcommand"])
            return [_parse_command(c) for c in com]

        res = cache.cache(tex_root, "own_command_completion",
                          create_completion)

        bpoint = point - len(prefix)
        char_before = view.substr(sublime.Region(bpoint - 1, bpoint))
        if char_before == "\\":
            res = [(c[0], c[1][1:]) for c in res]
        return res


def _parse_command(c):
    class NoArgs(Exception):
        pass
    try:
        if not c.optargs2:
            raise NoArgs()
        arg_count = int(c.optargs2)
        has_opt = bool(c.optargs2a)
        s = c.args
        if has_opt:
            s += "[{0}]".format(c.optargs2a)
            arg_count -= 1
        elif arg_count == 0:
            raise NoArgs()
        s += "{arg}" * arg_count
        comp = latex_cwl_completions.parse_keyword(s)
    except:  # no args
        s = c.args + "{}"
        comp = s
    return (s + "\tself-defined", comp)
