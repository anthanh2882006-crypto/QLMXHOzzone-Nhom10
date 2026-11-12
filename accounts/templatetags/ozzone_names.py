"""Hiển thị họ tên thống nhất theo hàm dùng chung của Tài khoản."""
from django import template
from accounts.views._chung import ho_ten as format_name

register = template.Library()


@register.filter
def ho_ten(user):
    return format_name(user) if user else ""
