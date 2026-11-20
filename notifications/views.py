import uuid
from functools import wraps

from accounts.views._chung import ho_ten

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from projectp.models import (
    BaiViet,
    BaiVietDaLuu,
    DinhKem,
    NguoiNhanThongBao,
    ThongBaoChinhThuc,
)

from .forms import OfficialNoticeForm, initial_from_notice
from .permissions import (
    can_manage_draft, can_publish_notices, can_read_notice, can_track_notice,
    resolve_scope_user_ids,
)
from .services import (
    PREVIEW_SALT, acknowledge_notice, cancel_notice_draft, publication_preview,
    save_and_publish_notice, save_notice_draft,
)


def _notice_read_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except Http404:
            return render(request, "notifications/unavailable.html", status=404)
        except DatabaseError:
            return render(request, "notifications/unavailable.html", {
                "load_failed": True, "retry_url": request.get_full_path(),
            }, status=503)
    return wrapped


def _published_notices_for(user):
    candidates = ThongBaoChinhThuc.objects.filter(
        trang_thai="da_cong_bo",
        bai_viet__da_xoa_mem=False,
        bai_viet__trang_thai="hien",
        bai_viet__loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT,
    ).select_related("bai_viet", "nguoi_phu_trach", "nguoi_xuat_ban", "thong_bao_tham_chieu")
    visible = []
    for notice in candidates:
        notice.can_read_for_request_user = can_read_notice(user, notice)
        notice.can_track_for_request_user = can_track_notice(user, notice)
        # A tracking-only role may see notice metadata and the receipt report, not the body.
        if notice.can_read_for_request_user or notice.can_track_for_request_user:
            visible.append(notice)
    return visible


def _notice_form_context(request, form, *, notice=None, is_edit=False, correction=None):
    attachments = []
    if notice:
        attachments = list(DinhKem.objects.filter(
            bai_viet=notice.bai_viet,
            tep_tin__trang_thai="san_sang",
            tep_tin__da_xoa_mem=False,
        ).select_related("tep_tin"))
    return {
        "form": form,
        "notice": notice,
        "attachments": attachments,
        "is_edit": is_edit,
        "correction": correction or (notice.thong_bao_tham_chieu if notice and notice.thong_bao_tham_chieu_id else None),
        "can_publish": can_publish_notices(request.user),
    }


@login_required(login_url="accounts:login")
@_notice_read_errors
def notice_list(request):
    published = _published_notices_for(request.user)
    drafts = []
    if can_publish_notices(request.user):
        draft_qs = ThongBaoChinhThuc.objects.filter(
            trang_thai="ban_nhap",
            bai_viet__da_xoa_mem=False,
        )
        if not request.user.has_perm("projectp.change_thongbaochinhthuc"):
            draft_qs = draft_qs.filter(nguoi_phu_trach=request.user)
        drafts = list(draft_qs.select_related("bai_viet", "nguoi_phu_trach").order_by("-ngay_cap_nhat"))
    return render(request, "notifications/list.html", {
        "published_notices": published,
        "draft_notices": drafts,
        "can_publish": can_publish_notices(request.user),
    })


@login_required(login_url="accounts:login")
@require_POST
def notice_preview(request):
    if not can_publish_notices(request.user):
        return JsonResponse({"errors": ["Bạn chưa được cấp quyền phát hành thông báo."]}, status=403)
    try:
        notice = None
        draft_id = request.POST.get("draft_id", "")
        if draft_id:
            if not draft_id.isascii() or not draft_id.isdecimal() or len(draft_id) > 18:
                raise Http404
            notice = get_object_or_404(
                ThongBaoChinhThuc.objects.select_related("bai_viet"), pk=int(draft_id),
            )
            if not can_manage_draft(request.user, notice):
                raise PermissionDenied("Bản nháp không còn khả dụng.")
        form = OfficialNoticeForm(request.POST, request.FILES, notice=notice)
        if not form.is_valid():
            return JsonResponse({"errors": list(next(iter(form.errors.values())))}, status=400)
        data = form.cleaned_data
        if not data["tieu_de"]:
            raise ValidationError("Nhập tiêu đề trước khi phát hành.")
        reference = data["thong_bao_tham_chieu"]
        if reference and not can_read_notice(request.user, reference):
            raise PermissionDenied("Thông báo tham chiếu không khả dụng.")
        recipients, fingerprint, filenames = publication_preview(request.user, data, notice)
    except ValidationError as exc:
        return JsonResponse({"errors": exc.messages}, status=400)
    except PermissionDenied as exc:
        return JsonResponse({"errors": [str(exc)]}, status=403)
    except Http404:
        return JsonResponse({"errors": ["Bản nháp không còn khả dụng."]}, status=404)
    except DatabaseError:
        return JsonResponse({"errors": ["Chưa kiểm tra được phạm vi người nhận. Vui lòng thử lại."]}, status=503)
    return JsonResponse({
        "recipient_count": len(recipients), "attachments": filenames,
        "preview_token": signing.dumps(fingerprint, salt=PREVIEW_SALT),
    })


