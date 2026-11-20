"""Phản hồi khi truy vấn bảng tin hoặc nội dung chưa hoàn tất."""

from functools import wraps
import logging

from django.db import DatabaseError
from django.shortcuts import render
from django.urls import reverse


def database_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except DatabaseError:
            logging.getLogger(__name__).exception("Chưa hoàn tất thao tác Mạng xã hội")
            retry_url = request.get_full_path()
            if request.method != "GET" and request.resolver_match:
                name = request.resolver_match.url_name
                if name in {"comment_create", "reaction_set", "save_set"}:
                    retry_url = reverse("social:post_detail", args=[kwargs["pk"]])
                elif name == "delete":
                    retry_url = reverse("social:my_posts")
            return render(request, "social/load_error.html", {
                "retry_url": retry_url,
                "is_write": request.method != "GET",
            }, status=503)

    return wrapped
