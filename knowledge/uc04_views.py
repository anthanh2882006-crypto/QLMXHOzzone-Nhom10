from __future__ import annotations

from accounts.views._chung import ho_ten

import uuid

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import F, Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from projectp.models import (
    BaiHocKinhNghiem,
    ChoDanhGiaTriThuc,
    NhatKyNghiepVu,
    PhanCongTriThuc,
    DuAn,
)

OPEN_STATES = ("cho_danh_gia", "cho_danh_gia_lai")
DONE_STATES = ("khong_tao_bai_hoc", "da_tao_bai_hoc")
QUEUE_LABELS = {
    "cho_danh_gia": "Chờ đánh giá",
    "cho_danh_gia_lai": "Chờ đánh giá lại",
    "khong_tao_bai_hoc": "Không chuyển thành bài học",
    "da_tao_bai_hoc": "Đã chuẩn hóa bài học",
}


def _login_redirect(request: HttpRequest) -> HttpResponse:
    return redirect_to_login(request.get_full_path(), login_url=reverse("accounts:login"))


def _user_name(user) -> str:
    return ho_ten(user)


def _base_review_queue():
    """Business-valid review sources, independent of which curator is logged in."""
    return (
        ChoDanhGiaTriThuc.objects.filter(
            phan_cong__isnull=False,
            phan_cong__ket_thuc_luc__isnull=True,
            phan_cong__ngay_phan_cong__lte=timezone.now(),
            bai_viet_nguon__du_an_id=F("phan_cong__du_an_id"),
            bai_viet_nguon__che_do_xu_ly=True,
            bai_viet_nguon__trang_thai_xu_ly="da_giai_quyet",
            bai_viet_nguon__giai_quyet_luc__isnull=False,
            bai_viet_nguon__giai_quyet_boi__isnull=False,
            bai_viet_nguon__trang_thai="hien",
            bai_viet_nguon__da_xoa_mem=False,
            ket_luan__trang_thai="da_xac_nhan",
            ket_luan__bai_viet_nguon_id=F("bai_viet_nguon_id"),
            ket_luan__ket_qua__thanh_cong=True,
            ket_luan__ket_qua__lan_thu__phuong_an__bai_viet_id=F("bai_viet_nguon_id"),
        )
        .select_related(
            "phan_cong",
            "phan_cong__du_an",
            "phan_cong__nguoi_phu_trach",
            "bai_viet_nguon",
            "bai_viet_nguon__du_an",
            "bai_viet_nguon__ma_the_thiet_bi",
            "bai_viet_nguon__tai_san",
            "ket_luan",
            "ket_luan__nguoi_de_nghi",
            "ket_luan__ket_qua",
            "ket_luan__ket_qua__nguoi_ghi_nhan",
            "ket_luan__ket_qua__lan_thu",
            "ket_luan__ket_qua__lan_thu__phuong_an",
            "nguoi_danh_gia",
            "bai_hoc",
        )
        .order_by(
            "bai_viet_nguon__du_an__ten_du_an",
            "bai_viet_nguon__tieu_de",
            "ma_cho_danh_gia",
        )
    )


def _assignment_scoped_queue(user):
    """Production/normal-user view: only the curator's own active assignments."""
    from projects.permissions import readable_project_posts, readable_projects

    projects = readable_projects(user)
    # Cùng kiểm tra nguồn hiện hành với Dự án, không dùng quyền Admin thay phân công.
    from social.permissions import accessible_posts

    return _base_review_queue().filter(
        phan_cong__nguoi_phu_trach=user,
        phan_cong__du_an__in=projects,
        bai_viet_nguon_id__in=accessible_posts(user).values("pk"),
    )


def _queue_for_user(user):
    return _assignment_scoped_queue(user)


