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

import sys

from django.core.exceptions import ImproperlyConfigured
from django.conf import settings
from django.db.models import Q

from rest_framework.parsers import JSONParser, MultiPartParser, ParseError
from rest_framework import generics, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer, MultiPartRenderer

from latex.models import LatexProject, LatexCollection, LatexPdf
from latex.permissions import IsPrivateOrReadOnly
from latex.serializers import (
    LatexProjectSerializer, LatexCollectionSerializer, LatexPdfSerializer)
from latex.converter import (
    unzipped_folder_to_pdf_converter, LatexCompileError,
)


class L2PProjectViewSet(viewsets.ModelViewSet):
    serializer_class = LatexProjectSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly,
                          IsPrivateOrReadOnly]

    def get_queryset(self):
        return LatexProject.objects.filter(Q(creator=self.request.user) | Q(is_private=False))


class L2PCollectionViewSet(viewsets.ModelViewSet):
    serializer_class = LatexCollectionSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly,
                          IsPrivateOrReadOnly]
    parser_classes = (MultiPartParser, JSONParser)

    def get_queryset(self):
        return LatexCollection.objects.filter(Q(project__creator=self.request.user) | Q(project__is_private=False))

    def create(self, request, *args, **kwargs):
        if 'file' not in request.data:
            raise ParseError("Empty content")
        file = request.data["file"]




class L2PCollectionRenderer(JSONRenderer):
    """ If response contains "compile_error", always return 400 """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if renderer_context:
            response = renderer_context['response']
            if isinstance(data, dict):
                compile_error = data.get("compile_error", None)
                if compile_error is not None:
                    response.status_code = status.HTTP_400_BAD_REQUEST
                else:
                    # remove compile_error from data if it's None
                    data.pop("compile_error", None)
        return super().render(data, accepted_media_type, renderer_context)



def get_field_cache_key(zip_file_hash, field_name):
    return "%s:%s" % (zip_file_hash, field_name)


def get_cached_attribute_by_tex_key(zip_file_hash, attr, request):
    try:
        import django.core.cache as cache

        def_cache = cache.caches["default"]
        cache_key = get_field_cache_key(zip_file_hash, attr)
    except ImproperlyConfigured:
        cache_key = None

    result_dict = {}

    if cache_key is not None:
        # def_cache.delete(cache_key)
        ret_value = def_cache.get(cache_key)

        if ret_value is not None:
            # print("Got value in cache!")
            result_dict[attr] = ret_value
            return result_dict

        compile_error_cache_key = get_field_cache_key(zip_file_hash, "compile_error")
        cached_compile_error = def_cache.get(compile_error_cache_key)
        if cached_compile_error is not None:
            return {"compile_error": cached_compile_error}

    # print("Getting value from db")

    # Check db if it exists
    objs = LatexPdf.objects.filter(project__zip_file_hash=zip_file_hash)
    if not objs.count():
        return None if request.method == "POST" else {}

    obj = objs[0]

    serializer = LatexPdfSerializer(obj, fields=attr, context={"request": request})

    data = serializer.to_representation(obj)

    compile_error = data.pop("compile_error", None)
    if compile_error is not None:
        result_dict["compile_error"] = compile_error

        if cache_key is not None:
            compile_error_cache_key = get_field_cache_key(zip_file_hash, "compile_error")
            def_cache.add(compile_error_cache_key, obj.compile_error, None)
        return result_dict

    ret_value = data.get(attr, None)
    if ret_value is None:
        return None if request.method == "POST" else {}

    assert isinstance(ret_value, str)

    # Ignore attribute value with size (byte) over L2P_CACHE_MAX_BYTES
    if (cache_key is not None
            and len(ret_value) <= getattr(settings, "L2P_CACHE_MAX_BYTES", 0)):
        def_cache.add(cache_key, ret_value, None)

    result_dict[attr] = ret_value
    return result_dict


def get_cached_results_from_field_and_tex_key(tex_key, field_str, request):
    """
    This currently deal with single field ('image' or 'data_url') cache
    """
    cached_result = None
    fields = field_str.split(",")
    if len(fields) == 1:
        cached_result = get_cached_attribute_by_tex_key(tex_key, fields[0], request)
    return cached_result


