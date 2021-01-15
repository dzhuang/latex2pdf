from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from rest_framework.authtoken.models import Token

from latex.models import LatexPdf
from latex.serializers import LatexImageSerializer
from latex.api import get_field_cache_key


@receiver(post_save, sender=get_user_model())
def create_auth_token(sender, instance=None, created=False, **kwargs):
    if created:
        Token.objects.create(user=instance)


@receiver(post_delete, sender=LatexPdf)
def pdf_delete(sender, instance, **kwargs):
    """
    Delete the associated image when the instance is deleted.
    """

    # “false” to instance.image.delete ensures that ImageField
    # does not save the model
    # post_delete signal is sent at the end of a model’s delete()
    # method and a queryset’s delete() method.
    # This is safer as it does not execute unless the parent object
    # is successfully deleted.
    instance.image.delete(False)

    try:
        import django.core.cache as cache
    except ImproperlyConfigured:
        return

    def_cache = cache.caches["default"]

    for attr in ("pdf", "data_url", "compile_error"):
        def_cache.delete(get_field_cache_key(instance.project.zip_file_key, attr))


@receiver(post_save, sender=LatexPdf)
def create_pdf_cache_on_save(sender, instance, **kwargs):
    # We will cache image and data_url
    try:
        import django.core.cache as cache
    except ImproperlyConfigured:
        return

    def_cache = cache.caches["default"]

    from django.conf import settings

    serializer = LatexImageSerializer(instance)
    data = serializer.to_representation(instance)

    attr_to_cache = []

    if (data["pdf"]
            and getattr(settings, "L2P_API_PDF_RETURNS_RELATIVE_PATH", True)):
        # We only cache when image relative path are requested in api
        # because we can't access the request thus no way to know
        # the url and can't build the image url.

        attr_to_cache.append("pdf")

    if getattr(settings, "L2P_CACHE_DATA_URL_ON_SAVE", False):
        attr_to_cache.append("data_url")

    for attr in attr_to_cache:
        attr_value = data[attr]
        if (attr_value is not None
                and len(str(attr_value)) <= getattr(
                    settings, "L2P_CACHE_MAX_BYTES", 0)):
            def_cache.add(
                get_field_cache_key(instance.collection.zip_file_key, attr), attr_value, None)
