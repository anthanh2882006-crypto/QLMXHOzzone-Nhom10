"""Giao dịch, chống gửi lặp, nhật ký và tệp cho UC-01, UC-05 đến UC-09.

Mọi lệnh ghi khóa dự án trước khi kiểm tra quyền/trạng thái. Cùng một mã yêu cầu
chỉ trả lại kết quả khi cả người dùng, hành động và nội dung yêu cầu trùng nhau.
"""

from contextlib import contextmanager
import hashlib
import json
import logging
from pathlib import Path
import uuid

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from projectp.models import DinhKem, DuAn, NhatKyNghiepVu, TepTin
from .permissions import project_access

SALT = "ozzone.projects.request.v1"
logger = logging.getLogger(__name__)


def request_token(user, action, project_id=None, target=None):
    return signing.dumps(
        {
            "request": str(uuid.uuid4()),
            "user": user.pk,
            "action": action,
            "project": project_id,
            "target": target,
        },
        salt=SALT,
    )


def normalize(value):
    if hasattr(value, "_meta"):
        return value.pk
    if hasattr(value, "chunks"):
        hasher = hashlib.sha256()
        for chunk in value.chunks():
            hasher.update(chunk)
        value.seek(0)
        return {"name": value.name, "sha256": hasher.hexdigest()}
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items() if key != "request_token"}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def payload_hash(data):
    encoded = json.dumps(normalize(data), sort_keys=True, cls=DjangoJSONEncoder).encode()
    return hashlib.sha256(encoded).hexdigest()


@contextmanager
def command(user, action, token, data, project_id=None, target=None):
    """Khóa, kiểm tra yêu cầu, giữ nhất quán dữ liệu và dọn tệp nếu rollback."""
    try:
        info = signing.loads(token, salt=SALT, max_age=24 * 60 * 60)
    except signing.BadSignature:
        raise ValidationError("Biểu mẫu hết hiệu lực. Tải lại trang để thực hiện.")
    expected = (user.pk, action, project_id, target)
    actual = (info["user"], info["action"], info["project"], info["target"])
    if actual != expected:
        raise ValidationError("Yêu cầu không khớp người dùng hoặc ngữ cảnh đang mở.")
    fingerprint = payload_hash(data)
    created_files = []
    try:
        with transaction.atomic():
            if project_id is None:
                get_user_model().objects.filter(pk=user.pk).update(is_active=F("is_active"))
                project = None
            else:
                DuAn.objects.filter(pk=project_id).update(ngay_cap_nhat=F("ngay_cap_nhat"))
                project, _ = project_access(user, project_id)
            if not get_user_model().objects.filter(pk=user.pk, is_active=True).exists():
                raise PermissionDenied("Tài khoản không còn hoạt động.")
            previous = NhatKyNghiepVu.objects.filter(
                ma_yeu_cau=info["request"], nguoi_dung=user, hanh_dong=action
            ).first()
            result = {
                "project": project,
                "replay": False,
                "result_id": None,
                "files": created_files,
            }
            if previous:
                saved = previous.du_lieu_sau or {}
                if saved.get("request_hash") != fingerprint:
                    raise ValidationError(
                        "Yêu cầu đã được xử lý với nội dung khác. Mở lại biểu mẫu để đối chiếu."
                    )
                result.update(replay=True, result_id=saved["result_id"])
            elif project and project.da_luu_tru:
                raise PermissionDenied("Dự án đã lưu trữ, không nhận nội dung mới.")
            yield result
            if not result["replay"]:
                if result["result_id"] is None:
                    raise ValidationError("Thao tác chưa hoàn tất đầy đủ.")
                if project:
                    DuAn.objects.filter(pk=project.pk).update(ngay_cap_nhat=timezone.now())
                NhatKyNghiepVu.objects.create(
                    nguoi_dung=user,
                    hanh_dong=action,
                    loai_tai_nguyen="DU_AN",
                    ma_tai_nguyen=str(project_id or result["result_id"]),
                    ma_yeu_cau=info["request"],
                    du_lieu_sau={
                        "request_hash": fingerprint,
                        "result_id": result["result_id"],
                        **result.get("audit", {}),
                    },
                )
    except BaseException as exc:
        for storage, path in created_files:
            try:
                storage.delete(path)
            except OSError:
                logger.exception("Không dọn được tệp sau khi hoàn tác giao dịch dự án")
        if isinstance(exc, OSError):
            raise ValidationError(
                "Chưa lưu được tệp minh chứng. Nội dung nhập được giữ, bạn có thể chọn lại tệp và thử lại."
            ) from exc
        raise


def save_model(instance):
    instance.full_clean()
    instance.save()
    return instance


def attach_files(user, files, owner, journal):
    """Lưu minh chứng đã kiểm tra định dạng, gắn đúng đối tượng nghiệp vụ."""
    for upload in files:
        content = upload.read()
        upload.seek(0)
        extension = Path(upload.name).suffix.lower()
        if extension == ".pdf" and content.startswith(b"%PDF-"):
            mime = "application/pdf"
        elif extension in (".jpg", ".jpeg", ".png"):
            from PIL import Image
            from io import BytesIO

            try:
                image = Image.open(BytesIO(content))
                image.verify()
                actual = image.format
            except Exception:
                raise ValidationError("Minh chứng ảnh không hợp lệ.")
            expected = "PNG" if extension == ".png" else "JPEG"
            if actual != expected:
                raise ValidationError("Định dạng ảnh không khớp phần mở rộng.")
            mime = "image/png" if actual == "PNG" else "image/jpeg"
        elif extension == ".txt":
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                raise ValidationError("Tệp TXT cần dùng UTF-8.")
            mime = "text/plain"
        else:
            raise ValidationError("Định dạng minh chứng không hợp lệ.")
        file = TepTin(
            ten_tep=Path(upload.name).name,
            loai_tep=mime,
            kich_thuoc=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            trang_thai="san_sang",
            nguoi_tai_len=user,
        )
        storage = file.tep.storage
        filename = file.tep.field.generate_filename(file, f"projects/{uuid.uuid4().hex}{extension}")
        if storage.exists(filename):
            raise ValidationError("Tên tệp lưu trữ bị trùng. Vui lòng gửi lại để tạo tên mới.")
        # Theo dõi đường dẫn trước khi ghi để dọn được cả tệp viết dở khi kho lưu trữ lỗi.
        journal.append((storage, filename))
        saved_name = storage.save(
            filename, ContentFile(content), max_length=file.tep.field.max_length
        )
        journal[-1] = (storage, saved_name)
        file.tep = saved_name
        save_model(file)
        save_model(DinhKem(tep_tin=file, nguoi_dinh_kem=user, **owner))
