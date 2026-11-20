"""Cổng đăng nhập cho các trang Dự án, dùng phiên và tài khoản Django hiện có."""

from accounts.views import logout_view
from django.shortcuts import redirect
from django.urls import reverse
from urllib.parse import urlencode


def project_login(request):
    target = request.GET.get("next") or reverse("projects:list")
    return redirect(reverse("accounts:login") + "?" + urlencode({"next": target}))

project_logout = logout_view
