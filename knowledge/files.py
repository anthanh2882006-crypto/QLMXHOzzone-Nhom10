"""Tải tệp tri thức sau khi kiểm tra lại quyền đối với nội dung chứa tệp."""

from pathlib import Path
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from projectp.models import DinhKem, NguonThamKhao
from .services import can_edit, check_scope


def can_read_version(user, version):
    from .views import _knowledge_sources_for

    if _knowledge_sources_for(user)["articles"].filter(phien_ban_dang_cong_bo=version).exists():
        return True
    if version.trang_thai == "ban_nhap" and can_edit(user, version.bai_viet_tri_thuc):
        check_scope(user, version)
        return True
    return False


def can_read_reference_file(user, reference):
    """Quyền bài tri thức và quyền tệp nguồn được xét tại thời điểm truy cập."""
    file = reference.tep_nguon
    if not file or file.da_xoa_mem or file.trang_thai != "san_sang":
        return False
    try:
        if not can_read_version(user, reference.phien_ban):
            return False
    except PermissionDenied:
        return False
    attachments = DinhKem.objects.filter(tep_tin=file)
    if not attachments.exists():
        # Tệp cung cấp trực tiếp làm nguồn của phiên bản, chưa gắn nguồn khác.
        return True
    from social.permissions import accessible_posts
    from .views import _knowledge_sources_for

    posts = accessible_posts(user).values("pk")
    if attachments.filter(
        Q(bai_viet_id__in=posts)
        | Q(binh_luan__bai_viet_id__in=posts, binh_luan__da_xoa_mem=False)
        | Q(phuong_an__bai_viet_id__in=posts)
        | Q(ket_qua_thu__lan_thu__phuong_an__bai_viet_id__in=posts)
    ).exists():
        return True
    sources = _knowledge_sources_for(user)
    if attachments.filter(
        Q(bai_hoc_id__in=sources["lessons"].values("pk"))
        | Q(phien_ban_tri_thuc_id__in=sources["articles"].values("phien_ban_dang_cong_bo_id"))
    ).exists():
        return True
    for attachment in attachments.filter(
        phien_ban_tri_thuc__trang_thai="ban_nhap",
    ).select_related("phien_ban_tri_thuc__bai_viet_tri_thuc"):
        try:
            if can_read_version(user, attachment.phien_ban_tri_thuc):
                return True
        except PermissionDenied:
            continue
    return False


@login_required(login_url="accounts:login")
def download(request, attachment_id=None, reference_id=None):
    if reference_id:
        reference = get_object_or_404(
            NguonThamKhao.objects.select_related("phien_ban__bai_viet_tri_thuc", "tep_nguon"),
            pk=reference_id,
            loai_tham_chieu="tep",
        )
        allowed = can_read_reference_file(request.user, reference)
        file = reference.tep_nguon
    else:
        attachment = get_object_or_404(
            DinhKem.objects.select_related("tep_tin", "phien_ban_tri_thuc__bai_viet_tri_thuc"),
            pk=attachment_id,
        )
        file = attachment.tep_tin
        allowed = bool(
            attachment.phien_ban_tri_thuc_id and can_read_version(request.user, attachment.phien_ban_tri_thuc)
        )
        if attachment.bai_hoc_id:
            from .views import _knowledge_sources_for

            allowed = (
                _knowledge_sources_for(request.user)["lessons"].filter(pk=attachment.bai_hoc_id).exists()
            )
    if not allowed or not file or file.da_xoa_mem or file.trang_thai != "san_sang":
        raise Http404("Tệp không còn khả dụng trong phạm vi hiện hành.")
    try:
        handle = file.tep.storage.open(file.tep.name, "rb")
    except (OSError, ValueError):
        raise Http404("Chưa mở được tệp. Nội dung tri thức vẫn được giữ.")
    return FileResponse(handle, as_attachment=True, filename=Path(file.ten_tep).name)
