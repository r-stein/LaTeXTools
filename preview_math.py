import os
import re
import struct
import threading
import time
import types

import sublime
import sublime_plugin


_ST3 = sublime.version() >= "3000"
if _ST3:
    from .latextools_utils import cache
    from . import preview_utils
    from .preview_utils import (
        call_shell_command, convert_installed, try_delete_temp_files
    )

_IS_SUPPORTED = sublime.version() >= "3118"
if _IS_SUPPORTED:
    import mdpopups


# the default and usual template for the latex file
default_latex_template = """
\\documentclass[preview]{standalone}
<<packages>>
<<preamble>>
\\begin{document}
<<content>>
\\end{document}
"""


# the path to the temp files (set on loading)
temp_path = None

# we use png files for the html popup
_IMAGE_EXTENSION = ".png"

_scale_quotient = 1
_density = 150
_lt_settings = {}


def _on_setting_change():
    global _density, _scale_quotient
    _scale_quotient = _lt_settings.get(
        "preview_math_scale_quotient", _scale_quotient)
    _density = _lt_settings.get("preview_math_density", _density)


def plugin_loaded():
    global _lt_settings, temp_path
    _lt_settings = sublime.load_settings("LaTeXTools.sublime-settings")

    temp_path = os.path.join(cache._global_cache_path(), "preview_math")
    # validate the temporary file directory is available
    if not os.path.exists(temp_path):
        os.makedirs(temp_path)

    # init all variables
    _on_setting_change()
    # add a callback to setting changes
    _lt_settings.add_on_change("lt_preview_math_main", _on_setting_change)


def _create_image(latex_program, latex_document, base_name):
    """Create an image for a latex document."""
    rel_source_path = base_name + ".tex"
    pdf_path = os.path.join(temp_path, base_name + ".pdf")
    image_path = os.path.join(temp_path, base_name + _IMAGE_EXTENSION)

    # write the latex document
    source_path = os.path.join(temp_path, rel_source_path)
    with open(source_path, "w", encoding="utf-8") as f:
        f.write(latex_document)

    # compile the latex document to a pdf
    call_shell_command(
        "cd \"{temp_path}\" && "
        "{latex_program} -interaction=nonstopmode "
        "{rel_source_path}"
        .format(temp_path=temp_path, **locals())
    )

    pdf_exists = os.path.exists(pdf_path)
    if not pdf_exists:
        dvi_path = os.path.join(temp_path, base_name + ".dvi")
        if os.path.exists(dvi_path):
            pdf_path = dvi_path
            pdf_exists = True

    if pdf_exists:
        # convert the pdf to a png image
        density = _density
        call_shell_command(
            "convert -density {density}x{density} -trim "
            '"{pdf_path}" "{image_path}"'
            .format(**locals())
        )

    # cleanup created files
    for ext in ["tex", "aux", "log", "pdf", "dvi"]:
        delete_path = os.path.join(temp_path, base_name + "." + ext)
        if os.path.exists(delete_path):
            os.remove(delete_path)


def _convert_image_thread(thread_id):
    print("start convert thread", thread_id, threading.get_ident())
    while True:
        try:
            with _job_list_lock:
                do = _job_list.pop()[0]
            do()
        except IndexError:
            break
        except Exception as e:
            print("Exception:", e)
            break
        if thread_id >= _max_threads:
            break
    print("close convert thread", thread_id, threading.get_ident())

    # decrease the number of threads -> delete this thread
    global _thread_num
    with _thread_num_lock:
        _thread_num -= 1
        remaining_threads = _thread_num

    # if all threads have been terminated we can check to delete
    # the temporary files beyond the size limit
    if remaining_threads == 0:
        try_delete_temp_files("preview_math", temp_path)


_max_threads = 2
_job_list_lock = threading.Lock()
_job_list = []
_thread_num_lock = threading.Lock()
_thread_num = 0


def _cancel_image_jobs(vid, p=None):
    global _job_list

    if p is None:
        def is_target_job(job):
            return job[1] == vid
    elif isinstance(p, list):
        pset = set(p)

        def is_target_job(job):
            return job[1] == vid and job[2] in pset
    else:
        def is_target_job(job):
            return job[1] == vid and job[2] == p
    with _job_list_lock:
        if any(is_target_job(job) for job in _job_list):
            _job_list = [job for job in _job_list if not is_target_job(job)]


