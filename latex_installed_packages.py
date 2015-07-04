# -*- coding:utf-8 -*-
from __future__ import print_function 
import sublime
import sublime_plugin
if sublime.version() < '3000':
    # we are on ST2 and Python 2.X
    _ST3 = False
else:
    _ST3 = True

import subprocess as sp
import os
import sys
import json

# Generating cache for installed latex packages, classes and bst.
# Used for fill all command for \documentclass, \usepackage and
# \bibliographystyle envrioments
class LatexGenPkgCacheCommand(sublime_plugin.WindowCommand):

    def run(self):
        # For different platforms
        # in windows, env variables are seprated by ;
        # for UNIX like platform, its :   
        plat = sublime.platform()
        if plat == 'windows':
            delim = ';'
        else:
            delim = ':'

        # Need to make sure that kpsewhich is on our PATH
        # Read from settings file (see makePDF.py)

        old_path = os.environ["PATH"]
        s = sublime.load_settings("LaTeXTools.sublime-settings")
        platform_settings  = s.get(sublime.platform())
        texpath = platform_settings['texpath']
        if not _ST3:
            os.environ["PATH"] = os.path.expandvars(texpath).encode(sys.getfilesystemencoding())
        else:
            os.environ["PATH"] = os.path.expandvars(texpath)

        # Search path.
        # Note: must pass environment for Yosemite **AND** must send stderr to STDOUT. Crucial!
        p = sp.Popen("kpsewhich --show-path=tex", shell = True, stdout = sp.PIPE, stderr = sp.STDOUT, env = os.environ)
        pkg_path = p.communicate()[0].decode('utf-8')
        p = sp.Popen("kpsewhich --show-path=bst", shell = True, stdout = sp.PIPE, stderr = sp.STDOUT, env = os.environ)
        bst_path = p.communicate()[0].decode('utf-8')

        # Restore old path
        os.environ["PATH"] = old_path
        
        # For installed packages.
        installed_pkg = []

        # For installed bst files.
        installed_bst = []

        # For installed class files.
        installed_cls = []
        for path in pkg_path.strip().split(delim):

            # In OSX and Linux, there will be !! for some of the result of kpsewhich
            # strip them
            path = path.replace('!!', '') 
            if not os.path.exists(path):# Make sure path are exists
                continue
            for _, _, files in os.walk(os.path.normpath(path)):
                for f in files:
                    if f.endswith('.sty'): # Searching package files
                        installed_pkg.append(os.path.splitext(f)[0])
                    if f.endswith('.cls'): # Searching class files
                        installed_cls.append(os.path.splitext(f)[0])

        for path in bst_path.strip().split(delim):
            path = path.replace('!!', '')
            if not os.path.exists(path):
                continue
            for _, _, files in os.walk(os.path.normpath(path)):
                for f in files:
                    if f.endswith('.bst'): # Searching bst files.
                        installed_bst.append(os.path.splitext(f)[0])

        # pkg_cache
        pkg_cache = {'pkg':installed_pkg, 'bst':installed_bst, 'cls': installed_cls}

        # For ST3, put the cache files in cache dir
        # and for ST2, put it in package dir
        if _ST3:
            cache_path = os.path.normpath(sublime.cache_path() + "/" + "LaTeXTools")
        else:
            cache_path = os.path.normpath(sublime.packages_path() + "/" + "LaTeXTools")

        if not os.path.exists(cache_path):
            os.makedirs(cache_path)

        pkg_cache_file = os.path.normpath(cache_path + '/' + 'pkg_cache.cache')
        with open(pkg_cache_file, 'w+') as f:
            json.dump(pkg_cache, f)

