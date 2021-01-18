from rest_framework import serializers
from latex.models import LatexProject, LatexCollection, LatexPdf
from django.conf import settings


class LatexProjectSerializer(serializers.ModelSerializer):

    class Meta:
        model = LatexProject


class LatexCollectionSerializer(serializers.ModelSerializer):

    class Meta:
        model = LatexCollection


class DynamicFieldsModelSerializer(serializers.ModelSerializer):
    """
    A ModelSerializer that takes an additional `fields` argument that
    controls which fields should be displayed.

    https://www.django-rest-framework.org/api-guide/serializers/#example
    """

    def __init__(self, *args, **kwargs):
        # Don't pass the 'fields' arg up to the superclass
        fields = kwargs.pop('fields', None)

        # Instantiate the superclass normally
        super().__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument
            # but we will always include "compile_error"
            allowed = set(fields.split(","))
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)


class LatexPdfSerializer(DynamicFieldsModelSerializer):

    class Meta:
        model = LatexPdf
        fields = ("id", "pdf")

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if not getattr(settings, "L2P_API_PDF_RETURNS_RELATIVE_PATH", True):
            print(representation)
            return representation

        if "pdf" in representation and representation["pdf"] is not None:
            representation['pdf'] = str(instance.pdf)
        return representation
