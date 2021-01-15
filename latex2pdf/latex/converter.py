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
import errno
import sys
import shutil
import re
import pathlib
from datetime import datetime
from wand.image import Image as wand_image
from hashlib import md5

from django.core.management.base import CommandError
from django.utils.encoding import DEFAULT_LOCALE_ENCODING
from django.utils.translation import ugettext as _

from latex.utils import (
    string_concat, CriticalCheckMessage,
    popen_wrapper,
    file_read, file_write, get_abstract_latex_log,
)

debug = False

from typing import Text, Optional, Any, List, Dict, TYPE_CHECKING  # noqa
if TYPE_CHECKING:
    from django.core.checks.messages import CheckMessage  # noqa

LATEXMKRC = ".latexmkrc"


TIKZ_PGF_RE = re.compile(r"\\begin\{(?:tikzpicture|pgfpicture)\}")


class LatexCompileError(RuntimeError):
    pass


class UnknownCompileError(RuntimeError):
    pass


class ImageConvertError(RuntimeError):
    pass


# {{{ latex compiler classes and image converter classes


class CommandBase(object):
    @property
    def name(self):
        # type: () -> Text
        """
        The name of the command tool
        """
        pass
        # raise NotImplementedError

    @property
    def cmd(self):
        # type: () -> Text
        """
        The string of the command
        """
        pass
        # raise NotImplementedError

    @property
    def skip_version_check(self):
        # type: () -> bool
        return False

    min_version = None  # type: Optional[Text]
    max_version = None  # type: Optional[Text]
    bin_path = ""  # type: Text

    def __init__(self):
        # type: () -> None
        self.bin_path = self.get_bin_path()

    def get_bin_path(self):
        pass
        # return self.cmd.lower()

    def version_popen(self):
        return popen_wrapper(
            [self.bin_path, '--version'],
            stdout_encoding=DEFAULT_LOCALE_ENCODING
        )

    def check(self):
        # type: () -> List[CheckMessage]
        errors = []

        self.bin_path = self.get_bin_path()

        try:
            out, err, status = self.version_popen()
        except CommandError as e:
            errors.append(CriticalCheckMessage(
                msg=e.__str__(),
                hint=("Unable to run '%(cmd)s with '--version'. Is "
                      "%(tool)s installed or has its "
                      "path correctly configured "
                      "in local_settings.py?") % {
                         "cmd": self.cmd,
                         "tool": self.name,
                     },
                obj=self.name,
                id="%s.E001" % self.name.lower()
            ))
            return errors

        if self.skip_version_check:
            return errors

        m = re.search(r'(\d+)\.(\d+)\.?(\d+)?', out)

        if not m:
            errors.append(CriticalCheckMessage(
                msg="\n".join([out, err]),
                hint=("Unable find the version of '%(cmd)s'. Is "
                      "%(tool)s installed with the correct version?"
                      ) % {
                         "cmd": self.cmd,
                         "tool": self.name,
                     },
                obj=self.name,
                id="%s.E002" % self.name.lower()
            ))
        else:
            version = ".".join(d for d in m.groups() if d)
            from pkg_resources import parse_version
            if self.min_version:
                if parse_version(version) < parse_version(self.min_version):
                    errors.append(CriticalCheckMessage(
                        "Version outdated",
                        hint=("'%(tool)s' with version "
                              ">=%(required)s is required, "
                              "current version is %(version)s"
                              ) % {
                                 "tool": self.name,
                                 "required": self.min_version,
                                 "version": version},
                        obj=self.name,
                        id="%s.E003" % self.name.lower()
                    ))
            if self.max_version:
                if parse_version(version) > parse_version(self.max_version):
                    errors.append(CriticalCheckMessage(
                        "Version not supported",
                        hint=("'%(tool)s' with version "
                              "< %(max_version)s is required, "
                              "current version is %(version)s"
                              ) % {
                                 "tool": self.name,
                                 "max_version": self.max_version,
                                 "version": version},
                        obj=self.name,
                        id="%s.E004" % self.name.lower()
                    ))
        return errors


class TexCompilerBase(CommandBase):
    pass


class Latexmk(TexCompilerBase):
    name = "latexmk"
    cmd = "latexmk"
    
    # This also require perl, ActivePerl is recommended
    min_version = "4.39"