def _submit_notice(request, form, *, notice=None, correction=None):
    status = 400
    if form.is_valid():
        data = form.cleaned_data
        action = request.POST.get("action", "save_draft")
        try:
            if correction and getattr(data["thong_bao_tham_chieu"], "pk", None) != correction.pk:
                raise ValidationError("Thông báo đính chính phải giữ tham chiếu đến thông báo đã chọn.")
            if action == "publish":
                published = save_and_publish_notice(
                    user=request.user, cleaned=data, notice=notice,
                    preview_token=request.POST.get("preview_token", ""), request=request,
                )
                messages.success(request, "Thông báo chính thức đã được phát hành.")
                return redirect("notifications:detail", pk=published.pk)
            if action != "save_draft":
                raise ValidationError("Thao tác không hợp lệ.")
            draft = save_notice_draft(
                user=request.user, cleaned=data, files=data["tep_dinh_kem"], notice=notice, request=request,
            )
            messages.success(request, "Bản nháp thông báo đã được lưu.")
            return redirect("notifications:edit_draft", pk=draft.pk)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        except PermissionDenied as exc:
            form.add_error(None, str(exc))
            status = 403
        except (DatabaseError, OSError):
            form.add_error(None, "Chưa lưu được thông báo. Bản nháp đã lưu vẫn được giữ. Vui lòng thử lại.")
            status = 503
    return render(request, "notifications/form.html", _notice_form_context(
        request, form, notice=notice, is_edit=notice is not None, correction=correction,
    ), status=status)


@login_required(login_url="accounts:login")
def notice_create(request, reference_id=None):
    if not can_publish_notices(request.user):
        raise PermissionDenied("Bạn chưa được cấp quyền phát hành thông báo chính thức.")

    correction = None
    initial = {"publish_key": uuid.uuid4()}
    if reference_id is not None:
        correction = get_object_or_404(
            ThongBaoChinhThuc.objects.select_related("bai_viet"), pk=reference_id, trang_thai="da_cong_bo",
        )
        if not can_read_notice(request.user, correction):
            raise PermissionDenied("Bạn không có quyền xem thông báo được chọn để đính chính.")
        initial.update(initial_from_notice(correction, initial["publish_key"]))
        initial.update(tieu_de=f"Đính chính: {correction.bai_viet.tieu_de}"[:250], thong_bao_tham_chieu=correction.pk)

    if request.method == "POST":
        return _submit_notice(request, OfficialNoticeForm(request.POST, request.FILES), correction=correction)
    return render(request, "notifications/form.html", _notice_form_context(
        request, OfficialNoticeForm(initial=initial), correction=correction,
    ))


@login_required(login_url="accounts:login")
def notice_edit_draft(request, pk):
    notice = get_object_or_404(
        ThongBaoChinhThuc.objects.select_related("bai_viet", "thong_bao_tham_chieu"),
        pk=pk, bai_viet__da_xoa_mem=False,
    )
    if notice.trang_thai == "da_cong_bo" and request.method == "POST" and request.POST.get("action") == "publish":
        if (notice.nguoi_xuat_ban_id == request.user.pk and can_publish_notices(request.user)
                and str(notice.khoa_yeu_cau_xuat_ban) == request.POST.get("publish_key")):
            return redirect("notifications:detail", pk=notice.pk)
    if not can_manage_draft(request.user, notice):
        raise PermissionDenied("Bạn không được biên tập thông báo này.")
    if request.method == "POST":
        return _submit_notice(request, OfficialNoticeForm(request.POST, request.FILES, notice=notice), notice=notice)

    form = OfficialNoticeForm(initial=initial_from_notice(notice, uuid.uuid4()), notice=notice)
    return render(request, "notifications/form.html", _notice_form_context(request, form, notice=notice, is_edit=True))


