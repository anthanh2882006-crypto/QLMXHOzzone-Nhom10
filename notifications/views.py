from accounts.views._chung import ho_ten
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from projectp.models import (
    BaiViet,
    DinhKem,
    NguoiNhanThongBao,
    ThongBaoChinhThuc,
)

from .forms import OfficialNoticeForm, initial_from_notice
from .permissions import (
    can_manage_draft, can_publish_notices, can_read_notice, can_track_notice,
    resolve_scope_user_ids,
)
from .services import acknowledge_notice, cancel_notice_draft, publish_notice, save_notice_draft


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
def notice_create(request, reference_id=None):
    if not can_publish_notices(request.user):
        raise PermissionDenied("Bạn chưa được cấp quyền phát hành thông báo chính thức.")

    correction = None
    if reference_id is not None:
        correction = get_object_or_404(ThongBaoChinhThuc.objects.select_related("bai_viet"), pk=reference_id, trang_thai="da_cong_bo")
        if not can_read_notice(request.user, correction):
            raise PermissionDenied("Bạn không có quyền xem thông báo được chọn để đính chính.")

    publish_key = uuid.uuid4()
    initial = {"publish_key": publish_key}
    if correction:
        # Carry forward the original read/distribution scope by default.
        # A correction must not accidentally broaden the audience to the whole company.
        initial.update(initial_from_notice(correction, publish_key))
        initial.update({
            "tieu_de": f"Đính chính: {correction.bai_viet.tieu_de}"[:250],
            "thong_bao_tham_chieu": correction.pk,
        })

    if request.method == "POST":
        form = OfficialNoticeForm(request.POST, request.FILES)
        if form.is_valid():
            if correction and getattr(form.cleaned_data.get("thong_bao_tham_chieu"), "pk", None) != correction.pk:
                form.add_error(None, "Thông báo đính chính phải giữ tham chiếu đến thông báo đã chọn.")
                return render(request, "notifications/form.html", _notice_form_context(
                    request, form, correction=correction
                ), status=400)
            key = form.cleaned_data["publish_key"]
            already = ThongBaoChinhThuc.objects.filter(khoa_yeu_cau_xuat_ban=key, trang_thai="da_cong_bo").first()
            if already:
                messages.success(request, "Thông báo đã được phát hành trước đó; không tạo phân phối trùng.")
                return redirect("notifications:detail", pk=already.pk)
            try:
                draft = save_notice_draft(
                    user=request.user,
                    cleaned=form.cleaned_data,
                    files=request.FILES.getlist("tep_dinh_kem"),
                    request=request,
                )
                action = request.POST.get("action", "save_draft")
                if action == "publish":
                    published, created = publish_notice(
                        notice_id=draft.pk,
                        user=request.user,
                        request_key=key,
                        request=request,
                    )
                    messages.success(request, "Thông báo chính thức đã được phát hành và phân phối đến tập người nhận hợp lệ.")
                    return redirect("notifications:detail", pk=published.pk)
                messages.success(request, "Bản nháp thông báo đã được lưu.")
                return redirect("notifications:edit_draft", pk=draft.pk)
            except (ValidationError, IntegrityError) as exc:
                if isinstance(exc, ValidationError):
                    error_messages = exc.messages
                else:
                    error_messages = ["Không thể lưu/phát hành do xung đột dữ liệu. Bản nháp hợp lệ (nếu đã lưu) được giữ nguyên; vui lòng tải lại và thử lại."]
                for message in error_messages:
                    form.add_error(None, message)
                notice = locals().get("draft")
                if notice:
                    form.fields["remove_attachment_ids"].queryset = DinhKem.objects.filter(bai_viet=notice.bai_viet)
                return render(request, "notifications/form.html", _notice_form_context(
                    request, form, notice=notice, is_edit=bool(notice), correction=correction
                ), status=400)
    else:
        form = OfficialNoticeForm(initial=initial)

    return render(request, "notifications/form.html", _notice_form_context(
        request, form, correction=correction
    ))


@login_required(login_url="accounts:login")
def notice_edit_draft(request, pk):
    notice = get_object_or_404(
        ThongBaoChinhThuc.objects.select_related("bai_viet", "thong_bao_tham_chieu"),
        pk=pk,
        bai_viet__da_xoa_mem=False,
    )
    if notice.trang_thai != "ban_nhap":
        raise PermissionDenied("Thông báo đã công bố là bất biến; hãy tạo thông báo đính chính mới.")
    if not can_manage_draft(request.user, notice):
        raise PermissionDenied("Bạn không được biên tập bản nháp này.")

    if request.method == "POST":
        form = OfficialNoticeForm(request.POST, request.FILES, notice=notice)
        if form.is_valid():
            key = form.cleaned_data["publish_key"]
            already = ThongBaoChinhThuc.objects.filter(khoa_yeu_cau_xuat_ban=key, trang_thai="da_cong_bo").first()
            if already:
                messages.success(request, "Yêu cầu phát hành đã được xử lý trước đó.")
                return redirect("notifications:detail", pk=already.pk)
            try:
                draft = save_notice_draft(
                    user=request.user,
                    cleaned=form.cleaned_data,
                    files=request.FILES.getlist("tep_dinh_kem"),
                    notice=notice,
                    request=request,
                )
                notice = draft
                if request.POST.get("action") == "publish":
                    published, created = publish_notice(
                        notice_id=draft.pk,
                        user=request.user,
                        request_key=key,
                        request=request,
                    )
                    messages.success(request, "Thông báo chính thức đã được phát hành.")
                    return redirect("notifications:detail", pk=published.pk)
                messages.success(request, "Bản nháp đã được cập nhật.")
                return redirect("notifications:edit_draft", pk=draft.pk)
            except (ValidationError, IntegrityError) as exc:
                error_messages = exc.messages if isinstance(exc, ValidationError) else [
                    "Không thể lưu/phát hành do xung đột dữ liệu. Bản nháp hợp lệ được giữ nguyên; vui lòng tải lại và thử lại."
                ]
                for message in error_messages:
                    form.add_error(None, message)
                current_notice = locals().get("draft", notice)
                form.fields["remove_attachment_ids"].queryset = DinhKem.objects.filter(bai_viet=current_notice.bai_viet)
                return render(request, "notifications/form.html", _notice_form_context(
                    request, form, notice=current_notice, is_edit=True
                ), status=400)
    else:
        form = OfficialNoticeForm(
            initial=initial_from_notice(notice, uuid.uuid4()),
            notice=notice,
        )

    return render(request, "notifications/form.html", _notice_form_context(
        request, form, notice=notice, is_edit=True
    ))


