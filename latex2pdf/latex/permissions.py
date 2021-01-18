from rest_framework import permissions
from latex.models import LatexProject, LatexCollection


class IsPrivateOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.

        if isinstance(obj, LatexProject):
            creator = obj.creator
            is_private = obj.is_private
        else:
            assert isinstance(obj, LatexCollection)
            creator = obj.project.creator
            is_private = obj.project.is_private

        if request.method in permissions.SAFE_METHODS:
            return True and not is_private

        # Write permissions are only allowed to the owner of the snippet.
        return creator == request.user