def _wrap_create_image(latex_program, latex_document, base_name, cont):
    def do():
        _create_image(latex_program, latex_document, base_name)
        cont()
    return do


def _extend_image_jobs(vid, latex_program, jobs):
    global _job_list
    prepared_jobs = []
    for job in jobs:
        wrap = _wrap_create_image(
            latex_program, job["latex_document"], job["base_name"],
            job["cont"])
        prepared_jobs.append((wrap, vid, job["p"]))

    with _job_list_lock:
        _job_list.extend(prepared_jobs[::-1])


def _run_image_jobs():
    global _thread_num
    thread_id = -1

    # we may not need locks for this
    with _job_list_lock:
        rem_len = len(_job_list)
    with _thread_num_lock:
        before_num = _thread_num
        after_num = min(_max_threads, rem_len)
        start_threads = after_num - before_num
        if start_threads > 0:
            _thread_num += start_threads
    for thread_id in range(before_num, after_num):
        threading.Thread(target=_convert_image_thread,
                         args=(thread_id,)).start()


def _generate_html(view, image_path):
    with open(image_path, "rb") as f:
        image_raw_data = f.read()

    color = mdpopups.scope2style(view, "").get("color", "#CCCCCC")
    # create the image tag
    if _scale_quotient == 1 or len(image_raw_data) < 24:
        img_tag = mdpopups.tint(image_raw_data, color)
    else:
        # read the image dimensions out of the binary string
        width, height = struct.unpack(">ii", image_raw_data[16:24])
        width /= _scale_quotient
        height /= _scale_quotient
        img_tag = mdpopups.tint(
            image_raw_data, color, height=height, width=width)
    return img_tag


