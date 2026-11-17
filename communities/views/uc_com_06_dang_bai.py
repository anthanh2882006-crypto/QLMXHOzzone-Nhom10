"""UC-COM-06 Tạo bài đăng cộng đồng — GD-019 Soạn bài đăng.

post_create      : nơi đăng cố định là cộng đồng hiện tại; B3e không có quyền đăng.
luu_tep_dinh_kem : tính SHA-256, lưu TepTin và gắn DinhKem vào bài.
"""

import hashlib
import logging
import uuid
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from ._chung import community_change, handled
from social.services import _verified_mime
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.shortcuts import redirect, render

from projectp.models import BaiViet, DinhKem, TepTin

from ..forms import PostForm
from ._chung import can_doi_mat_khau, du_an_lien_ket, duoc_dang, ghi_nhat_ky, lay_cong_dong, sidebar, tu_cach


logger = logging.getLogger(__name__)


def luu_tep_dinh_kem(request, upload, post, cd, created_files):
    """Lưu tệp theo từng đoạn và gắn vào bài qua DinhKem.
    Tệp sẵn sàng cần có MIME type và mã SHA-256."""
    mime_type = _verified_mime(upload)
    sha = hashlib.sha256()
    for chunk in upload.chunks():
        sha.update(chunk)
    tep = TepTin(
        ten_tep=Path(upload.name).name[:255],
        loai_tep=mime_type,
        kich_thuoc=upload.size,
        sha256=sha.hexdigest(),
        trang_thai="san_sang",
        nguoi_tai_len=request.user,
    )
    ten_luu = f"cong_dong/{cd.pk}/{uuid.uuid4().hex}{Path(upload.name).suffix.lower()}"  # tên ngẫu nhiên
    upload.seek(0)
    storage = tep.tep.storage
    filename = tep.tep.field.generate_filename(tep, ten_luu)
    created_files.append((storage, filename))
    saved_filename = storage.save(filename, upload, max_length=tep.tep.field.max_length)
    if saved_filename != filename:
        created_files.append((storage, saved_filename))
    tep.tep.name = saved_filename
    tep.full_clean()
    tep.save()
    DinhKem.objects.create(tep_tin=tep, bai_viet=post, nguoi_dinh_kem=request.user)


@login_required
@can_doi_mat_khau
@handled
def post_create(request, pk):
    """GD-019 Soạn bài đăng — nơi đăng cố định là cộng đồng hiện tại."""
    cd = lay_cong_dong(request.user, pk)
    tv = tu_cach(request.user, cd)
    if not duoc_dang(cd, tv):                                        # B3e
        messages.error(request, "Bạn không có quyền đăng bài trong cộng đồng này.")
        return redirect("communities:detail", pk=pk)

    if request.method == "POST":
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = BaiViet(
                nguoi_dang=request.user,
                cong_dong=cd,
                du_an=du_an_lien_ket(cd),          # bài cộng đồng dự án gắn đúng dự án
                tieu_de=form.cleaned_data["tieu_de"],
                noi_dung=form.cleaned_data["noi_dung"],
            )
            created_files = []
            try:
                # Bài + tệp + nhật ký lưu cùng một giao dịch: lỗi ở bước nào thì không lưu gì cả
                with community_change(request.user, pk) as cd:
                    if not duoc_dang(cd, tu_cach(request.user, cd)):
                        raise ValidationError("Quyền đăng đã thay đổi hoặc dự án đã lưu trữ.")
                    post.du_an = du_an_lien_ket(cd)
                    post.full_clean()
                    post.save()
                    if form.cleaned_data["tep"]:
                        luu_tep_dinh_kem(request, form.cleaned_data["tep"], post, cd, created_files)
                    ghi_nhat_ky(request, "tao_bai_cong_dong", "BAI_VIET", post.pk, sau={"cong_dong": cd.pk})
            except (ValidationError, DatabaseError, OSError) as loi:
                for storage, filename in created_files:
                    try:
                        storage.delete(filename)
                    except OSError:
                        logger.exception("Không dọn được tệp khi hoàn tác bài cộng đồng")
                form.add_error(None, loi if isinstance(loi, ValidationError) else
                               "Chưa lưu được bài và tệp. Nội dung được giữ để bạn thử lại.")
            else:
                messages.success(request, "Đã đăng bài trong cộng đồng.")
                return redirect("communities:post", pk=pk, post_id=post.pk)
    else:
        form = PostForm()

    context = {"community": cd, "membership": tv, "form": form}
    context.update(sidebar(request, "community", cd))
    return render(request, "communities/post_form.html", context)