def _get_assigned_queue_item(user, pk, *, lock=False):
    if lock:
        # Khóa dự án trước các bản ghi con, cùng thứ tự với quản lý phân công.
        project_id = (
            ChoDanhGiaTriThuc.objects.filter(pk=pk).values_list("bai_viet_nguon__du_an_id", flat=True).first()
        )
        DuAn.objects.filter(pk=project_id).update(ngay_cap_nhat=F("ngay_cap_nhat"))
    qs = _assignment_scoped_queue(user)
    if lock:
        qs = qs.select_for_update()
    item = qs.filter(pk=pk).first()
    if item is not None:
        return item

    # Hide both missing and out-of-scope queue records.
    raise Http404("Nguồn đánh giá không khả dụng.")


def _source_context(item):
    post = item.bai_viet_nguon
    project = post.du_an
    device = post.ma_the_thiet_bi if post.ma_the_thiet_bi_id else None
    asset = post.tai_san if post.tai_san_id else None
    conclusion = item.ket_luan
    result = conclusion.ket_qua
    trial = result.lan_thu
    plan = trial.phuong_an
    return {
        "source_post": post,
        "project": project,
        "device": device,
        "asset": asset,
        "conclusion": conclusion,
        "result": result,
        "trial": trial,
        "plan": plan,
        "is_archived_project": bool(project and project.trang_thai == "luu_tru"),
    }


def _review_snapshot(item):
    if not item.danh_gia_luc and not item.nguoi_danh_gia_id:
        return None
    return {
        "actor_id": item.nguoi_danh_gia_id,
        "actor": _user_name(item.nguoi_danh_gia) if item.nguoi_danh_gia_id else "Không rõ",
        "time_iso": item.danh_gia_luc.isoformat() if item.danh_gia_luc else "",
        "time_display": (
            timezone.localtime(item.danh_gia_luc).strftime("%d/%m/%Y %H:%M") if item.danh_gia_luc else ""
        ),
        "reason": item.ly_do_danh_gia,
        "outcome": item.ket_luan_danh_gia,
        "status": item.trang_thai,
        "status_label": QUEUE_LABELS.get(item.trang_thai, item.trang_thai),
    }


def _history_entries(item):
    """Build append-only review history from NHAT_KY_NGHIEP_VU."""
    logs = list(
        NhatKyNghiepVu.objects.filter(
            loai_tai_nguyen="CHO_DANH_GIA_TRI_THUC",
            ma_tai_nguyen=str(item.pk),
        )
        .select_related("nguoi_dung")
        .order_by("thoi_diem", "ma_nhat_ky")
    )
    history = []
    seen = set()

    def add_review(snapshot, *, legacy=False):
        if not snapshot:
            return
        key = (
            snapshot.get("time_iso", ""),
            snapshot.get("actor_id"),
            snapshot.get("reason", ""),
            snapshot.get("outcome", ""),
            snapshot.get("status", ""),
        )
        if key in seen:
            return
        seen.add(key)
        history.append({**snapshot, "kind": "review", "legacy": legacy})

    for log in logs:
        before = log.du_lieu_truoc or {}
        after = log.du_lieu_sau or {}
        add_review(before.get("review_snapshot"), legacy=True)
        event = after.get("event")
        if event == "review":
            add_review(after.get("review"))
        elif event == "reopen":
            history.append(
                {
                    "kind": "reopen",
                    "actor": _user_name(log.nguoi_dung) if log.nguoi_dung_id else "Không rõ",
                    "time_display": timezone.localtime(log.thoi_diem).strftime("%d/%m/%Y %H:%M"),
                    "reason": after.get("reason", log.ly_do),
                    "outcome": "Đã mở lại lượt đánh giá",
                    "status_label": "Chờ đánh giá lại",
                    "legacy": False,
                }
            )
    if not history:
        add_review(_review_snapshot(item), legacy=True)
    return history


def _write_audit(request, item, *, action, reason, before_snapshot, after_data):
    NhatKyNghiepVu.objects.create(
        nguoi_dung=request.user,
        hanh_dong=action,
        loai_tai_nguyen="CHO_DANH_GIA_TRI_THUC",
        ma_tai_nguyen=str(item.pk),
        du_lieu_truoc={"review_snapshot": before_snapshot, "status": item.trang_thai},
        du_lieu_sau=after_data,
        ly_do=reason,
        ma_yeu_cau=uuid.uuid4(),
        dia_chi_ip=request.META.get("REMOTE_ADDR") or None,
        thoi_diem=timezone.now(),
    )


