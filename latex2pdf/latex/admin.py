from django.contrib import admin
from django import forms
from django.contrib.admin import SimpleListFilter
from django.utils.translation import ugettext_lazy as _

from latex.models import LatexPdf


class LatexImageAdminForm(forms.ModelForm):
    class Meta:
        model = LatexPdf
        exclude = ()


class HasCompileErrorFilter(SimpleListFilter):
    title = _('has compile error')
    parameter_name = 'has_compile_error'

    def lookups(self, request, model_admin):
        return(
            ('y', _('Yes')),
            ('n', _('No')))

    def queryset(self, request, queryset):
        if self.value() is not None:
            return queryset.filter(compile_error__isnull=bool(self.value() == "n"))
        return queryset


# class LatexPdfAdmin(admin.ModelAdmin):
#     _readonly_fields = ["data_url", "compile_error"]
#     list_display = (
#             "id",
#     )
#     list_filter = ("creation_time", "creator", HasCompileErrorFilter)
#     search_fields = (
#             "zip_file_key",
#             "pdf",
#             "compile_error")
#
#     form = LatexImageAdminForm
#     save_on_top = True
#
#     def get_form(self, *args, **kwargs):
#         form = super(LatexPdfAdmin, self).get_form(*args, **kwargs)
#
#         for field_name in self._readonly_fields:
#             form.base_fields[field_name].disabled = True
#
#         return form


# admin.site.register(LatexPdf, LatexPdfAdmin)
