from functools import wraps

from django.core.exceptions import PermissionDenied

from .models import User


def role_required(*roles: str):
    """View decorator: 403s unless the logged-in user's role is one of `roles`."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated or request.user.role not in roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


admin_required = role_required(User.Role.ADMIN)


class RoleRequiredMixin:
    """CBV mixin: 403s unless the logged-in user's role is in `allowed_roles`."""

    allowed_roles: tuple[str, ...] = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
