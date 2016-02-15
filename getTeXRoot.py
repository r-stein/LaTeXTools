# ST2/ST3 compat
from __future__ import print_function

import sublime
# get_tex_root and get_tex_root_from_settings has been moved to the utils
# import it to provide backward compatibility
if sublime.version() < '3000':
	from latextools_utils import get_tex_root, get_tex_root_from_settings
else:
	from .latextools_utils import get_tex_root, get_tex_root_from_settings