class LatexCompiler(TexCompilerBase):
    latexmk_option = [
        '-latexoption="-no-shell-escape"',
        '-interaction=nonstopmode',
        '-halt-on-error'
    ]

    @property
    def output_format(self):
        # type: () -> Text
        raise NotImplementedError()

    def __init__(self):
        # type: () -> None
        super().__init__()
        self.latexmk_prog_repl = self._get_latexmk_prog_repl()

    def _get_latexmk_prog_repl(self):
        # type: () -> Text
        """
        Program replace when using "-pdflatex=" or "-latex="
        arg in latexmk, especially needed when compilers are
        not in system's default $PATH.
        :return: the latexmk arg "-pdflatex=/path/to/pdflatex" for
        # pdflatex or "-pdflatex=/path/to/xelatex" for xelatex
        """
        pass
        # return (
        #     "-%s=%s" % (self.name.lower(), self.bin_path.lower())
        # )

    def get_latexmk_subpro_cmdline(self, input_path):
        # type: (Text) -> List[Text]
        latexmk = Latexmk()
        args = [
            latexmk.bin_path,
            "-%s" % self.output_format,
            self.latexmk_prog_repl,
        ]
        args.extend(self.latexmk_option)
        args.append(input_path)

        return args


class Latex(LatexCompiler):
    name = "latex"
    cmd = "latex"
    output_format = "dvi"


class PdfLatex(LatexCompiler):
    name = "PdfLatex"
    cmd = "pdflatex"
    output_format = "pdf"


class LuaLatex(LatexCompiler):
    name = "LuaLatex"
    cmd = "lualatex"
    output_format = "pdf"

    def __init__(self):
        # type: () -> None
        super().__init__()
        self.latexmk_prog_repl = "-%s=%s" % ("pdflatex", self.bin_path)
        if sys.platform.startswith("win"):  # pragma: no cover
            self.latexmk_prog_repl = "-%s=%s" % ("pdflatex", "lualatex-dev")


class XeLatex(LatexCompiler):
    name = "XeLatex"
    cmd = "xelatex"
    output_format = "pdf"

    def __init__(self):
        # type: () -> None
        super().__init__()
        self.latexmk_prog_repl = "-%s=%s" % ("pdflatex", self.bin_path)


class ImageConverter(CommandBase):

    @property
    def output_format(self):
        # type: () -> Text
        raise NotImplementedError

    @staticmethod
    def convert_popen(cmdline, cwd):
        return popen_wrapper(cmdline, cwd=cwd)

    def do_convert(self, compiled_file_path, image_path, working_dir):
        cmdlines = self._get_convert_cmdlines(
            compiled_file_path, image_path)

        status = None
        error = None
        for cmdline in cmdlines:
            _output, error, status = self.convert_popen(
                cmdline,
                cwd=working_dir
            )
            if status != 0:
                return False, error

        return status == 0, error

    def _get_convert_cmdlines(
            self, input_filepath, output_filepath):
        # type: (Text, Text) -> List[List[Text]]
        raise NotImplementedError

# }}}


# {{{ convert file to data url

def get_data_url(file_path):
    # type: (Text) -> Text
    """
    Convert file to data URL
    """
    buf = file_read(file_path)

    from mimetypes import guess_type
    mime_type = guess_type(file_path)[0]

    from base64 import b64encode
    return "data:%(mime_type)s;base64,%(b64)s" % {
        "mime_type": mime_type,
        "b64": b64encode(buf).decode(),
    }

# }}}


# {{{ Base tex2img class

def build_key(tex_source, cmd, file_format="pdf"):
    from django.conf import settings
    version = getattr(settings, "L2P_KEY_VERSION", 1)

    return "%s_%s_%s_v%s" % (
        md5(tex_source.encode("utf-8")).hexdigest(),
        cmd, file_format, version)


