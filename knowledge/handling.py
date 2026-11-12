from functools import wraps
import logging
from django.db import DatabaseError
from django.shortcuts import render


def database_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except DatabaseError:
            logging.getLogger(__name__).exception("Chưa hoàn tất truy vấn Tri thức")
            return render(request, "knowledge/error.html", {"retry_url": request.get_full_path()}, status=503)

    return wrapped