class CreateMixin:
    def create(self, request, *args, **kwargs):
        try:
            req_params = MultiPartParser().parse(request)
            compiler = req_params.pop("compiler")
            tex_source = req_params.pop("tex_source")
            tex_key = req_params.pop("tex_key", None)
            field_str = req_params.pop("fields", None)
        except Exception:
            from traceback import print_exc
            print_exc()
            tp, e, __ = sys.exc_info()
            error = "%s: %s" % (tp.__name__, str(e))
            return Response(
                {"error": error},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if field_str and tex_key:
            cached_result = (
                get_cached_results_from_field_and_tex_key(
                    tex_key, field_str, request))
            if cached_result:
                return Response(cached_result,
                                status=status.HTTP_200_OK)

        data_url = None
        error = None

        try:
            _converter = unzipped_folder_to_pdf_converter(compiler, tex_source, image_format, tex_key, **req_params)
        except Exception as e:
            from traceback import print_exc
            print_exc()
            tp, e, __ = sys.exc_info()
            error = "%s: %s" % (tp.__name__, str(e))
            return Response(
                {"error": error},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        qs = LatexPdf.objects.filter(project__zip_file_hash=_converter.zip_file_hash)
        if qs.count():
            instance = qs[0]
            image_serializer = self.get_serializer(
                instance, fields=field_str)
            return Response(
                image_serializer.data, status=status.HTTP_200_OK)

        try:
            data_url = _converter.get_converted_data_url()
        except Exception as e:
            if isinstance(e, LatexCompileError):
                error = "%s: %s" % (type(e).__name__, str(e))
            else:
                from traceback import print_exc
                print_exc()
                tp, e, __ = sys.exc_info()
                error = "%s: %s" % (tp.__name__, str(e))
                return Response(
                    {"error": error},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        assert not all([data_url is None, error is None])

        data = {"tex_key": _converter.zip_file_hash}
        if data_url is not None:
            data["data_url"] = data_url
        else:
            data["compile_error"] = error

        data["creator"] = self.request.user.pk

        image_serializer = self.get_serializer(data=data)

        if image_serializer.is_valid():
            instance = image_serializer.save()
            return Response(
                self.get_serializer(instance, fields=field_str).data,
                status=status.HTTP_201_CREATED)
        return Response(
            # For example, tex_key already exists.
            image_serializer.errors,
            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LatexImageCreate(
        CreateMixin, generics.CreateAPIView):
    renderer_classes = (L2PCollectionRenderer,)
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LatexPdfSerializer


class FieldsSerializerMixin:
    def get_serializer(self, *args, **kwargs):
        fields = self.request.GET.getlist('fields')
        if fields:
            kwargs["fields"] = fields[0]
        return super().get_serializer(*args, **kwargs)


class LatexImageDetail(
        FieldsSerializerMixin, generics.RetrieveUpdateDestroyAPIView):
    renderer_classes = (L2PCollectionRenderer,)
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LatexPdfSerializer

    lookup_field = "tex_key"

    def get_queryset(self):
        if not self.request.user.is_superuser:
            return LatexPdf.objects.filter(project__creator=self.request.user)
        return LatexPdf.objects.all()

    def get(self, request, *args, **kwargs):
        tex_key = kwargs.get("tex_key")
        assert tex_key is not None
        fields_str = request.GET.getlist('fields')
        if len(fields_str) == 1:
            fields = fields_str[0].split(",")
            if len(fields) == 1:
                cached_result = (
                    get_cached_results_from_field_and_tex_key(
                        tex_key, fields[0], request))
                return Response(
                    data=cached_result,
                    status=status.HTTP_200_OK)
        return super().get(request, *args, **kwargs)


class LatexPdfList(
        CreateMixin, FieldsSerializerMixin, generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LatexPdfSerializer
    renderer_classes = (L2PCollectionRenderer,)

    def get_queryset(self):
        if not self.request.user.is_superuser:
            return LatexPdf.objects.filter(project__creator=self.request.user)
        return LatexPdf.objects.all()