@login_required(login_url="accounts:login")
@require_POST
def notice_cancel_draft(request, pk):
    notice = get_object_or_404(ThongBaoChinhThuc.objects.select_related("bai_viet"), pk=pk)
    cancel_notice_draft(notice=notice, user=request.user, request=request)
    messages.success(request, "Bản nháp đã được hủy; nội dung được xóa mềm để giữ lịch sử.")
    return redirect("notifications:list")


@login_required(login_url="accounts:login")
@_notice_read_errors
def notice_detail(request, pk):
    notice = get_object_or_404(
        ThongBaoChinhThuc.objects.select_related(
            "bai_viet", "nguoi_phu_trach", "nguoi_xuat_ban", "thong_bao_tham_chieu"
        ), pk=pk
    )
    is_draft = notice.trang_thai == "ban_nhap"
    if is_draft:
        if not can_manage_draft(request.user, notice):
            raise PermissionDenied("Bạn không được xem bản nháp này.")
    elif not can_read_notice(request.user, notice):
        return render(request, "notifications/unavailable.html", status=404)

    attachments = DinhKem.objects.filter(
        bai_viet=notice.bai_viet,
        tep_tin__trang_thai="san_sang",
        tep_tin__da_xoa_mem=False,
    ).select_related("tep_tin", "nguoi_dinh_kem").order_by("thu_tu", "pk")
    recipient = None
    if not is_draft:
        recipient = NguoiNhanThongBao.objects.filter(
            thong_bao=notice, nguoi_dung=request.user
        ).first()

    tracker_access = not is_draft and can_track_notice(request.user, notice)
    tracking = None
    if tracker_access:
        tracking = notice.nguoi_nhan.filter(bat_buoc_xac_nhan=True).aggregate(
            total=Count("pk"),
            acknowledged=Count("pk", filter=Q(trang_thai_tiep_nhan="da_xac_nhan")),
            pending=Count("pk", filter=Q(trang_thai_tiep_nhan="chua_xac_nhan", ngay_xac_nhan__isnull=True)),
        )

    reference_readable = bool(
        notice.thong_bao_tham_chieu_id
        and can_read_notice(request.user, notice.thong_bao_tham_chieu)
    )
    ack_done = bool(
        request.GET.get("ack") == "done"
        and recipient
        and recipient.bat_buoc_xac_nhan
        and recipient.trang_thai_tiep_nhan == "da_xac_nhan"
    )
    return render(request, "notifications/detail.html", {
        "notice": notice,
        "publisher_profile": getattr(notice.nguoi_xuat_ban, "ho_so_nhan_vien", None) if notice.nguoi_xuat_ban_id else None,
        "attachments": attachments,
        "reference_readable": reference_readable,
        "recipient": recipient,
        "tracking": tracking,
        "can_track_notice": tracker_access,
        "ack_done": ack_done,
        "is_draft": is_draft,
        "is_saved": not is_draft and BaiVietDaLuu.objects.filter(
            nguoi_dung=request.user, bai_viet=notice.bai_viet,
        ).exists(),
        "can_publish": can_publish_notices(request.user),
        "can_correct": (not is_draft and can_publish_notices(request.user)),
    })


@login_required(login_url="accounts:login")
@require_POST
@_notice_read_errors
def notice_save(request, pk):
    notice = get_object_or_404(ThongBaoChinhThuc.objects.select_related("bai_viet"), pk=pk)
    if not can_read_notice(request.user, notice):
        raise Http404
    saved = BaiVietDaLuu.objects.filter(nguoi_dung=request.user, bai_viet=notice.bai_viet)
    if request.POST.get("state") == "on":
        saved.get_or_create(nguoi_dung=request.user, bai_viet=notice.bai_viet)
    else:
        saved.delete()
    return redirect("notifications:detail", pk=pk)


ACK_SALT = "ozzone.notice.acknowledgement"