class Tex2PdfBase(object):
    """The abstract class of converting tex source to images.
    """

    @property
    def compiler(self):
        # type: () -> LatexCompiler
        """
        :return: an instance of `LatexCompiler`
        """
        pass
        # raise NotImplementedError()

    def __init__(self, zip_file, zip_file_key=None, force_overwrite=False):
        # type: (...) -> None
        """
        :param zip_file: Required, a string representing the
        full tex source code.
        :param zip_file_key: a string which is the identifier of
        the zip file, if None, it will be generated using
        `tex_source`.
        """

        zip_file = zip_file.strip()
        assert isinstance(zip_file, str)

        self.zip_file = zip_file
        self.working_dir = None

        self.compiled_ext = ".pdf"

        if zip_file_key is None:
            zip_file_key = build_key(self.zip_file, self.compiler.cmd, self.image_format)
        self.zip_file_key = zip_file_key
        self.force_overwrite = force_overwrite

    def get_compiler_cmdline(self, tex_path):
        # type: (Text) -> List[Text]
        return self.compiler.get_latexmk_subpro_cmdline(tex_path)

    def save_source(self):  # pragma: no cover, this happens when debugging
        file_name = self.zip_file_key + ".tex"
        from django.conf import settings
        BASE_DIR = getattr(settings, "BASE_DIR")
        folder = os.path.join(BASE_DIR, "test_tex")

        try:
            os.makedirs(folder)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
        file_path = os.path.join(folder, file_name)
        file_write(file_path, self.zip_file.encode())

    def _remove_working_dir(self):
        # type: () -> None
        if debug:
            self.save_source()

        if self.working_dir:
            if debug:
                print(self.working_dir)
            else:
                shutil.rmtree(self.working_dir)

    def compile_popen(self, cmdline):
        # This method is introduced for facilitating subprocess tests.
        return popen_wrapper(cmdline, cwd=self.working_dir)

    def get_compiled_file(self):
        # type: () -> Optional[Text]
        """
        Compile latex source.
        :return: string, the path of the compiled file if succeeded.
        """
        from tempfile import mkdtemp

        # https://github.com/python/mypy/issues/1833
        self.working_dir = mkdtemp(prefix="LATEX_")  # type: ignore

        assert self.zip_file_key is not None
        assert self.working_dir is not None
        tex_filename_to_compile = self.zip_file_key + ".tex"
        tex_path = os.path.join(self.working_dir, tex_filename_to_compile)
        file_write(tex_path, self.zip_file.encode('UTF-8'))

        assert tex_path is not None
        log_path = tex_path.replace(".tex", ".log")
        compiled_file_path = tex_path.replace(
            ".tex", self.compiled_ext)

        cmdline = self.get_compiler_cmdline(tex_path)
        output, error, status = self.compile_popen(cmdline)

        if status != 0:
            try:
                log = file_read(log_path).decode("utf-8")
            except OSError:
                # no log file is generated
                self._remove_working_dir()
                raise LatexCompileError(error)

            log = get_abstract_latex_log(log).replace("\\n", "\n").strip()
            self._remove_working_dir()
            raise LatexCompileError(log)

        if os.path.isfile(compiled_file_path):
            return compiled_file_path
        else:
            self._remove_working_dir()

            raise UnknownCompileError(
                string_concat(
                    ("%s." % error) if error else "",
                    _('No %s file was generated.')
                    % self.compiler.output_format)
            )

    def get_converted_data_url(self):
        # type: () -> Optional[Text]
        """
        Convert compiled file into image.
        :return: string, the data_url
        """
        compiled_file_path = self.get_compiled_file()
        assert compiled_file_path

        try:
            data_url = get_data_url(compiled_file_path)
        except Exception as e:
            raise ImageConvertError(
                "%s:%s" % (type(e).__name__, str(e))
            )
        finally:
            self._remove_working_dir()

        return data_url

# }}}


# {{{ check if multiple images are generated due to long pdf

def get_number_of_pdf_file(pdf_path, pdf_ext="pdf"):
    # type: (Text, Text) -> int
    if os.path.isfile(pdf_path):
        return 1
    return 0

# }}}


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
                log = file_read(log_path).decode("utf-8")
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
    print(pdfs)

    for pdf in pdfs:
        if not os.path.isfile(os.path.join(working_dir, pdf)):
            raise UnknownCompileError(
                string_concat(
                    _('No file named "%s" was generated after compile.' % pdf)
                ))
    print(get_latest_log_file(working_dir))

    return dict(
            (tex_path,
                get_data_url(get_pdf_path(os.path.join(working_dir, tex_path)))
             )
            for tex_path in default_tex_files)


# vim: foldmethod=marker