def _normalization_context(item, form_data=None, errors=None):
    source = _source_context(item)
    existing_lesson = BaiHocKinhNghiem.objects.filter(
        bai_viet_nguon_id=item.bai_viet_nguon_id
    ).first()  # includes soft-deleted lessons; uniqueness is logical, not visible-only

    if form_data is None:
        post = source["source_post"]
        form_data = {
            "ly_do_danh_gia": item.ly_do_cho or "",
            "ket_luan_danh_gia": source["conclusion"].noi_dung_ket_luan or "",
            "van_de": "\n".join(part for part in (post.tieu_de, post.noi_dung) if part),
            "nguyen_nhan": "",
            "giai_phap": source["plan"].noi_dung_phuong_an or "",
            "ket_qua": source["result"].mo_ta_ket_qua or "",
            "pham_vi_ap_dung": "",
            "pham_vi_chia_se": "du_an",
            "an_danh_noi_bo": False,
        }
    return {
        "item": item,
        **source,
        "existing_lesson": existing_lesson,
        "form_data": form_data,
        "errors": errors or {},
        "is_re_review": item.trang_thai == "cho_danh_gia_lai",
        "assigned_curator": item.phan_cong.nguoi_phu_trach,
    }


def review_queue(request: HttpRequest) -> HttpResponse:
    """GD-087, nguồn thuộc phân công hiện hành và còn quyền đọc."""
    if not request.user.is_authenticated:
        return _login_redirect(request)

    status_filter = request.GET.get("status", "pending")
    if status_filter not in {"pending", "completed", "all"}:
        status_filter = "pending"
    query = request.GET.get("q", "").strip()

    qs = _queue_for_user(request.user)
    if status_filter == "pending":
        qs = qs.filter(trang_thai__in=OPEN_STATES)
    elif status_filter == "completed":
        qs = qs.filter(trang_thai__in=DONE_STATES)

    if query:
        qs = qs.filter(
            Q(bai_viet_nguon__tieu_de__icontains=query)
            | Q(bai_viet_nguon__noi_dung__icontains=query)
            | Q(bai_viet_nguon__du_an__ten_du_an__icontains=query)
            | Q(bai_viet_nguon__ma_the_thiet_bi__ten_thiet_bi__icontains=query)
            | Q(bai_viet_nguon__ma_the_thiet_bi__ma_thiet_bi__icontains=query)
        )

    rows = []
    for item in qs:
        item.history_entries = _history_entries(item)
        item.has_existing_lesson = BaiHocKinhNghiem.objects.filter(
            bai_viet_nguon_id=item.bai_viet_nguon_id
        ).exists()
        item.is_archived_project = item.bai_viet_nguon.du_an.trang_thai == "luu_tru"
        rows.append(item)

    active_assignment_count = PhanCongTriThuc.objects.filter(
        nguoi_phu_trach=request.user,
        ket_thuc_luc__isnull=True,
        ngay_phan_cong__lte=timezone.now(),
    ).count()

    return render(
        request,
        "knowledge/review_queue.html",
        {
            "items": rows,
            "query": query,
            "status_filter": status_filter,
            "status_options": [
                ("pending", "Nguồn chờ đánh giá"),
                ("completed", "Đã hoàn tất đánh giá"),
                ("all", "Tất cả"),
            ],
            "result_count": len(rows),
            "active_assignment_count": active_assignment_count,
        },
    )


