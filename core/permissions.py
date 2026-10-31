from django.core.exceptions import PermissionDenied
from functools import wraps
OWNER = 'Owner'
OPERATOR = 'Admin Operasional'
def is_owner(user):
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name=OWNER).exists())
def is_operator(user):
    return user.is_authenticated and user.groups.filter(name=OPERATOR).exists()
def require_access(user):
    if not (is_owner(user) or is_operator(user)):
        raise PermissionDenied('Akun belum memiliki akses KMS.')
def owner_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_owner(request.user):
            raise PermissionDenied('Fitur ini hanya untuk Owner / Super Admin.')
        return view(request, *args, **kwargs)
    return wrapped
def context(request):
    return {'is_owner': is_owner(request.user)}
