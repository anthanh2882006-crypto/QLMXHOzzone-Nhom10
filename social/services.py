import hashlib
import uuid
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.text import get_valid_filename

from projectp.models import BaiViet, DinhKem, DuAn, NhatKyNghiepVu, TepTin


def _editable_post(post, user):
    """Khóa cùng phạm vi với Dự án và kiểm tra lại quyền/nguồn trước khi sửa."""
    from .permissions import accessible_posts, can_manage_own_post

    if post.du_an_id:
        DuAn.objects.filter(pk=post.du_an_id).update(ngay_cap_nhat=F("ngay_cap_nhat"))
    BaiViet.objects.filter(pk=post.pk).update(ngay_cap_nhat=F("ngay_cap_nhat"))
    current = BaiViet.objects.select_related("du_an", "cong_dong").get(pk=post.pk)
    allowed, reason = can_manage_own_post(user, current)
    if not allowed or not accessible_posts(user).filter(pk=current.pk).exists():
        raise PermissionDenied(reason or "Bạn không còn quyền truy cập ngữ cảnh bài viết.")
    return current


def _verified_mime(uploaded_file):
    """Nhận diện MIME bằng chữ ký nội dung cơ bản, không tin content_type từ trình duyệt."""
    extension = Path(uploaded_file.name).suffix.lower()
    header = uploaded_file.read(8192)
    uploaded_file.seek(0)

    signatures = {
        ".jpg": (lambda data: data.startswith(b"\xff\xd8\xff"), "image/jpeg"),
        ".jpeg": (lambda data: data.startswith(b"\xff\xd8\xff"), "image/jpeg"),
        ".png": (lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"), "image/png"),
        ".gif": (lambda data: data.startswith((b"GIF87a", b"GIF89a")), "image/gif"),
        ".webp": (
            lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
            "image/webp",
        ),
        ".pdf": (lambda data: data.startswith(b"%PDF-"), "application/pdf"),
        ".doc": (lambda data: data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")), "application/msword"),
        ".xls": (lambda data: data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")), "application/vnd.ms-excel"),
        ".ppt": (
            lambda data: data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")),
            "application/vnd.ms-powerpoint",
        ),
        ".docx": (
            lambda data: data.startswith(b"PK\x03\x04"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ".xlsx": (
            lambda data: data.startswith(b"PK\x03\x04"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        ".pptx": (
            lambda data: data.startswith(b"PK\x03\x04"),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        ".zip": (
            lambda data: data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")),
            "application/zip",
        ),
    }
    if extension in {".txt", ".csv"}:
        try:
            header.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"Tệp {uploaded_file.name} không phải văn bản UTF-8 hợp lệ.") from exc
        if b"\x00" in header:
            raise ValidationError(f"Tệp {uploaded_file.name} chứa byte nhị phân không hợp lệ.")
        return "text/csv" if extension == ".csv" else "text/plain"

    signature = signatures.get(extension)
    if not signature or not signature[0](header):
        raise ValidationError(f"Nội dung tệp {uploaded_file.name} không khớp định dạng phần mở rộng.")
    return signature[1]


def _sha256(uploaded_file):
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()


def _audit(user, action, obj, before=None, after=None, request=None):
    ip = request.META.get("REMOTE_ADDR") if request else None
    audit_key = uuid.uuid4()
    if request and action == "cap_nhat_bai_viet_ca_nhan":
        from .views import _comment_key
        audit_key = _comment_key(request, request.POST.get("request_token", "")) or audit_key
    NhatKyNghiepVu.objects.create(
        nguoi_dung=user,
        hanh_dong=action,
        loai_tai_nguyen="BAI_VIET",
        ma_tai_nguyen=str(obj.pk),
        du_lieu_truoc=before,
        du_lieu_sau=after,
        dia_chi_ip=ip,
        thoi_diem=timezone.now(),
        ma_yeu_cau=audit_key,
    )


def _save_attachments(post, user, files, request=None):
    created_storage_names = []
    try:
        for uploaded in files:
            original_name = get_valid_filename(Path(uploaded.name).name)[:200]
            extension = Path(original_name).suffix.lower()
            mime_type = _verified_mime(uploaded)
            record = TepTin(
                ten_tep=original_name,
                loai_tep=mime_type,
                kich_thuoc=uploaded.size,
                sha256=_sha256(uploaded),
                trang_thai="san_sang",
                nguoi_tai_len=user,
                ngay_tai_len=timezone.now(),
            )
            storage_name = f"social/{uuid.uuid4().hex}{extension}"
            filename = record.tep.field.generate_filename(record, storage_name)
            created_storage_names.append(filename)
            saved_name = record.tep.storage.save(filename, uploaded, max_length=record.tep.field.max_length)
            if saved_name != filename:
                created_storage_names.append(saved_name)
            record.tep.name = saved_name
            record.full_clean()
            record.save()

            attachment = DinhKem(
                tep_tin=record,
                bai_viet=post,
                nguoi_dinh_kem=user,
                mo_ta="",
            )
            attachment.full_clean()
            attachment.save()
        return created_storage_names
    except Exception:
        from django.core.files.storage import default_storage

        for stored_name in created_storage_names:
            try:
                default_storage.delete(stored_name)
            except Exception:
                pass
        raise


def create_company_post(*, user, title, content, files, request=None):
    """Tạo bài cá nhân và các liên kết tệp trong cùng transaction DB.

    Bài cá nhân luôn là Kind.STANDARD, không tạo ThongBaoChinhThuc/recipient set.
    """
    post = None
    created_storage_names = []
    try:
        with transaction.atomic():
            post = BaiViet(
                nguoi_dang=user,
                loai_bai_viet=BaiViet.Kind.STANDARD,
                tieu_de=title.strip(),
                noi_dung=content.strip(),
                trang_thai="hien",
            )
            post.full_clean()
            post.save()
            # Track all stored files, enabling best-effort cleanup if DB transaction fails.
            created_storage_names.extend(_save_attachments(post, user, files, request=request))
            _audit(
                user,
                "tao_bai_viet_ca_nhan",
                post,
                after={"tieu_de": post.tieu_de, "loai_bai_viet": post.loai_bai_viet},
                request=request,
            )
        return post
    except Exception:
        # Database rollback cannot roll back files written to storage.
        for stored_name in created_storage_names:
            try:
                from django.core.files.storage import default_storage

                default_storage.delete(stored_name)
            except Exception:
                pass
        raise


def update_company_post(*, post, user, title, content, files, remove_attachment_ids, request=None):
    created_storage_names = []
    try:
        with transaction.atomic():
            post = _editable_post(post, user)
            if request:
                from .views import _has_session_token
                if not _has_session_token(request, request.POST.get("request_token", "")):
                    raise ValidationError("Yêu cầu chỉnh sửa đã được xử lý hoặc hết hiệu lực.")
            before = {"tieu_de": post.tieu_de, "noi_dung": post.noi_dung}
            post.tieu_de = title.strip()
            post.noi_dung = content.strip()
            post.phien_ban_noi_dung += 1
            post.full_clean()
            post.save(update_fields=["tieu_de", "noi_dung", "phien_ban_noi_dung", "ngay_cap_nhat"])

            if remove_attachment_ids:
                attachments = DinhKem.objects.filter(
                    bai_viet=post,
                    pk__in=[int(value) for value in remove_attachment_ids],
                ).select_related("tep_tin")
                for attachment in attachments:
                    file_record = attachment.tep_tin
                    attachment.delete()  # Gỡ quan hệ, không xóa file vật lý.
                    if not DinhKem.objects.filter(tep_tin=file_record).exists():
                        file_record.da_xoa_mem = True
                        file_record.trang_thai = "da_go"
                        file_record.save(update_fields=["da_xoa_mem", "trang_thai", "ngay_cap_nhat"])

            created_storage_names.extend(_save_attachments(post, user, files, request=request))
            _audit(
                user,
                "cap_nhat_bai_viet_ca_nhan",
                post,
                before=before,
                after={"tieu_de": post.tieu_de, "noi_dung": post.noi_dung},
                request=request,
            )
        return post
    except Exception:
        for stored_name in created_storage_names:
            try:
                from django.core.files.storage import default_storage

                default_storage.delete(stored_name)
            except Exception:
                pass
        raise


def soft_delete_post(*, post, user, request=None):
    with transaction.atomic():
        post = _editable_post(post, user)
        post.da_xoa_mem = True
        post.ngay_xoa = timezone.now()
        post.nguoi_xoa = user
        post.save(update_fields=["da_xoa_mem", "ngay_xoa", "nguoi_xoa", "ngay_cap_nhat"])
        _audit(
            user,
            "xoa_mem_bai_viet_ca_nhan",
            post,
            after={"da_xoa_mem": True},
            request=request,
        )
