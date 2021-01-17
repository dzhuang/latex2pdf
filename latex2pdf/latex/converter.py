# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = "Copyright (C) 2020 Dong Zhuang"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import os
import re
import pathlib
from datetime import datetime
from django.utils.translation import ugettext as _

from latex.utils import (
    string_concat,
    popen_wrapper,
    get_abstract_latex_log,
)

debug = False

from typing import Text, Optional, Any, List, Dict, TYPE_CHECKING  # noqa
if TYPE_CHECKING:
    from django.core.checks.messages import CheckMessage  # noqa

LATEXMKRC = ".latexmkrc"


class LatexCompileError(RuntimeError):
    pass


class UnknownCompileError(RuntimeError):
    pass


class ImageConvertError(RuntimeError):
    pass


DEFAULT_FILE_REGEX = re.compile(r"@default_files\s*=\s*\((.*)\);")


def get_default_files_from_latexmkrc(working_dir):
    # type: (Text) -> List
    """
    Extract default files from .latexmkrc file.
    i.e., @default_files = ('main.tex'); or @default_files = ('file-one.tex', 'file-two.tex');
    results are ['main.tex'] or ['file-one.tex', 'file-two.tex']

    :param working_dir:
    :return:
    """
    latexmkrc_file = os.path.join(working_dir, LATEXMKRC)

    with open(latexmkrc_file, "r") as lf:
        configure_lines = [l.strip() for l in lf.read().split("\n")
                         if (l.strip() and not l.strip().startswith("#"))]
    result = []
    for l in configure_lines:
        match = DEFAULT_FILE_REGEX.match(l)
        if match:
            files_str_with_quote = match.group(1).strip()
            files_str = files_str_with_quote.replace('\'', '').replace('\"', '')
            result = [fs.strip() for fs in files_str.split(",")]

    return result


def get_file_with_replaced_ext(file_path, replace_ext):
    replace_ext = replace_ext.lstrip(".")
    base_name = os.path.splitext(file_path)[0]
    return "%s.%s" % (base_name, replace_ext)


def get_logfile_path(tex_file_path):
    return get_file_with_replaced_ext(tex_file_path, ".log")


def get_pdf_path(tex_file_path):
    return get_file_with_replaced_ext(tex_file_path, ".pdf")


def get_latest_log_file(working_dir):
    files = [os.path.join(working_dir, f) for f in os.listdir(working_dir)]
    files_with_time = [
        (f, datetime.fromtimestamp(pathlib.Path(f).stat().st_mtime))
        for f in files
        if os.path.isfile(f) and f.endswith(".log")]

    if not files_with_time:
        return None

    files_with_time.sort(key=lambda f: f[1])
    return files_with_time[-1][0]


def unzipped_folder_to_pdf_converter(working_dir, compiler=None, **kwargs):
    # type: (Text, Text, **Any) -> Dict
    """Convert LaTeX to pdf"""

    default_tex_files = get_default_files_from_latexmkrc(working_dir)

    print(get_latest_log_file(working_dir))

    command_line_args = ["latexmk"]
    if compiler is not None:
        command_line_args.append("-%s" % compiler)

    command_line_args.extend([
        '-latexoption="-no-shell-escape"',
        '-interaction=nonstopmode',
        '-halt-on-error'
    ])

    _output, error, status = popen_wrapper(command_line_args, cwd=working_dir)

    if status != 0:
        log_path = get_latest_log_file(working_dir)
        if log_path is not None:
            try:
                with open(log_path, 'rb') as f:
                    log = f.read().decode()
            except OSError:
                # no log file is generated
                raise LatexCompileError(error)

            log = get_abstract_latex_log(log).replace("\\n", "\n").strip()
            raise LatexCompileError(log)
        else:
            raise UnknownCompileError(
                string_concat(
                    ("%s " % error) if error else "",
                    _("when executing '%s', " % " ".join(command_line_args)),
                    _('no pdf file was generated.')
                ))

    pdfs = [get_pdf_path(tex_path) for tex_path in default_tex_files]

    for pdf in pdfs:
        if not os.path.isfile(os.path.join(working_dir, pdf)):
            raise UnknownCompileError(
                string_concat(
                    _('No file named "%s" was generated after compile.' % pdf)
                ))

    return dict((pdf, os.path.join(working_dir, pdf)) for pdf in pdfs)


# vim: foldmethod=marker
