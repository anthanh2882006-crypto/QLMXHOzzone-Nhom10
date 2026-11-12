"""Ghi hồ sơ cá nhân và kỹ năng cùng giao dịch; dọn ảnh mới nếu ghi thất bại."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import UploadedFile
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from projectp.models import KyNangNhanVien


def save_profile(user, form):
    files = []
    try:
        with transaction.atomic():
            active = (
                get_user_model().objects.filter(pk=user.pk, is_active=True).update(first_name=F("first_name"))
            )
            if not active:
                raise PermissionDenied("Tài khoản không còn hoạt động.")
            user.first_name = form.cleaned_data["first_name"]
            user.last_name = form.cleaned_data["last_name"]
            user.save(update_fields=["first_name", "last_name"])
            image = form.cleaned_data.get("anh_dai_dien")
            if isinstance(image, UploadedFile):
                field_file = form.instance.anh_dai_dien
                storage = field_file.storage
                # Có thể gặp tên ảnh cũ trùng tên; chỉ dọn đường dẫn mới do giao dịch này tạo.
                import uuid
                from pathlib import Path

                filename = field_file.field.generate_filename(
                    form.instance, f"{uuid.uuid4().hex}{Path(image.name).suffix.lower()}"
                )
                files.append((storage, filename))
                image.seek(0)
                stored = storage.save(filename, image, max_length=field_file.field.max_length)
                if stored != filename:
                    files.append((storage, stored))
                form.instance.anh_dai_dien = stored
            form.save()
            selected = {skill.pk for skill in form.cleaned_data["ky_nang"]}
            existing = set(
                KyNangNhanVien.objects.filter(ho_so=form.instance).values_list("ky_nang_id", flat=True)
            )
            KyNangNhanVien.objects.filter(ho_so=form.instance, ky_nang_id__in=existing - selected).delete()
            KyNangNhanVien.objects.bulk_create(
                [KyNangNhanVien(ho_so=form.instance, ky_nang_id=pk) for pk in selected - existing]
            )
    except Exception:
        for storage, filename in files:
            try:
                storage.delete(filename)
            except OSError:
                import logging

                logging.getLogger(__name__).exception("Chưa dọn được ảnh mới sau khi hoàn tác")
        raise
