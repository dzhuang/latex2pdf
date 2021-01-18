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

from django.db import models
from django.core.validators import validate_slug
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _
from django.conf import settings
from django.core.files.storage import get_storage_class
from jsonfield import JSONField


def pdf_upload_to(instance, filename):
    return "l2p_pdf/{0}/{1}/{2}/{3}".format(
        instance.project.creator.id,
        instance.project.name, instance.collection.zip_file_hash, filename)


class OverwriteStorage(get_storage_class()):
    def get_available_name(self, name, max_length=None):
        self.delete(name)
        return name


class LatexProject(models.Model):
    identifier = models.CharField(
        unique=True, db_index=True,
        max_length=200, null=False, blank=False, verbose_name=_("Project identifier"),
        validators=[validate_slug])
    name = models.CharField(
        max_length=200, null=False, blank=False, verbose_name=_("Project name"))
    description = models.TextField(
        null=True, blank=True, verbose_name=_("Project Description"))
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_('Creator'),
        on_delete=models.CASCADE)
    is_private = models.BooleanField(default=True)

    def get_collections_info(self):
        ordered_collections = LatexCollection.objects.filter(
            project=self).order_by("-creation_time")

        count = ordered_collections.count()
        last_revision = None

        if count:
            last_revision = ordered_collections[0].creation_time

        return count, last_revision

    def __str__(self):
        return _('project: "%s" (name: "%s")') % (self.identifier, self.name)

    class Meta:
        verbose_name = _("Project")
        verbose_name_plural = _("Projects")


class LatexCollection(models.Model):
    project = models.ForeignKey(
        LatexProject, verbose_name=_('Project'), on_delete=models.CASCADE)
    zip_file_hash = models.TextField(
        blank=False, verbose_name=_('Zip File Hash'))
    compile_error = models.TextField(
        null=True, blank=True, verbose_name=_('Compile Error'))
    creation_time = models.DateTimeField(
        blank=False, default=now, verbose_name=_('Creation time'))

    class Meta:
        unique_together = (("project", "zip_file_hash"),)
        ordering = ("-creation_time",)

    def __str__(self):
        return _('project: "%s", zip file hash: "%s", created_at %s') % (
            self.project.identifier, self.zip_file_hash, self.creation_time)


class LatexPdf(models.Model):
    project = models.ForeignKey(
        LatexProject, verbose_name=_('Project'), on_delete=models.CASCADE)
    collection = models.ForeignKey(
        LatexCollection, verbose_name=_('Collection'), related_name="entries", on_delete=models.CASCADE)
    name = models.CharField(max_length=200, null=False, blank=False, verbose_name="File name")
    pdf = models.FileField(
        null=True, blank=True, upload_to=pdf_upload_to, storage=OverwriteStorage())
    mediabox = JSONField(null=True, blank=True, verbose_name=_('Media box size, in points'))

    class Meta:
        verbose_name = _("LaTeXPdf")
        verbose_name_plural = _("LaTeXPdfs")

    def is_slide(self):
        # width > height then it is a slide
        if self.mediabox is None:
            return False
        width, height = map(int, self.mediabox[2:])
        return width > height

    def __repr__(self):
        return "<project:%s, filename: %s, creation_time:%s, path:%s>" % (
            self.project.name, self.name, self.collection.creation_time, self.pdf.url)
