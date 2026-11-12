"""Trả ảnh hồ sơ và tệp cộng đồng sau khi kiểm tra quyền của phiên hiện hành."""

from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from communities.views import la_quan_tri_noi_dung, tu_cach
from projectp.models import DinhKem, HoSoNhanVien, TepTin
from social.permissions import accessible_posts


@login_required
@require_GET
def media_file(request, path):
    if HoSoNhanVien.objects.filter(anh_dai_dien=path, nguoi_dung__is_active=True).exists():
        storage, filename, download_name = default_storage, path, None
    else:
        file = get_object_or_404(TepTin, tep=path, trang_thai="san_sang", da_xoa_mem=False)
        attachments = DinhKem.objects.filter(tep_tin=file, bai_viet__da_xoa_mem=False)
        allowed = attachments.filter(bai_viet_id__in=accessible_posts(request.user)).exists()
        if not allowed:
            for attachment in attachments.filter(
                bai_viet__du_an__isnull=True, bai_viet__cong_dong__da_xoa_mem=False,
                bai_viet__cong_dong__loai_cong_dong="chung",
            ).select_related("bai_viet__cong_dong"):
                if la_quan_tri_noi_dung(tu_cach(request.user, attachment.bai_viet.cong_dong)):
                    allowed = True
                    break
        if not allowed:
            raise Http404("Tệp không khả dụng trong phạm vi được phép đọc.")
        storage, filename, download_name = file.tep.storage, file.tep.name, Path(file.ten_tep).name
    try:
        handle = storage.open(filename, "rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404("Tệp chưa có trong kho lưu trữ.")
    return FileResponse(handle, as_attachment=download_name is not None, filename=download_name)
