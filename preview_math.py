import os
import re
import subprocess

import sublime
import sublime_plugin


_ST3 = sublime.version() >= "3000"
if _ST3:
    from .latextools_utils import cache, get_setting
else:
    from latextools_utils import cache, get_setting

startupinfo = None
if sublime.platform() == "windows":
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW


# TODO read from file
latex_template = """
\\documentclass[preview]{standalone}
\\usepackage{amsmath}
\\usepackage{amssymb}
\\usepackage{latexsym}
\\usepackage{mathtools}
\\begin{document}
<<content>>
\\end{document}
"""

# we use png files for the html popup
_IMAGE_EXTENSION = ".png"


def _create_document(view, scope):
    """
    Create the document content for the scope content and calculate
    the location, where it should be showed.
    """
    content = view.substr(scope)
    env = None

    # calculate the leading and remaining characters to strip off
    # if not present it is surrounded by an environment
    if content[0:2] in ["\\[", "\\(", "$$"]:
        offset = 2
    elif content[0] == "$":
        offset = 1
    else:
        offset = 0

    # calculate the location of the popup:
    # if the content is a single line, set it to the start
    # if the scope is multi lines, set it to the end
    multline = "\n" in content
    location = (scope.end() - offset if multline else scope.begin() + offset)

    # if there is no offset it must be surrounded by an environment
    # get the name of the environment
    if offset == 0:
        scope_end = scope.end()
        line_reg = view.line(scope_end)
        after_reg = sublime.Region(scope_end, line_reg.end())
        after_str = view.substr(line_reg)
        m = re.match(r"\\end\{([^\}]+?)\*?\}", after_str)
        if m:
            env = m.group(1)

    # strip the content
    if offset:
        content = content[offset:-offset]
    content = content.strip()

    # create the wrap string
    open_str = "\\("
    close_str = "\\)"
    if env:
        # add a * to the env to avoid numbers in the resulting image
        # TODO blacklist of envs, which does not support a *
        open_str = "\\begin{{{env}*}}".format(env=env)
        close_str = "\\end{{{env}*}}".format(env=env)
    document_content = "{open_str}\n{content}\n{close_str}".format(**locals())

    latex_document = latex_template.replace("<<content>>", document_content)

    return latex_document, location


def _call_shell_command(command):
    """Call the command with shell=True and wait for it to finish"""
    subprocess.Popen(command,
                     shell=True,
                     startupinfo=startupinfo).wait()


def _create_image(view, temp_path, base_name, latex_document):
    source_path = base_name + ".tex"
    pdf_path = base_name + ".pdf"
    image_path = base_name + _IMAGE_EXTENSION

    # change to the working directory
    orig_dir = os.curdir
    os.chdir(temp_path)

    # write the latex document
    with open(source_path, "w") as f:
        f.write(latex_document)

    _call_shell_command(
        "pdflatex -shell-escape -interaction=nonstopmode {source_path}"
        .format(**locals())
    )
    # TODO read this from the settings
    density = 150
    _call_shell_command(
        "convert -density {density}x{density} -trim {pdf_path} {image_path}"
        .format(**locals())
    )

    # cleanup created files
    for ext in ["tex", "aux", "log", "pdf"]:
        delete_name = base_name + "." + ext
        if os.path.exists(delete_name):
            os.remove(delete_name)

    # change to the original directory
    os.chdir(orig_dir)


def _show_image(view, image_path, location):
    # don't show the image if it is already visible (don't let it blink)
    if view.settings().get("math_preview_image") == image_path:
        return
    view.settings().set("math_preview_image", image_path)

    def on_hide():
        view.settings().erase("math_preview_image")

    html_content = '<div><img src="file://{0}" /></div>'.format(image_path)

    def show():
        # don't hide when auto complete is visible
        flags = sublime.COOPERATE_WITH_AUTO_COMPLETE
        view.show_popup(html_content, on_hide=on_hide, location=location,
                        flags=flags)
    # better move showing the popup into the main thread
    sublime.set_timeout(show)


def preview_math(view, pos, live_preview=False):
    # retrieve the containing scope
    math_scopes = view.find_by_selector("meta.environment.math")
    try:
        containing_scope = next(s for s in math_scopes if s.contains(pos))
    except:
        print("Not inside a math scope.")
        return

    # create the latex document
    latex_document, location = _create_document(view, containing_scope)

    # calculate and create the path, where the images should be generated
    temp_path = os.path.join(cache._global_cache_path(), "math_preview")
    if not os.path.exists(temp_path):
        os.makedirs(temp_path)

    # create the file base name based on the latex document
    # i.e. a unique fingerprint of the document using a hash function
    base_name = cache.hash_digest(latex_document)

    # check whether the image already exists,
    # if yes show it and we are done
    full_image_path = os.path.join(temp_path, base_name + _IMAGE_EXTENSION)
    if os.path.exists(full_image_path):
        _show_image(view, full_image_path, location)
        return

    # inform the user, that the work is in process
    if not live_preview:
        view.show_popup("Generating preview...", location=location)

    # create the image from the document
    _create_image(view, temp_path, base_name, latex_document)
    # show the image
    _show_image(view, full_image_path, location)
