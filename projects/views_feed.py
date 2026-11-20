"""UC-PRJ-04, đọc bảng tin, bài thường và tệp trong đúng dự án."""

import logging
from pathlib import Path
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET
from projectp.models import DinhKem, TepTin
from social.navigation import listing_origin, with_listing_origin
from social.views import _post_cards, post_discussion_context
from .ui import with_issue_state
from .permissions import project_access, readable_project_posts
from .presentation import handled, screen


logger = logging.getLogger(__name__)


def attachments_for(**owner):
    return (
        DinhKem.objects.filter(
            **owner, tep_tin__trang_thai="san_sang", tep_tin__da_xoa_mem=False
        )
        .select_related("tep_tin", "nguoi_dinh_kem")
        .order_by("thu_tu", "pk")
    )


@login_required(login_url="projects:login")
@require_GET
@handled
def project_feed(request, pk):
    """GD-053. Đọc bảng tin theo ngữ cảnh dự án hiện hành."""
    project, membership = project_access(request.user, pk)
    sort = request.GET.get("sort", "latest")
    if sort != "latest":
        from django.core.exceptions import ValidationError

        raise ValidationError("Chế độ sắp xếp không hợp lệ. Hiện hỗ trợ Mới nhất.")
    keyword = request.GET.get("q", "").strip()[:100]
    context = screen(project, membership, f"Bảng tin {project.ten_du_an}", "feed")
    context["q"] = keyword
    try:
        posts = with_issue_state(readable_project_posts(request.user, project)).select_related(
            "nguoi_dang", "ma_the_thiet_bi", "tai_san"
        )
        posts = _post_cards(posts, request.user)
        if keyword:
            posts = posts.filter(Q(tieu_de__icontains=keyword) | Q(noi_dung__icontains=keyword))
        page = Paginator(posts, 12).get_page(request.GET.get("page"))
        visible_posts = list(page)
        files = {}
        for attachment in attachments_for(bai_viet_id__in=[post.pk for post in visible_posts]):
            files.setdefault(attachment.bai_viet_id, []).append(attachment)
        context.update(page_obj=page, feed_rows=[
            {"post": post, "attachments": files.get(post.pk, [])} for post in visible_posts
        ])
        return render(request, "projects/project_feed.html", context)
    except DatabaseError:
        logger.exception("Chưa tải được bảng tin dự án")
        context.update(feed_load_failed=True, retry_url=request.get_full_path(), page_obj=None, feed_rows=[])
        return render(request, "projects/project_feed.html", context, status=503)


@login_required(login_url="projects:login")
@require_GET
@handled
def post_detail(request, pk, post_id):
    """GD-015. Mở bài thường hoặc chuyển sang chi tiết xử lý nếu là vấn đề."""
    try:
        project, membership = project_access(request.user, pk)
    except (Http404, PermissionDenied):
        return render(request, "social/unavailable.html", {
            "back_url": reverse("projects:list"), "back_label": "Về danh sách dự án",
        }, status=404)
    origin = listing_origin(request, project_id=pk)
    post = _post_cards(readable_project_posts(request.user, project), request.user).select_related(
        "nguoi_dang", "ma_the_thiet_bi", "tai_san"
    ).filter(pk=post_id).first()
    if post is None:
        return render(request, "social/unavailable.html", {
            "back_url": origin or reverse("projects:feed", args=[pk]),
            "back_label": "Về bảng tin dự án",
        }, status=404)
    post.du_an = project
    if post.che_do_xu_ly:
        return redirect(with_listing_origin(reverse("projects:issue", args=[pk, post.pk]), origin))
    context = screen(project, membership, post.tieu_de or "Chi tiết bài đăng", "feed")
    context.update(post_discussion_context(request, post))
    context.update(
        post=post,
        back_url=origin or reverse("projects:feed", kwargs={"pk": project.pk}),
        attachments=attachments_for(bai_viet=post),
    )
    return render(request, "projects/post_detail.html", context)


@login_required(login_url="projects:login")
@require_GET
@handled
def attachment_download(request, pk, file_id):
    """Kiểm tra lại quyền nguồn trước khi trả tệp minh chứng."""
    try:
        project, _ = project_access(request.user, pk)
    except (Http404, PermissionDenied):
        return render(request, "social/unavailable.html", {
            "back_url": reverse("projects:list"), "back_label": "Về danh sách dự án",
        }, status=404)
    visible_posts = readable_project_posts(request.user, project)
    source_id = request.GET.get("post", "")
    source = None
    if source_id.isascii() and source_id.isdecimal() and len(source_id) <= 18:
        source = visible_posts.filter(pk=int(source_id)).first()
        visible_posts = visible_posts.filter(pk=source.pk) if source else visible_posts.none()
    visible_ids = visible_posts.values("pk")
    relations = DinhKem.objects.filter(tep_tin_id=file_id).filter(
        Q(bai_viet_id__in=visible_ids)
        | Q(binh_luan__bai_viet_id__in=visible_ids, binh_luan__da_xoa_mem=False)
        | Q(phuong_an__bai_viet_id__in=visible_ids)
        | Q(ket_qua_thu__lan_thu__phuong_an__bai_viet_id__in=visible_ids)
    )
    file = TepTin.objects.filter(pk=file_id, trang_thai="san_sang", da_xoa_mem=False).first() if relations.exists() else None
    try:
        if file is None:
            raise FileNotFoundError
        handle = file.tep.open("rb")
    except (OSError, ValueError):
        return render(request, "social/file_unavailable.html", {
            "source_url": reverse("projects:post_detail", args=[pk, source.pk]) if source else None,
            "listing_url": reverse("projects:feed", args=[pk]),
            "retry_url": request.get_full_path() if file else None,
        }, status=404)
    inline_types = {"image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"}
    response = FileResponse(
        handle,
        as_attachment=not (request.GET.get("preview") == "1" and file.loai_tep in inline_types),
        filename=Path(file.ten_tep).name,
        content_type=file.loai_tep or "application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response