class MathPreviewPhantomListener(sublime_plugin.ViewEventListener,
                                 preview_utils.SettingsListener):
    key = "preview_math"
    # a dict from the file name to the content to avoid storing it for
    # every view
    template_contents = {}
    # cache to check refresh the template
    template_mtime = {}
    template_lock = threading.Lock()

    def __init__(self, view):
        self.view = view
        self.phantoms = []

        self._phantom_lock = threading.Lock()

        self._modifications = 0
        self._selection_modifications = 0

        self._init_watch_settings()

        if self.latex_template_file:
            sublime.set_timeout_async(self._read_latex_template_file)

        view.erase_phantoms(self.key)
        # start with updating the phantoms
        sublime.set_timeout_async(self.update_phantoms)

    def _init_watch_settings(self):
        # listen to setting changes to update the phantoms
        def update_packages_str(init=False):
            self.packages_str = "\n".join(self.packages)
            if not init:
                self.reset_phantoms()

        def update_preamble_str(init=False):
            if isinstance(self.preamble, str):
                self.preamble_str = self.preamble
            else:
                self.preamble_str = "\n".join(self.preamble)
            if not init:
                self.reset_phantoms()

        def update_template_file(init=False):
            self._read_latex_template_file(refresh=True)
            if not init:
                self.reset_phantoms()

        view_attr = {
            "visible_mode": {
                "setting": "preview_math_mode",
                "call_after": self.update_phantoms
            },
            "latex_program": {
                "setting": "preview_math_latex_compile_program",
                "call_after": self.reset_phantoms
            },
            "no_star_env": {
                "setting": "preview_math_no_star_envs",
                "call_after": self.reset_phantoms
            },
            "packages": {
                "setting": "preview_math_template_packages",
                "call_after": update_packages_str
            },
            "preamble": {
                "setting": "preview_math_template_preamble",
                "call_after": update_preamble_str
            },
            "latex_template_file": {
                "setting": "preview_math_latex_template_file",
                "call_after": update_template_file
            }
        }
        lt_attr = view_attr.copy()
        # watch this attributes for setting changes to reset the phantoms
        watch_attr = {
            "_watch_scale_quotient": {
                "setting": "preview_math_scale_quotient",
                "call_after": self.reset_phantoms
            },
            "_watch_density": {
                "setting": "preview_math_density",
                "call_after": self.reset_phantoms
            }
        }
        for attr_name, d in watch_attr.items():
            settings_name = d["setting"]
            self.__dict__[attr_name] = _lt_settings.get(settings_name)

        lt_attr.update(watch_attr)

        self._init_list_add_on_change("preview_math", view_attr, lt_attr)
        update_packages_str(init=True)
        update_preamble_str(init=True)
        update_template_file(init=True)

    def _read_latex_template_file(self, refresh=False):
        with self.template_lock:
            if not self.latex_template_file:
                return

            if self.latex_template_file in self.template_contents:
                if not refresh:
                    return
                try:
                    mtime = os.path.getmtime(self.latex_template_file)
                    old_mtime = self.template_mtime[self.latex_template_file]
                    if old_mtime == mtime:
                        return
                except:
                    return

            mtime = 0
            try:
                with open(self.latex_template_file, "r", encoding="utf8") as f:
                    file_content = f.read()
                mtime = os.path.getmtime(self.latex_template_file)
                print(
                    "LaTeXTools preview_math: "
                    "Load template file for '{0}'"
                    .format(self.latex_template_file)
                )
            except Exception as e:
                print(
                    "LaTeXTools preview_math: "
                    "Error while reading template file: {0}"
                    .format(e)
                )
                file_content = None
            self.template_contents[self.latex_template_file] = file_content
            self.template_mtime[self.latex_template_file] = mtime

    @classmethod
    def is_applicable(cls, settings):
        syntax = settings.get('syntax')
        return syntax == 'Packages/LaTeX/LaTeX.sublime-syntax'

    @classmethod
    def applies_to_primary_view_only(cls):
        return True

    #######################
    # MODIFICATION LISTENER
    #######################

    def on_after_modified_async(self):
        self.update_phantoms()

    def _validate_after_modified(self):
        self._modifications -= 1
        if self._modifications == 0:
            sublime.set_timeout_async(self.on_after_modified_async)

    def on_modified(self):
        self._modifications += 1
        sublime.set_timeout(self._validate_after_modified, 600)

    def on_after_selection_modified_async(self):
        if self.visible_mode == "selected" or not self.phantoms:
            self.update_phantoms()

    def _validate_after_selection_modified(self):
        self._selection_modifications -= 1
        if self._selection_modifications == 0:
            sublime.set_timeout_async(self.on_after_selection_modified_async)

    def on_selection_modified(self):
        if self._modifications:
            return
        self._selection_modifications += 1
        sublime.set_timeout(self._validate_after_selection_modified, 600)

    #########
    # METHODS
    #########

    def reset_phantoms(self):
        view = self.view
        _cancel_image_jobs(view.id())
        with self._phantom_lock:
            for p in self.phantoms:
                view.erase_phantom_by_id(p.id)
            self.phantoms = []
        self.update_phantoms()

    def update_phantoms(self):
        with self._phantom_lock:
            self._update_phantoms()

    def _update_phantoms(self):
        if not convert_installed():
            return
        if not self.view.is_primary():
            return
        view = self.view
        # TODO we may only want to apply if the view is visible
        if not any(view.window().active_view_in_group(g) == view
                   for g in range(view.window().num_groups())):
            return
        # if view != view.window().active_view():
        #     return

        # update the regions of the phantoms
        self._update_phantom_regions()

        new_phantoms = []
        job_args = []
        if self.visible_mode == "all":
            scopes = view.find_by_selector(
                "text.tex.latex meta.environment.math")
        elif self.visible_mode == "selected":
            math_scopes = view.find_by_selector(
                "text.tex.latex meta.environment.math")
            scopes = [scope for scope in math_scopes
                      if any(scope.contains(sel) for sel in view.sel())]
        elif self.visible_mode == "none":
            if not self.phantoms:
                return
            scopes = []
        else:
            print("Invalid mode reseted to \"none\".", self.visible_mode)
            self.visible_mode = "none"
            scopes = []

        for scope in scopes:
            content = view.substr(scope)
            multline = "\n" in content

            layout = (sublime.LAYOUT_BLOCK
                      if multline or self.visible_mode == "selected"
                      else sublime.LAYOUT_INLINE)
            region = sublime.Region(scope.end())

            try:
                p = next(e for e in self.phantoms if e.region == region)
                if p.content == content:
                    new_phantoms.append(p)
                    continue

                # update the content and the layout
                p.content = content
                p.layout = layout
            except:
                p = types.SimpleNamespace(
                    id=None,
                    region=region,
                    content=content,
                    layout=layout,
                    update_time=0
                )

            # generate the latex template
            latex_document = self._create_document(scope)

            # create a string, which uniquely identifies the compiled document
            id_str = "\n".join([
                self.latex_program,
                str(_density),
                latex_document
            ])
            base_name = cache.hash_digest(id_str)
            image_path = os.path.join(temp_path, base_name + _IMAGE_EXTENSION)

            # if the file exists as an image update the phantom
            if os.path.exists(image_path):
                if p.id is not None:
                    view.erase_phantom_by_id(p.id)
                    _cancel_image_jobs(view.id(), p)
                html_content = _generate_html(view, image_path)
                p.id = view.add_phantom(
                    self.key, region, html_content, layout, on_navigate=None)
                new_phantoms.append(p)
                continue
            # if neither the file nor the phantom exists, create a
            # placeholder phantom
            elif p.id is None:
                p.id = view.add_phantom(
                    self.key, region, "\u231B", layout, on_navigate=None)

            job_args.append({
                "latex_document": latex_document,
                "base_name": base_name,
                "p": p,
                "cont": self._make_cont(p, image_path, time.time())
            })

            new_phantoms.append(p)

        # delete deprecated phantoms
        delete_phantoms = [x for x in self.phantoms if x not in new_phantoms]
        for p in delete_phantoms:
            if p.region != sublime.Region(-1):
                view.erase_phantom_by_id(p.id)
        _cancel_image_jobs(view.id(), delete_phantoms)

        # set the new phantoms
        self.phantoms = new_phantoms

        # run the jobs to create the remaining images
        if job_args:
            _extend_image_jobs(view.id(), self.latex_program, job_args)
            _run_image_jobs()

    def _create_document(self, scope):
        view = self.view
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
            # if there is no offset it must be surrounded by an environment
            # get the name of the environment
            scope_end = scope.end()
            line_reg = view.line(scope_end)
            after_reg = sublime.Region(scope_end, line_reg.end())
            after_str = view.substr(line_reg)
            m = re.match(r"\\end\{([^\}]+?)(\*?)\}", after_str)
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
            star = "*" if env not in self.no_star_env or m.group(2) else ""
            # add a * to the env to avoid numbers in the resulting image
            open_str = "\\begin{{{env}{star}}}".format(**locals())
            close_str = "\\end{{{env}{star}}}".format(**locals())

        document_content = (
            "{open_str}\n{content}\n{close_str}"
            .format(**locals())
        )

        try:
            latex_template = self.template_contents[self.latex_template_file]
            if not latex_template:
                raise Exception("Template must not be empty!")
        except:
            latex_template = default_latex_template

        latex_document = (
            latex_template
            .replace("<<content>>", document_content, 1)
            .replace("<<packages>>", self.packages_str, 1)
            .replace("<<preamble>>", self.preamble_str, 1)
        )

        return latex_document

    def _make_cont(self, p, image_path, update_time):
        def cont():
            # if the image does not exists do nothing
            if not os.path.exists(image_path):
                return

            # generate the html
            html_content = _generate_html(self.view, image_path)
            # move to main thread and update the phantom
            sublime.set_timeout(
                self._update_phantom_content(p, html_content, update_time)
            )
        return cont

    def _update_phantom_regions(self):
        regions = self.view.query_phantoms([p.id for p in self.phantoms])
        for i in range(len(regions)):
            self.phantoms[i].region = regions[i]

    def _update_phantom_content(self, p, html_content, update_time):
        # if the current phantom is newer than the change ignore it
        if p.update_time > update_time:
            return
        view = self.view
        # update the phantom region
        p.region = view.query_phantom(p.id)[0]

        # if the region is -1 the phantom does not exists anymore
        if p.region == sublime.Region(-1):
            return

        # erase the old and add the new phantom
        view.erase_phantom_by_id(p.id)
        p.id = view.add_phantom(
            self.key, p.region, html_content, p.layout, on_navigate=None)

        # update the phantoms update time
        p.update_time = update_time