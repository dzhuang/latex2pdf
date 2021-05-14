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

from crispy_forms.layout import Submit
from django import forms
from django.contrib.auth.decorators import login_required
from django.db.transaction import atomic
from django.utils.translation import ugettext as _
from django.shortcuts import render, get_object_or_404
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.views.generic import ListView, CreateView, DeleteView, DetailView
from django.views.generic.edit import ModelFormMixin
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


UPLOAD_FILE_MAX_BYTES = 64 * 1024 ** 2


class ProjectListView(ListView):
    model = LatexProject
    template_name = "latex/project_list.html"

    def get_queryset(self):
        self.public_projects = self.model.objects.filter(is_private=False)
        self.my_project = None
        owner = self.request.user
        if owner.is_authenticated:
            self.my_project = self.model.objects.filter(creator=owner)
        return self.model.objects.all().order_by("-creation_time")

    def get_context_data(self, **kwargs):
        context = super(ProjectListView, self).get_context_data(**kwargs)
        context["public_project"] = self.public_projects
        context["my_project"] = self.my_project
        return context


class ProjectCreateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LatexProject
        fields = ["identifier", "name", "description", "is_private"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper.form_class = "form-horizontal"
        self.helper.add_input(Submit('submit', _('Submit')))


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
        return reverse_lazy(
            "project-compile", kwargs={"project_identifier": self.object.identifier})


class ProjectDeleteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LatexProject
        fields = ["identifier"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["identifier"].widget = forms.HiddenInput()
        self.helper.add_input(Submit('submit', _('Confirm'), css_class="btn-danger"))


class ProjectDeleteView(ModelFormMixin, DeleteView):
    model = LatexProject
    success_url = reverse_lazy('project-list')
    template_name = "generic_form_page.html"
    form_class = ProjectDeleteForm

    def get_queryset(self):
        owner = self.request.user
        if not owner.is_authenticated:
            return self.model.objects.filter(is_private=False)
        return self.model.objects.filter(creator=owner)

    def get_context_data(self, **kwargs):
        context = super(ProjectDeleteView, self).get_context_data(**kwargs)
        context["form_description"] = _('Are you sure you want to delete project "%s"?' % self.object.identifier)
        return context


class CollectionCreateForm(StyledFormMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["zip_file"] = forms.FileField(
            label=_("Zip File"), required=True,
            help_text=_("A zip file is required, it must contain "
                        "a .latexmkrc file with @default_files and "
                        "compiler configured."))

        self.fields["compiler"] = forms.ChoiceField(
            choices=tuple((c, c) for c in ["xelatex", "pdflatex"]),
            initial=("xelatex", "xelatex"),
            label=_("Compiler"),
            required=True)

        self.helper.form_class = "form-horizontal"

        self.helper.add_input(
                Submit("submit", _("Compile")))

    def clean(self):
        super().clean()

        zip_file = self.cleaned_data.get('zip_file', None)
        from django.template.defaultfilters import filesizeformat

        if zip_file.size > UPLOAD_FILE_MAX_BYTES:
            raise forms.ValidationError(
                _("Please keep file size under %(allowedsize)s. "
                  "Current filesize is %(uploadedsize)s.")
                % {'allowedsize': filesizeformat(UPLOAD_FILE_MAX_BYTES),
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

        return self.cleaned_data


def view_collection(request, project_identifier, zip_file_hash=None):
    if request.method == "POST":
        raise PermissionDenied("Not allow to post")

    is_viewing_old_version = zip_file_hash is not None

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
           "pdfs": pdf_instances,
           "is_viewing_old_version": is_viewing_old_version
           }

    render_kwargs = {
        "request": request,
        "template_name": "latex/project_detail.html",
        "context": ctx
    }

    if collection is not None:
        if collection.compile_error:
            render_kwargs["status"] = status.HTTP_400_BAD_REQUEST

    return render(**render_kwargs)


def get_pdf_mediabox(filepath):
    import fitz
    doc = fitz.open(filepath)
    page = doc.loadPage(0)
    return list(page.MediaBox)


@login_required(login_url='/login/')
def compile_project(request, project_identifier):
    pdf_instances = None
    collection = None
    ctx = {}
    unknown_error = None
    if request.method == "POST":
        form = CollectionCreateForm(request.POST, request.FILES)
        if form.is_valid():
            form_zip_file = request.FILES.get("zip_file")
            compiler = form.cleaned_data["compiler"]

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
                print(working_dir)
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
                    with atomic():
                        collection.save()
                    for (filename, filepath) in compiled_pdf_dict.items():
                        with open(filepath, "rb") as f:
                            buff = io.BytesIO(f.read())

                        pdf = InMemoryUploadedFile(
                            file=buff, field_name='file', name=filename,
                            content_type="application/pdf", size=buff.tell(), charset=None)

                        mediabox = get_pdf_mediabox(filepath)
                        print(mediabox)

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

    ctx["pdfs"] = pdf_instances

    render_kwargs = {
        "request": request,
        "template_name": "latex/project_update.html",
        "context": ctx
    }

    if collection is not None:
        if collection.compile_error:
            render_kwargs["status"] = status.HTTP_400_BAD_REQUEST

    if unknown_error:
        render_kwargs["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR

    return render(**render_kwargs)
