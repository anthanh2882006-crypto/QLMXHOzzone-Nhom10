"""Các hàm giao diện dùng chung để nối 10 use case của app projects."""

from django.urls import NoReverseMatch, reverse


def related_url(name, **kwargs):
    """Chỉ đưa liên kết lên giao diện khi chức năng đích đã được tích hợp."""
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        return None