def normalize_lesson(request: HttpRequest, pk: int) -> HttpResponse:
    """GD-088, chuẩn hóa đúng nguồn theo phân công của người thao tác."""
    if not request.user.is_authenticated:
        return _login_redirect(request)

    item = _get_assigned_queue_item(request.user, pk)

    if item.trang_thai == "khong_tao_bai_hoc":
        messages.info(
            request,
            "Nguồn đã được đánh giá không chuyển thành bài học. Hãy mở lại đánh giá tại GD-087 trước khi tiếp tục.",
        )
        return redirect("knowledge:review_queue")
    if item.trang_thai == "da_tao_bai_hoc":
        messages.info(request, "Nguồn này đã có bài học kinh nghiệm; hệ thống không tạo bài trùng.")
        return redirect("knowledge:review_queue")

    if request.method == "GET":
        return render(
            request,
            "knowledge/normalize_lesson.html",
            _normalization_context(item),
        )

    action = request.POST.get("action", "normalize")
    form_data = {
        "ly_do_danh_gia": request.POST.get("ly_do_danh_gia", "").strip(),
        "ket_luan_danh_gia": request.POST.get("ket_luan_danh_gia", "").strip(),
        "van_de": request.POST.get("van_de", "").strip(),
        "nguyen_nhan": request.POST.get("nguyen_nhan", "").strip(),
        "giai_phap": request.POST.get("giai_phap", "").strip(),
        "ket_qua": request.POST.get("ket_qua", "").strip(),
        "pham_vi_ap_dung": request.POST.get("pham_vi_ap_dung", "").strip(),
        "pham_vi_chia_se": request.POST.get("pham_vi_chia_se", "du_an").strip(),
        "an_danh_noi_bo": request.POST.get("an_danh_noi_bo") in {"1", "on", "yes", "true"},
    }

    errors = {}
    for field in ("ly_do_danh_gia", "ket_luan_danh_gia"):
        if not form_data[field]:
            errors[field] = "Trường này bắt buộc để lưu lịch sử đánh giá."

    if action == "normalize":
        for field in ("van_de", "nguyen_nhan", "giai_phap", "ket_qua", "pham_vi_ap_dung"):
            if not form_data[field]:
                errors[field] = "Không được để trống thành phần này."
        if form_data["pham_vi_chia_se"] not in {"du_an", "noi_bo"}:
            errors["pham_vi_chia_se"] = "Phạm vi chia sẻ không hợp lệ."
        if form_data["pham_vi_chia_se"] == "noi_bo" and not form_data["an_danh_noi_bo"]:
            errors["an_danh_noi_bo"] = (
                "Muốn chia sẻ nội bộ, bạn phải xác nhận đã loại bỏ thông tin nhận diện dự án, thiết bị, tài sản và cá nhân."
            )
    elif action != "no_lesson":
        errors["action"] = "Thao tác không hợp lệ."

    if errors:
        return render(
            request,
            "knowledge/normalize_lesson.html",
            _normalization_context(item, form_data, errors),
            status=400,
        )

    now = timezone.now()
    old_snapshot = _review_snapshot(item)

    try:
        with transaction.atomic():
            locked = _get_assigned_queue_item(request.user, pk, lock=True)
            old_snapshot = _review_snapshot(locked)
            if locked.trang_thai not in OPEN_STATES:
                raise ValidationError("Lượt đánh giá không còn ở trạng thái chờ xử lý.")
            if BaiHocKinhNghiem.objects.filter(bai_viet_nguon_id=locked.bai_viet_nguon_id).exists():
                raise ValidationError(
                    "Nguồn đã có một bài học logic, kể cả bài học đã xóa mềm. Không tạo thêm bài học mới."
                )

            source = locked.bai_viet_nguon
            if not (
                source.che_do_xu_ly
                and source.trang_thai_xu_ly == "da_giai_quyet"
                and source.trang_thai == "hien"
                and not source.da_xoa_mem
                and source.du_an_id == locked.phan_cong.du_an_id
                and source.giai_quyet_luc
                and source.giai_quyet_boi_id
                and locked.ket_luan.trang_thai == "da_xac_nhan"
                and locked.ket_luan.bai_viet_nguon_id == source.pk
                and locked.ket_luan.ket_qua.thanh_cong
                and locked.ket_luan.ket_qua.lan_thu.phuong_an.bai_viet_id == source.pk
            ):
                raise ValidationError("Nguồn không còn đủ điều kiện hoặc quyền đọc để đánh giá tri thức.")

            assignment = locked.phan_cong
            if assignment.ket_thuc_luc is not None or assignment.ngay_phan_cong > now:
                raise ValidationError("Phân công tri thức không còn hiệu lực.")
            if assignment.nguoi_phu_trach_id != request.user.pk:
                raise ValidationError("Bạn không phải người phụ trách tri thức của nguồn này.")

            locked.nguoi_danh_gia = request.user
            locked.danh_gia_luc = now
            locked.ly_do_danh_gia = form_data["ly_do_danh_gia"]
            locked.ket_luan_danh_gia = form_data["ket_luan_danh_gia"]

            if action == "no_lesson":
                locked.trang_thai = "khong_tao_bai_hoc"
                locked.bai_hoc = None
                locked.full_clean()
                locked.save(
                    update_fields=[
                        "trang_thai",
                        "nguoi_danh_gia",
                        "danh_gia_luc",
                        "ly_do_danh_gia",
                        "ket_luan_danh_gia",
                        "ngay_cap_nhat",
                    ]
                )
                review = {
                    "actor_id": request.user.pk,
                    "actor": _user_name(request.user),
                    "time_iso": now.isoformat(),
                    "time_display": timezone.localtime(now).strftime("%d/%m/%Y %H:%M"),
                    "reason": form_data["ly_do_danh_gia"],
                    "outcome": form_data["ket_luan_danh_gia"],
                    "status": "khong_tao_bai_hoc",
                    "status_label": QUEUE_LABELS["khong_tao_bai_hoc"],
                }
                _write_audit(
                    request,
                    locked,
                    action="khong_chuyen_thanh_bai_hoc",
                    reason=form_data["ly_do_danh_gia"],
                    before_snapshot=old_snapshot,
                    after_data={"event": "review", "review": review},
                )
                messages.success(
                    request,
                    "Đã ghi nhận: Không chuyển thành bài học kinh nghiệm. Kết luận xử lý kỹ thuật được giữ nguyên.",
                )
            else:
                title = form_data["van_de"].splitlines()[0][:250]
                publication_note = ""
                if form_data["pham_vi_chia_se"] == "noi_bo":
                    publication_note = (
                        "Người chuẩn hóa xác nhận đã loại bỏ thông tin nhận diện dự án, thiết bị, "
                        "tài sản và cá nhân trước khi chia sẻ nội bộ."
                    )

                lesson = BaiHocKinhNghiem(
                    bai_viet_nguon=source,
                    ket_luan=locked.ket_luan,
                    phan_cong=locked.phan_cong,
                    nguoi_tao=request.user,
                    tieu_de=title,
                    van_de=form_data["van_de"],
                    nguyen_nhan=form_data["nguyen_nhan"],
                    giai_phap=form_data["giai_phap"],
                    ket_qua=form_data["ket_qua"],
                    pham_vi_ap_dung=form_data["pham_vi_ap_dung"],
                    pham_vi_chia_se=form_data["pham_vi_chia_se"],
                    nguoi_kiem_tra_noi_dung=request.user,
                    ghi_chu_cong_bo=publication_note,
                    kiem_tra_cong_bo_luc=now,
                    ngay_luu_tri_thuc=now,
                    phien_ban_noi_dung=1,
                    trang_thai_quan_tri="hien_thi",
                )
                lesson.full_clean()
                lesson.save(force_insert=True)

                locked.trang_thai = "da_tao_bai_hoc"
                locked.bai_hoc = lesson
                locked.full_clean()
                locked.save(
                    update_fields=[
                        "trang_thai",
                        "bai_hoc",
                        "nguoi_danh_gia",
                        "danh_gia_luc",
                        "ly_do_danh_gia",
                        "ket_luan_danh_gia",
                        "ngay_cap_nhat",
                    ]
                )
                review = {
                    "actor_id": request.user.pk,
                    "actor": _user_name(request.user),
                    "time_iso": now.isoformat(),
                    "time_display": timezone.localtime(now).strftime("%d/%m/%Y %H:%M"),
                    "reason": form_data["ly_do_danh_gia"],
                    "outcome": form_data["ket_luan_danh_gia"],
                    "status": "da_tao_bai_hoc",
                    "status_label": QUEUE_LABELS["da_tao_bai_hoc"],
                    "lesson_id": lesson.pk,
                }
                _write_audit(
                    request,
                    locked,
                    action="chuan_hoa_bai_hoc_kinh_nghiem",
                    reason=form_data["ly_do_danh_gia"],
                    before_snapshot=old_snapshot,
                    after_data={"event": "review", "review": review, "lesson_id": lesson.pk},
                )
                messages.success(request, "Đã chuẩn hóa bài học kinh nghiệm và ghi nhận lịch sử đánh giá.")

    except ValidationError as exc:
        detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        messages.error(request, detail)
        return render(
            request,
            "knowledge/normalize_lesson.html",
            _normalization_context(item, form_data),
            status=400,
        )
    except IntegrityError:
        messages.error(
            request,
            "Nguồn đã được xử lý ở một yêu cầu khác hoặc đã tồn tại bài học logic. Dữ liệu nhập được giữ lại.",
        )
        return render(
            request,
            "knowledge/normalize_lesson.html",
            _normalization_context(item, form_data),
            status=409,
        )

    except DatabaseError:
        messages.error(request, "Chưa lưu được đánh giá. Dữ liệu cũ được giữ, bạn có thể thử lại.")
        return render(
            request, "knowledge/normalize_lesson.html", _normalization_context(item, form_data), status=503
        )

    if action == "normalize":
        return redirect("knowledge:lesson_detail", pk=lesson.pk)
    return redirect(f"{reverse('knowledge:review_queue')}?status=completed")


