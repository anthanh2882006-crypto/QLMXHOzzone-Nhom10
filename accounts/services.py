"""Ghi hồ sơ cá nhân và kỹ năng cùng giao dịch; dọn ảnh mới nếu ghi thất bại."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import UploadedFile
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from projectp.models import (
    CommunityRole, CongDong, DuAn, KyNangNhanVien, MemberStatus, ProjectRole,
    ThanhVienCongDong, ThanhVienDuAn,
)


def check_deactivation(user_id):
    active = Q(trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True, nguoi_dung__is_active=True)
    project_members = ThanhVienDuAn.objects.filter(active)
    active_managers = project_members.filter(vai_tro=ProjectRole.MANAGER, du_an__cong_dong__da_xoa_mem=False)
    active_managers = active_managers.exclude(du_an__trang_thai=DuAn.Status.ARCHIVED)
    project_membership = project_members.filter(
        du_an__cong_dong_id=OuterRef("cong_dong_id"), nguoi_dung_id=OuterRef("nguoi_dung_id"),
    )
    active_owners = (
        ThanhVienCongDong.objects.filter(active, vai_tro=CommunityRole.OWNER, cong_dong__da_xoa_mem=False)
        .filter(Q(cong_dong__loai_cong_dong=CongDong.Type.GENERAL) | Exists(project_membership))
        .exclude(cong_dong__du_an_lien_ket__trang_thai=DuAn.Status.ARCHIVED)
    )

    managed_projects = active_managers.filter(nguoi_dung_id=user_id)
    owned_communities = active_owners.filter(nguoi_dung_id=user_id)
    # Khóa cùng đối tượng mà các luồng bàn giao dùng trước khi kiểm lại vai trò.
    managed_communities = DuAn.objects.filter(cong_dong_id__in=owned_communities.values("cong_dong_id"))
    list(DuAn.objects.filter(
        Q(pk__in=managed_projects.values("du_an_id")) | Q(pk__in=managed_communities.values("pk"))
    ).order_by("pk").select_for_update().values_list("pk", flat=True))
    list(CongDong.objects.filter(pk__in=owned_communities.values("cong_dong_id"))
         .order_by("pk").select_for_update().values_list("pk", flat=True))

    another_manager = active_managers.filter(du_an_id=OuterRef("du_an_id")).exclude(nguoi_dung_id=user_id)
    another_owner = active_owners.filter(cong_dong_id=OuterRef("cong_dong_id")).exclude(nguoi_dung_id=user_id)
    reasons = []
    if managed_projects.filter(~Exists(another_manager)).exists():
        reasons.append("Tài khoản là Quản lý cuối cùng của ít nhất một dự án chưa lưu trữ. Cần bàn giao quản lý trước khi vô hiệu hóa.")
    if owned_communities.filter(~Exists(another_owner)).exists():
        reasons.append("Tài khoản là Chủ sở hữu (OWNER) cuối cùng của ít nhất một cộng đồng còn hoạt động. Cần bàn giao OWNER trước khi vô hiệu hóa.")
    if reasons:
        raise ValidationError(reasons)


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