@login_required(login_url="accounts:login")
@_notice_read_errors
def notice_ack_confirm(request, pk):
    notice = get_object_or_404(
        ThongBaoChinhThuc.objects.select_related("bai_viet", "nguoi_xuat_ban"),
        pk=pk,
        trang_thai="da_cong_bo",
    )
    if not can_read_notice(request.user, notice):
        return render(request, "notifications/unavailable.html", status=404)
    recipient = NguoiNhanThongBao.objects.filter(
        thong_bao=notice, nguoi_dung=request.user, bat_buoc_xac_nhan=True
    ).first()
    if recipient is None:
        raise PermissionDenied("Bạn không thuộc tập người nhận cần xác nhận thông báo này.")
    if recipient.trang_thai_tiep_nhan == "da_xac_nhan" and recipient.ngay_xac_nhan:
        return redirect(f"{reverse('notifications:detail', kwargs={'pk': notice.pk})}?ack=done")

    confirmation = [request.user.pk, notice.pk, recipient.pk]
    if request.method == "POST":
        try:
            try:
                confirmed = signing.loads(request.POST.get("confirmation", ""), salt=ACK_SALT, max_age=900)
            except signing.BadSignature:
                confirmed = None
            if confirmed != confirmation:
                raise ValidationError("Hãy xem lại cảnh báo trước khi xác nhận tiếp nhận.")
            recipient, created = acknowledge_notice(
                notice_id=notice.pk, user=request.user, request=request
            )
        except PermissionDenied:
            return render(request, "notifications/unavailable.html", status=404)
        except (ValidationError, IntegrityError, DatabaseError) as exc:
            if isinstance(exc, ValidationError):
                error = " ".join(exc.messages)
            else:
                error = "Chưa lưu được xác nhận do lỗi dữ liệu. Trạng thái vẫn được giữ là Chưa xác nhận; vui lòng tải lại và thử lại."
            return render(request, "notifications/ack_confirm.html", {
                "notice": notice, "recipient": recipient, "error": error,
                "confirmation": signing.dumps(confirmation, salt=ACK_SALT),
            }, status=503 if isinstance(exc, DatabaseError) else 400)
        return redirect(f"{reverse('notifications:detail', kwargs={'pk': notice.pk})}?ack=done")

    return render(request, "notifications/ack_confirm.html", {
        "notice": notice,
        "publisher_profile": getattr(notice.nguoi_xuat_ban, "ho_so_nhan_vien", None),
        "recipient": recipient,
        "confirmation": signing.dumps(confirmation, salt=ACK_SALT),
    })


