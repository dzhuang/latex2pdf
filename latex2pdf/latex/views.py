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
import hashlib
from pdfrw import PdfReader

from crispy_forms.layout import Submit
from django import forms
from django.contrib.auth.decorators import login_required
from django.db.transaction import atomic
from django.utils.translation import ugettext as _
from django.shortcuts import render, get_object_or_404
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.views.generic import ListView, CreateView, DeleteView, DetailView
from django.http import Http404
from django.urls import reverse, reverse_lazy
from rest_framework import status

from latex.converter import (
    unzipped_folder_to_pdf_converter,
    LatexCompileError,
    LATEXMKRC
)
from latex.models import LatexProject, LatexCollection, LatexPdf
from latex.utils import StyledFormMixin, get_codemirror_widget


class ProjectListView(ListView):
    model = LatexProject


class ProjectCreateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LatexProject
        fields = ["identifier", "name", "description", "is_private"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper.form_class = "form-horizontal"
        self.helper.add_input(Submit('submit', 'Submit'))


class ProjectCreateView(CreateView):
    form_class = ProjectCreateForm
    model = LatexProject
    template_name = "generic_form_page.html"

    def form_valid(self, form):
        self.object = form.save(False)
        self.object.creator = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super(ProjectCreateView, self).get_context_data(**kwargs)
        context["form_description"] = _("Create Project")
        return context

    def get_success_url(self):
        return reverse_lazy("update_project", kwargs={"project_identifier": self.object.identifier})


class ProjectDeleteView(DeleteView):
    model = LatexProject
    success_url = reverse_lazy('home')
    # template_name = "generic_form_page.html"

    # def get_queryset(self):
    #     owner = self.request.user
    #     return self.model.objects.filter(creator=owner)

    # def get_context_data(self, **kwargs):
    #     context = super(ProjectDeleteView, self).get_context_data(**kwargs)
    #     context["form_description"] = _("Delete Project")
    #     print(context.get("form"))
    #     return context


class CollectionCreateForm(StyledFormMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["zip_file"] = forms.FileField(
            label=_("Zip File"), required=False,
            help_text=_("Optional. If upload a zip file, it must contain "
                        "a .latexmkrc file to with @default_files and "
                        "compiler configured. Other options, except 'zip_file_hash'"
                        "in this form will be neglected."))

        self.fields["zip_file_hash"] = forms.CharField(
            required=False,
            help_text=_("Optional. An unique string act as the identifier "
                        "of the LaTeX code. If not specified, it will be "
                        "generated automatically."))

        self.fields["compiler"] = forms.ChoiceField(
            choices=tuple((c, c) for c in ["xelatex", "pdflatex"]),
            initial=("xelatex", "xelatex"),
            label=_("Compiler"),
            required=True)

        self.helper.form_class = "form-horizontal"

        self.helper.add_input(
                Submit("convert", _("Convert")))

    def clean(self):
        super().clean()

        zip_file = self.cleaned_data.get('zip_file', None)

        if not any([zip_file,
                    self.cleaned_data.get("latex_code", None)]):
            raise forms.ValidationError(
                _("Either 'Zip File' or 'Tex Code' must be filled.")
            )

        if zip_file is not None:
            from django.template.defaultfilters import filesizeformat

            if zip_file.size > self.txt_max_file_size:
                raise forms.ValidationError(
                    _("Please keep file size under %(allowedsize)s. "
                      "Current filesize is %(uploadedsize)s.")
                    % {'allowedsize': filesizeformat(self.txt_max_file_size),
                       'uploadedsize': filesizeformat(zip_file.size)})

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


def view_collection(request, project_identifier, zip_file_hash=None):
    if request.method == "POST":
        raise PermissionDenied("Not allow to post")

    project = get_object_or_404(LatexProject, identifier=project_identifier)

    if project.is_private and request.user != project.creator:
        raise PermissionDenied("Not allow to view project")

    collections = LatexCollection.objects.filter(project=project)
    pdf_instances = None

    collection = None

    if collections.count():
        if zip_file_hash is not None:
            collections = collections.filter(zip_file_hash=zip_file_hash)
            if collections.count():
                collection = collections[0]
            else:
                raise Http404()
        else:
            collection = collections.order_by("-creation_time")[0]

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
def update_project(request, project_identifier):
    pdf_instances = None
    collection = None
    ctx = {}
    unknown_error = None
    if request.method == "POST":
        form = CollectionCreateForm(request.POST, request.FILES)
        if form.is_valid():
            zip_file_hash = form.cleaned_data.get("zip_file_hash")
            form_zip_file = request.FILES.get("zip_file")
            compiler = form.cleaned_data["compiler"]

            if not zip_file_hash.strip():
                _md5 = hashlib.md5(form_zip_file.read()).hexdigest()
                zip_file_hash = "%s_%s" % (_md5, compiler)

            project, created = LatexProject.objects.get_or_create(
                identifier=project_identifier, creator=request.user)

            collection_qset = LatexCollection.objects.filter(
                project=project, zip_file_hash=zip_file_hash)

            collection = None
            pdf_instances = None

            if collection_qset.count():
                assert collection_qset.count() == 1
                collection = collection_qset[0]
                pdf_instances = LatexPdf.objects.filter(project=project, collection=collection)

            if collection is None:
                collection = LatexCollection(project=project, zip_file_hash=zip_file_hash)
                working_dir = tempfile.mkdtemp()
                with zipfile.ZipFile(form_zip_file, "r") as zf:
                    zf.extractall(working_dir)

                try:
                    compiled_pdf_dict = unzipped_folder_to_pdf_converter(working_dir, compiler=compiler)
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
                    for (filename, filepath) in compiled_pdf_dict.items():
                        with open(filepath, "rb") as f:
                            buff = io.BytesIO(f.read())

                        pdf = InMemoryUploadedFile(
                            file=buff, field_name='file', name=filename,
                            content_type="application/pdf", size=buff.tell(), charset=None)

                        reader = PdfReader(filepath)
                        mediabox = reader.getPage(0).MediaBox

                        pdf = LatexPdf(
                            project=project,
                            collection=collection,
                            name=filename,
                            pdf=pdf,
                            mediabox=mediabox
                        )
                        with atomic():
                            pdf.save()
                    pdf_instances = LatexPdf.objects.filter(
                        project=project, collection=collection)
                finally:
                    shutil.rmtree(working_dir)

    else:
        form = CollectionCreateForm()

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
