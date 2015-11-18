# -*- coding:utf-8 -*-
import sublime
import sublime_plugin
import os
import re
import codecs

if sublime.version() < '3000':
    # we are on ST2 and Python 2.X
    _ST3 = False
    from latex_cite_completions import OLD_STYLE_CITE_REGEX, NEW_STYLE_CITE_REGEX, match
    from latex_ref_completions import OLD_STYLE_REF_REGEX, NEW_STYLE_REF_REGEX
    from getRegion import get_Region
    from latextools_utils.used_packages import used_package_names
else:
    _ST3 = True
    from .latex_cite_completions import OLD_STYLE_CITE_REGEX, NEW_STYLE_CITE_REGEX, match
    from .latex_ref_completions import OLD_STYLE_REF_REGEX, NEW_STYLE_REF_REGEX
    from .getRegion import get_Region
    from .latextools_utils.used_packages import used_package_names

# Do not do completions in these envrioments
ENV_DONOT_AUTO_COM = [
    OLD_STYLE_CITE_REGEX,
    NEW_STYLE_CITE_REGEX,
    OLD_STYLE_REF_REGEX,
    NEW_STYLE_REF_REGEX,
    re.compile(r'\\\\')
]

CWL_COMPLETION = False

class LatexCwlCompletion(sublime_plugin.EventListener):

    def on_query_completions(self, view, prefix, locations):
        # settings = sublime.load_settings("LaTeXTools.sublime-settings")
        # cwl_completion = settings.get('cwl_completion')

        if not CWL_COMPLETION:
            return []

        point = locations[0]
        if not view.score_selector(point, "text.tex.latex"):
            return []

        line = view.substr(get_Region(view.line(point).a, point))
        if re.match(r".*\\(?:(begin)|(end))\{[^\}]*$", line):
            completions = parse_cwl_file(True)
            if view.substr(sublime.Region(point, point + 1)) != "}":
                completions = [(x[0], x[1] + "}") for x in completions]
            return completions

        bpoint = point - len(prefix)
        char_before = view.substr(sublime.Region(bpoint - 1, bpoint))
        if char_before != "\\":
            return []

        line = line[::-1]

        # Do not do completions in actions
        for rex in ENV_DONOT_AUTO_COM:
            if match(rex, line) != None:
                return []

        completions = parse_cwl_file()
        # autocompleting with slash already on line
        # this is necessary to work around a short-coming in ST where having a keyed entry
        # appears to interfere with it recognising that there is a \ already on the line
        #
        # NB this may not work if there are other punctuation marks in the completion
        # since these are rare in TeX, this is probably ok
        if len(line) > 0 and line[0] == '\\':
            _completions = []
            for completion in completions:
                _completion = completion[1]
                if  _completion[0] == '\\' and '${1:' in _completion:
                    completion = (completion[0], _completion[1:])
                _completions.append(completion)
        else:
            _completions = completions
        return (_completions, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

    # This functions is to determine whether LaTeX-cwl is installed,
    # if so, trigger auto-completion in latex buffers by '\'
    def on_activated(self, view):
        point = view.sel()[0].b
        if not view.score_selector(point, "text.tex.latex"):
            return

        # Checking whether LaTeX-cwl is installed
        global CWL_COMPLETION
        if os.path.exists(sublime.packages_path() + "/LaTeX-cwl") or \
            os.path.exists(sublime.installed_packages_path() + "/LaTeX-cwl.sublime-package"):
            CWL_COMPLETION = True

        if CWL_COMPLETION:
            g_settings = sublime.load_settings("Preferences.sublime-settings")
            acts = g_settings.get("auto_complete_triggers", [])

            # Whether auto trigger is already set in Preferences.sublime-settings
            TEX_AUTO_COM = False
            for i in acts:
                if i.get("selector") == "text.tex.latex" and i.get("characters") == "\\":
                    TEX_AUTO_COM = True

            if not TEX_AUTO_COM:
                acts.append({
                    "characters": "\\",
                    "selector": "text.tex.latex"
                })
                g_settings.set("auto_complete_triggers", acts)

def parse_cwl_file(is_begin_env=False):
    # Get cwl file list
    # cwl_path = sublime.packages_path() + "/LaTeX-cwl"
    settings = sublime.load_settings("LaTeXTools.sublime-settings")
    view = sublime.active_window().active_view()
    cwl_file_list = view.settings().get('cwl_list',
        settings.get(
            'cwl_list',
            [
                "tex.cwl",
                "latex-209.cwl",
                "latex-document.cwl",
                "latex-l2tabu.cwl",
                "latex-mathsymbols.cwl"
            ]))

    cwl_file_list.extend(p + ".cwl" for p in used_package_names(view))

    # ST3 can use load_resource api, while ST2 do not has this api
    # so a little different with implementation of loading cwl files.
    if _ST3:
        cwl_files = ['Packages/LaTeX-cwl/%s' % x for x in cwl_file_list]
    else:
        cwl_files = [os.path.normpath(sublime.packages_path() + "/LaTeX-cwl/%s" % x) for x in cwl_file_list]

    completions = []
    for cwl in cwl_files:
        if _ST3:
            try:
                s = sublime.load_resource(cwl)
            except IOError:
                print(cwl + ' does not exist or could not be accessed')
                continue
        else:
            try:
                f = codecs.open(cwl, 'r', 'utf-8')
            except IOError:
                print(cwl + ' does not exist or could not be accessed')
                continue
            else:
                try:
                    s = u''.join(f.readlines())
                finally:
                    f.close()

        method = os.path.splitext(os.path.basename(cwl))[0]

        if not is_begin_env:
            def createItem(line):
                keyword = line.strip()
                item = (u'%s\t%s' % (keyword, method), parse_keyword(keyword))
                return item
        else:
            def createItem(line):
                pbe = parse_begine_end(line.strip())
                if pbe is None:
                    return
                keyword, entry = pbe
                item = (u'%s\t%s' % (keyword, method), entry)
                return item

        for line in s.split('\n'):
            line = line.strip()
            if line == '':
                continue
            if line[0] == '#':
                continue

            item = createItem(line)
            if item is not None:
                completions.append(item)

    return completions


def parse_begine_end(line):
    lre = re.compile(
        r"\\begin(?:\[.*\])?"
        r"\{(?P<env>[^\}]*)\}"
        r"(?P<after>(?:\{[^\}]*\})*)"
        )

    def compatible(x):
        return re.sub(r"[\{\}\s\*]", "-", x)
    m = lre.search(line)
    if m and m.group("env"):
        env = m.group("env")
        if not m.group("after"):
            return (compatible(env), env)
        after = m.group("after")
        return ("%s%s"%(compatible(env), compatible(after)), "%s}%s"%(env, parse_keyword(after)[:-1]))


def parse_keyword(keyword):
    # Replace strings in [] and {} with snippet syntax
    def replace_braces(matchobj):
        replace_braces.index += 1
        if matchobj.group(1) != None:
            word = matchobj.group(1)
            return u'{${%d:%s}}' % (replace_braces.index, word)
        else:
            word = matchobj.group(2)
            return u'[${%d:%s}]' % (replace_braces.index, word)
    replace_braces.index = 0

    replace, n = re.subn(r'\{([^\{\}\[\]]*)\}|\[([^\{\}\[\]]*)\]', replace_braces, keyword)

    # I do not understand why some of the input will eat the '\' charactor before it!
    # This code is to avoid these things.
    if n == 0 and re.search(r'^[a-zA-Z]+$', keyword[1:].strip()) != None:
        return keyword
    else:
        return replace
