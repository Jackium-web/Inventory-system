from django.conf import settings
from django.shortcuts import redirect


class InventoryLoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._requires_login(request) and not request.user.is_authenticated:
            login_url = f"{settings.LOGIN_URL}?next={request.get_full_path()}"
            return redirect(login_url)

        return self.get_response(request)

    @staticmethod
    def _requires_login(request):
        path = request.path
        return not (
            path.startswith("/login/")
            or path.startswith("/admin-login/")
            or path.startswith("/admin/")
            or path.startswith(settings.MEDIA_URL)
            or path.startswith(
                "/" + settings.STATIC_URL.lstrip("/")
            )
        )