@require_POST
def reopen_review(request: HttpRequest, pk: int) -> HttpResponse:
    """Mở đánh giá lại, giữ nguyên lịch sử quyết định trước."""
    if not request.user.is_authenticated:
        return _login_redirect(request)

    reason = request.POST.get("reopen_reason", "").strip()
    if not reason:
        messages.error(request, "Cần nhập lý do đánh giá lại.")
        return redirect(f"{reverse('knowledge:review_queue')}?status=completed")

    try:
        with transaction.atomic():
            item = _get_assigned_queue_item(request.user, pk, lock=True)
            if item.trang_thai != "khong_tao_bai_hoc":
                raise ValidationError(
                    "Chỉ nguồn đã được đánh giá Không chuyển thành bài học mới được mở đánh giá lại."
                )
            if BaiHocKinhNghiem.objects.filter(bai_viet_nguon_id=item.bai_viet_nguon_id).exists():
                raise ValidationError(
                    "Nguồn đã có bài học logic, kể cả khi bài học đã xóa mềm. Không thể tạo bài học thứ hai."
                )
            assignment = item.phan_cong
            if assignment.ket_thuc_luc is not None or assignment.ngay_phan_cong > timezone.now():
                raise ValidationError("Phân công tri thức không còn hiệu lực.")
            if assignment.nguoi_phu_trach_id != request.user.pk:
                raise ValidationError("Bạn không phải người phụ trách tri thức của nguồn này.")

            now = timezone.now()
            previous_snapshot = _review_snapshot(item)
            before_status = item.trang_thai
            item.trang_thai = "cho_danh_gia_lai"
            item.full_clean()
            item.save(update_fields=["trang_thai", "ngay_cap_nhat"])
            _write_audit(
                request,
                item,
                action="mo_lai_danh_gia_tri_thuc",
                reason=reason,
                before_snapshot=previous_snapshot,
                after_data={
                    "event": "reopen",
                    "previous_status": before_status,
                    "reason": reason,
                    "actor_id": request.user.pk,
                    "actor": _user_name(request.user),
                    "time_iso": now.isoformat(),
                    "time_display": timezone.localtime(now).strftime("%d/%m/%Y %H:%M"),
                },
            )
            messages.success(request, "Đã mở lại lượt đánh giá. Quyết định trước được giữ trong lịch sử.")
    except ValidationError as exc:
        detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        messages.error(request, detail)
    except DatabaseError:
        messages.error(request, "Không thể mở lại đánh giá do dữ liệu vừa thay đổi. Hãy tải lại danh sách.")

    return redirect(f"{reverse('knowledge:review_queue')}?status=pending")