@login_required(login_url="accounts:login")
@require_POST
def notice_cancel_draft(request, pk):
    notice = get_object_or_404(ThongBaoChinhThuc.objects.select_related("bai_viet"), pk=pk)
    cancel_notice_draft(notice=notice, user=request.user, request=request)
    messages.success(request, "Bản nháp đã được hủy; nội dung được xóa mềm để giữ lịch sử.")
    return redirect("notifications:list")


@login_required(login_url="accounts:login")
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
        raise PermissionDenied("Bạn không còn quyền đọc thông báo này.")

    attachments = DinhKem.objects.filter(
        bai_viet=notice.bai_viet,
        tep_tin__trang_thai="san_sang",
        tep_tin__da_xoa_mem=False,
    ).select_related("tep_tin").order_by("thu_tu", "pk")
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
        "can_publish": can_publish_notices(request.user),
        "can_correct": (not is_draft and can_publish_notices(request.user)),
    })


@login_required(login_url="accounts:login")
def notice_ack_confirm(request, pk):
    notice = get_object_or_404(
        ThongBaoChinhThuc.objects.select_related("bai_viet", "nguoi_xuat_ban"),
        pk=pk,
        trang_thai="da_cong_bo",
    )
    if not can_read_notice(request.user, notice):
        raise PermissionDenied("Bạn không còn quyền đọc thông báo này.")
    recipient = NguoiNhanThongBao.objects.filter(
        thong_bao=notice, nguoi_dung=request.user, bat_buoc_xac_nhan=True
    ).first()
    if recipient is None:
        raise PermissionDenied("Bạn không thuộc tập người nhận cần xác nhận thông báo này.")
    if recipient.trang_thai_tiep_nhan == "da_xac_nhan" and recipient.ngay_xac_nhan:
        return redirect(f"{reverse('notifications:detail', kwargs={'pk': notice.pk})}?ack=done")

    if request.method == "POST":
        try:
            recipient, created = acknowledge_notice(
                notice_id=notice.pk, user=request.user, request=request
            )
        except (ValidationError, IntegrityError, DatabaseError) as exc:
            if isinstance(exc, ValidationError):
                error = " ".join(exc.messages)
            else:
                error = "Chưa lưu được xác nhận do lỗi dữ liệu. Trạng thái vẫn được giữ là Chưa xác nhận; vui lòng tải lại và thử lại."
            return render(request, "notifications/ack_confirm.html", {
                "notice": notice, "recipient": recipient, "error": error,
            }, status=503 if isinstance(exc, DatabaseError) else 400)
        return redirect(f"{reverse('notifications:detail', kwargs={'pk': notice.pk})}?ack=done")

    return render(request, "notifications/ack_confirm.html", {
        "notice": notice,
        "publisher_profile": getattr(notice.nguoi_xuat_ban, "ho_so_nhan_vien", None),
        "recipient": recipient,
    })


@login_required(login_url="accounts:login")
def notice_tracking(request, pk):
    notice = get_object_or_404(
        ThongBaoChinhThuc.objects.select_related("bai_viet", "nguoi_phu_trach", "nguoi_xuat_ban"),
        pk=pk,
        trang_thai="da_cong_bo",
    )
    if not can_track_notice(request.user, notice):
        raise PermissionDenied("Bạn không có quyền theo dõi tập người nhận của thông báo này.")
    # A tracking role is independently authorized by the dedicated business permission;
    # it does not need to be part of the reader/recipient audience.
    search_term = request.GET.get("q", "").strip()[:100]
    status_filter = request.GET.get("status", "all").strip()
    if status_filter not in {"all", "acknowledged", "pending", "lost_access"}:
        status_filter = "all"

    try:
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
def notice_attachment_download(request, attachment_id):
    attachment = get_object_or_404(
        DinhKem.objects.select_related("bai_viet", "tep_tin"),
        pk=attachment_id,
        bai_viet__loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT,
        tep_tin__trang_thai="san_sang",
        tep_tin__da_xoa_mem=False,
    )
    notice = get_object_or_404(ThongBaoChinhThuc, bai_viet=attachment.bai_viet)
    if notice.trang_thai == "ban_nhap":
        allowed = can_manage_draft(request.user, notice)
    else:
        allowed = can_read_notice(request.user, notice)
    if not allowed:
        raise PermissionDenied("Bạn không có quyền tải tệp của thông báo này.")
    if not attachment.tep_tin.tep:
        raise Http404("Tệp không còn khả dụng.")
    response = FileResponse(
        attachment.tep_tin.tep.open("rb"),
        as_attachment=True,
        filename=attachment.tep_tin.ten_tep,
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response