@login_required(login_url="accounts:login")
@_notice_read_errors
def notice_tracking(request, pk):
    notice = get_object_or_404(
        ThongBaoChinhThuc.objects.select_related("bai_viet", "nguoi_phu_trach", "nguoi_xuat_ban"),
        pk=pk,
        trang_thai="da_cong_bo",
    )
    if not can_track_notice(request.user, notice):
        raise PermissionDenied("Bạn không có quyền theo dõi tập người nhận của thông báo này.")
    # Quyền theo dõi và phạm vi được giao được kiểm tra tách khỏi quyền đọc nội dung.
    search_term = request.GET.get("q", "").strip()[:100]
    status_filter = request.GET.get("status", "all").strip()
    if status_filter not in {"all", "acknowledged", "pending", "lost_access"}:
        status_filter = "all"

    try:
        report_at = timezone.now()
        all_recipients = NguoiNhanThongBao.objects.filter(
            thong_bao=notice,
            bat_buoc_xac_nhan=True,
        )
        stats = all_recipients.aggregate(
            total=Count("pk"),
            acknowledged=Count("pk", filter=Q(trang_thai_tiep_nhan="da_xac_nhan")),
            pending=Count("pk", filter=Q(trang_thai_tiep_nhan="chua_xac_nhan", ngay_xac_nhan__isnull=True)),
        )
        doc_criteria = list(notice.tieu_chi.filter(muc_dich="doc").select_related(
            "phong_ban", "cong_dong", "du_an", "nguoi_dung"
        ))
        currently_readable_ids = resolve_scope_user_ids(
            scope=notice.che_do_doc, criteria=doc_criteria, purpose="doc"
        )
        stats["pending_lost"] = all_recipients.filter(
            trang_thai_tiep_nhan="chua_xac_nhan", ngay_xac_nhan__isnull=True
        ).exclude(nguoi_dung_id__in=currently_readable_ids).count()
        stats["pending_current"] = (stats["pending"] or 0) - stats["pending_lost"]
        recipients = all_recipients.select_related(
            "nguoi_dung", "nguoi_dung__ho_so_nhan_vien", "nguoi_dung__ho_so_nhan_vien__phong_ban"
        )
        if search_term:
            recipients = recipients.filter(
                Q(nguoi_dung__username__icontains=search_term)
                | Q(nguoi_dung__first_name__icontains=search_term)
                | Q(nguoi_dung__last_name__icontains=search_term)
                | Q(nguoi_dung__ho_so_nhan_vien__ma_nhan_vien__icontains=search_term)
                | Q(nguoi_dung__ho_so_nhan_vien__phong_ban__ten_phong_ban__icontains=search_term)
            ).distinct()
        if status_filter == "acknowledged":
            recipients = recipients.filter(trang_thai_tiep_nhan="da_xac_nhan")
        elif status_filter == "pending":
            recipients = recipients.filter(trang_thai_tiep_nhan="chua_xac_nhan", ngay_xac_nhan__isnull=True)
        elif status_filter == "lost_access":
            recipients = recipients.filter(
                trang_thai_tiep_nhan="chua_xac_nhan", ngay_xac_nhan__isnull=True
            ).exclude(nguoi_dung_id__in=currently_readable_ids)

        recipients = recipients.order_by("trang_thai_tiep_nhan", "nguoi_dung__last_name", "nguoi_dung__first_name", "nguoi_dung__username")
        page_obj = Paginator(recipients, 25).get_page(request.GET.get("page"))
        recipient_rows = list(page_obj.object_list)
        for row in recipient_rows:
            profile = getattr(row.nguoi_dung, "ho_so_nhan_vien", None)
            row.display_name = ho_ten(row.nguoi_dung)
            row.department_name = profile.phong_ban.ten_phong_ban if profile else "Chưa cập nhật phòng ban"
            row.currently_readable = row.nguoi_dung_id in currently_readable_ids
    except DatabaseError:
        return render(request, "notifications/tracking.html", {
            "notice": notice,
            "tracking_error": "Không thể tải dữ liệu theo dõi. Dữ liệu cũ không được dùng thay cho kết quả mới; vui lòng tải lại trang.",
            "search_term": search_term,
            "status_filter": status_filter,
        }, status=503)

    return render(request, "notifications/tracking.html", {
        "notice": notice,
        "tracking": stats,
        "report_at": report_at,
        "can_read_report_notice": request.user.pk in currently_readable_ids,
        "recipient_rows": recipient_rows,
        "page_obj": page_obj,
        "search_term": search_term,
        "status_filter": status_filter,
        "filter_choices": [
            ("all", "Tất cả"),
            ("acknowledged", "Đã xác nhận"),
            ("pending", "Chưa xác nhận"),
            ("lost_access", "Chưa xác nhận · Mất quyền đọc"),
        ],
    })


@login_required(login_url="accounts:login")
@_notice_read_errors
def notice_attachment_download(request, attachment_id):
    attachment = DinhKem.objects.select_related("bai_viet", "tep_tin").filter(
        pk=attachment_id, bai_viet__loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT,
    ).first()
    if attachment is None:
        notice_id = request.GET.get("notice", "")
        notice = None
        if notice_id.isascii() and notice_id.isdecimal() and len(notice_id) <= 18:
            notice = ThongBaoChinhThuc.objects.select_related("bai_viet").filter(pk=int(notice_id)).first()
        return render(request, "notifications/unavailable.html", {
            "file_unavailable": True,
            "notice_id": notice.pk if can_read_notice(request.user, notice) else None,
        }, status=404)
    notice = get_object_or_404(ThongBaoChinhThuc, bai_viet=attachment.bai_viet)
    if notice.trang_thai == "ban_nhap":
        allowed = can_manage_draft(request.user, notice)
    else:
        allowed = can_read_notice(request.user, notice)
    if not allowed:
        return render(request, "notifications/unavailable.html", status=404)
    try:
        if attachment.tep_tin.da_xoa_mem or attachment.tep_tin.trang_thai != "san_sang":
            raise FileNotFoundError
        file = attachment.tep_tin.tep.open("rb")
    except (OSError, ValueError):
        return render(request, "notifications/unavailable.html", {
            "file_unavailable": True,
            "notice_id": notice.pk,
            "retry_url": request.get_full_path(),
        }, status=404)
    mime = attachment.tep_tin.loai_tep
    preview = mime in {"image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"}
    response = FileResponse(
        file,
        as_attachment=not (request.GET.get("preview") == "1" and preview),
        filename=attachment.tep_tin.ten_tep,
        content_type=mime or "application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response
