from django.contrib import admin
from django import forms
from django.contrib.admin import SimpleListFilter
from django.utils.translation import ugettext_lazy as _

from latex.models import LatexProject, LatexCollection, LatexPdf


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


class LatexProjectAdmin(admin.ModelAdmin):
    pass


admin.site.register(LatexProject, LatexProjectAdmin)


class LatexPdfInline(admin.TabularInline):
    model = LatexPdf
    extra = 0


class LatexCollectionAdmin(admin.ModelAdmin):
    def get_creator(self, obj):
        return obj.project.creator
    get_creator.short_description = _("creator")
    get_creator.admin_order_field = "project__creator__username"

    list_display = (
        "id",
        "project",
        "get_creator",
        "creation_time",
        "zip_file_hash",
    )

    list_filter = (
        "project",
        "project__is_private",
        "project__name",
        "project__identifier"
    )

    search_fields = (
            "zip_file_hash",
            "project__creator__username",
            "project__identifier",
            "project__name",
            )

    inlines = (LatexPdfInline,)


admin.site.register(LatexCollection, LatexCollectionAdmin)
