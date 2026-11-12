"""Liên kết tương tác dùng chung trong khung của từng phân hệ."""
from django import template
from social.navigation import post_navigation as build_navigation

register = template.Library()


@register.simple_tag(takes_context=True)
def post_navigation(context, post):
    return build_navigation(context["request"], post)
