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

import io
from urllib.parse import urljoin

from django.db import models
from django.core.validators import validate_slug
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.conf import settings
from django.core.files.storage import get_storage_class
from django.utils.html import mark_safe


def pdf_upload_to(instance, filename):
    return "l2p_pdf/{0}/{1}/{2}".format(instance.project.name, instance.collection.zip_file_key, filename)


def convert_data_url_to_file_obj(data_url):
    from binascii import a2b_base64
    return a2b_base64(data_url)


def make_pdf_file(data_url, file_base_name):
    output = io.BytesIO(
        convert_data_url_to_file_obj(data_url[data_url.index("base64,") + 7:]))
    mime_type = data_url[5: data_url.index(";")]
    assert mime_type == "application/pdf"
    ext = ".pdf"

    return InMemoryUploadedFile(
        output, 'file', "%s%s" % (file_base_name, ext),
        mime_type, output.tell(), None)


class OverwriteStorage(get_storage_class()):
    def get_available_name(self, name, max_length=None):
        self.delete(name)
        return name


class LatexProject(models.Model):
    name = models.CharField(
        max_length=200, null=False, blank=False, verbose_name="Project name")
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_('Creator'),
        on_delete=models.CASCADE)
    is_private = models.BooleanField(default=True)

    class Meta:
        unique_together = (("name", "creator"),)


class LatexCollection(models.Model):
    project = models.ForeignKey(
        LatexProject, verbose_name=_('Project'), on_delete=models.CASCADE)
    zip_file_key = models.TextField(
        blank=False, db_index=True, verbose_name=_('Zip File Key'))
    compile_error = models.TextField(
        null=True, blank=True, verbose_name=_('Compile Error'))
    creation_time = models.DateTimeField(
        blank=False, default=now, verbose_name=_('Creation time'))

    class Meta:
        unique_together = (("project", "zip_file_key"),)


class LatexPdf(models.Model):
    project = models.ForeignKey(
        LatexProject, verbose_name=_('Project'), on_delete=models.CASCADE)
    collection = models.ForeignKey(
        LatexCollection, verbose_name=_('Collection'), related_name="entries", on_delete=models.CASCADE)
    name = models.CharField(max_length=200, null=False, blank=False, verbose_name="File name")
    pdf = models.FileField(
        null=True, blank=True, upload_to=pdf_upload_to, storage=OverwriteStorage())
    data_url = models.TextField(null=False, blank=False, verbose_name=_('Data Url'))

    class Meta:
        verbose_name = _("LaTeXPdf")
        verbose_name_plural = _("LaTeXPdfs")

    def save(self, **kwargs):
        # https://stackoverflow.com/a/18803218/3437454
        if self.data_url:
            self.pdf = make_pdf_file(self.data_url, self.name)

        self.full_clean()
        return super().save(**kwargs)

    def __repr__(self):
        if self.data_url:
            return "<project:%s, filename: %s, creation_time:%s, data_url:%s, path:%s>" % (
                self.project, self.name, self.collection.creation_time, self.data_url[:50] + "...", self.pdf.url)
