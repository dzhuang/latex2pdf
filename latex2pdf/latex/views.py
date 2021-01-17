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

import shutil
import tempfile
import sys
import zipfile
import io
import os
import hashlib

from crispy_forms.layout import Submit
from django import forms
from django.contrib.auth.decorators import login_required
from django.db.transaction import atomic
from django.utils.translation import ugettext as _
from django.conf import settings
from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.http import Http404
from rest_framework import status

from latex.converter import (
    unzipped_folder_to_pdf_converter,
    LatexCompileError,
    LATEXMKRC
)
from latex.models import LatexProject, LatexCollection, LatexPdf
from latex.utils import StyledFormMixin, get_codemirror_widget


class Zip2PdfForm(StyledFormMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["project_name"] = forms.CharField(
            required=True,
            help_text=_("The name of the compile project."))

        self.fields["zip_file"] = forms.FileField(
            label=_("Zip File"), required=False,
            help_text=_("Optional. If upload a zip file, it must contain "
                        "a .latexmkrc file to with @default_files and "
                        "compiler configured. Other options, except 'zip_file_key'"
                        "in this form will be neglected."))

        self.fields["zip_file_key"] = forms.CharField(
            required=False,
            help_text=_("Optional. An unique string act as the identifier "
                        "of the LaTeX code. If not specified, it will be "
                        "generated automatically."))

        self.fields["latex_code"] = forms.CharField(
            label=_("Tex Code"),
            widget=get_codemirror_widget(),
            required=False,
        )

        self.fields["compiler"] = forms.ChoiceField(
            choices=tuple((c, c) for c in ["xelatex", "pdflatex"]),
            initial=("xelatex", "xelatex"),
            label=_("Compiler"),
            required=False)

        self.helper.form_class = "form-horizontal"

        self.helper.add_input(
                Submit("convert", _("Convert")))

    def clean(self):
        super().clean()
        # from django.template.defaultfilters import filesizeformat
        #
        # if zip_file.size > self.txt_max_file_size:
        #     raise forms.ValidationError(
        #         _("Please keep file size under %(allowedsize)s. "
        #           "Current filesize is %(uploadedsize)s.")
        #         % {'allowedsize': filesizeformat(self.txt_max_file_size),
        #            'uploadedsize': filesizeformat(zip_file.size)})

        zip_file = self.cleaned_data.get('zip_file', None)

        if not any([zip_file,
                    self.cleaned_data.get("latex_code", None)]):
            raise forms.ValidationError(
                _("Either 'Zip File' or 'Tex Code' must be filled.")
            )

        if zip_file is not None:
            if not zipfile.is_zipfile(zip_file):
                raise forms.ValidationError(
                    _("Please upload a zip file"))

            with zipfile.ZipFile(zip_file, "r") as zf:
                bad_zipped = zf.testzip()
                if zf.testzip() is not None:
                    raise forms.ValidationError(_("Bad file in zip file: %s" % bad_zipped))

                for required_file in [LATEXMKRC]:
                    if required_file not in zf.namelist():
                        raise forms.ValidationError(_("'%s' not found in zipfile uploaded" % required_file))


def view_collection(request, project_name, zip_file_key=None):
    if request.method == "POST":
        raise PermissionDenied("Not allow to post")

    project = get_object_or_404(LatexProject, name=project_name)

    if project.is_private and request.user != project.creator:
        raise PermissionDenied("Not allow to view project")

    collections = LatexCollection.objects.filter(project=project)
    pdf_instances = None

    collection = None

    if collections.count():
        if zip_file_key is not None:
            collections = collections.filter(zip_file_key=zip_file_key)
            if collections.count():
                collection = collections[0]
            else:
                raise Http404()
        else:
            collection = collections.order_by("-creation_time")[-1]

    if collection:
        pdf_instances = LatexPdf.objects.filter(project=project, collection=collection)

    ctx = {"collection": collection,
           "instances": pdf_instances}

    render_kwargs = {
        "request": request,
        "template_name": "latex/latex_view_collection.html",
        "context": ctx
    }

    if collection is not None:
        if collection.compile_error:
            render_kwargs["status"] = status.HTTP_400_BAD_REQUEST

    return render(**render_kwargs)


@login_required(login_url='/login/')
def request_get_compiled_pdf_from_latex_form_request(request):
    pdf_instances = None
    collection = None
    ctx = {}
    unknown_error = None
    if request.method == "POST":
        form = Zip2PdfForm(request.POST, request.FILES)
        if form.is_valid():
            project_name = form.cleaned_data.get("project_name")
            zip_file_key = form.cleaned_data.get("zip_file_key")
            form_zip_file = request.FILES.get("zip_file")
            compiler = form.cleaned_data.get("compiler")

            if not zip_file_key.strip():
                zip_file_key = hashlib.md5(form_zip_file.read()).hexdigest()
                print(zip_file_key)

            project, created = LatexProject.objects.get_or_create(
                name=project_name, creator=request.user)
            collection, created = LatexCollection.objects.get_or_create(
                project=project, zip_file_key=zip_file_key)

            pdf_instances = LatexPdf.objects.filter(project=project, collection=collection)

            if not pdf_instances.count():
                working_dir = tempfile.mkdtemp()
                print(working_dir)

                with zipfile.ZipFile(form_zip_file, "r") as zf:
                    zf.extractall(working_dir)

                try:
                    compile_result_dict = unzipped_folder_to_pdf_converter(working_dir, compiler=compiler)
                except Exception as e:
                    from traceback import print_exc
                    print_exc()

                    tp, err, __ = sys.exc_info()
                    error_str = "%s: %s" % (tp.__name__, str(err))
                    if isinstance(e, LatexCompileError):
                        collection.compile_error = error_str
                        with atomic():
                            collection.save()
                    else:
                        unknown_error = ctx["unknown_error"] = error_str
                else:
                    for (filename, filepath) in compile_result_dict.items():
                        with open(filepath, "rb") as f:
                            buff = io.BytesIO(f.read())

                        pdf = InMemoryUploadedFile(
                            file= buff, field_name='file', name=filename,
                            content_type="application/pdf", size=buff.tell(), charset=None)

                        instance = LatexPdf(
                            project=project,
                            collection=collection,
                            name=filename,
                            pdf=pdf,
                        )
                        with atomic():
                            instance.save()
                    pdf_instances = LatexPdf.objects.filter(
                        project=project, collection=collection)
                finally:
                    shutil.rmtree(working_dir)

    else:
        form = Zip2PdfForm()

    ctx["form"] = form
    ctx["form_description"] = _("Convert Zipped LaTeX code to Pdf")

    ctx["collection"] = collection
    ctx["instances"] = pdf_instances

    render_kwargs = {
        "request": request,
        "template_name": "latex/latex_form_page.html",
        "context": ctx
    }

    if collection is not None:
        if collection.compile_error:
            render_kwargs["status"] = status.HTTP_400_BAD_REQUEST

    if unknown_error:
        render_kwargs["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR

    return render(**render_kwargs)
