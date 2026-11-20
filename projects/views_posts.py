"""UC-PRJ-05, hiển thị biểu mẫu và phản hồi kết quả tạo bài dự án."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from .forms_posts import ProjectPostForm
from .permissions import project_access
from .presentation import form_page, handled
from .services_common import request_token
from .services_posts import create_post


@login_required(login_url="projects:login")
@require_http_methods(["GET", "POST"])
@handled
def project_post_create(request, pk):
    """GD-054. Tạo bài chia sẻ hoặc vấn đề từ lựa chọn chủ động của thành viên."""
    # POST gửi lại có thể đọc kết quả đã lưu. Dịch vụ vẫn chặn mọi lệnh ghi mới khi lưu trữ.
    project, membership = project_access(request.user, pk)
    if request.method == "GET" and project.da_luu_tru:
        messages.info(request, "Dự án đã lưu trữ. Bạn có thể xem dữ liệu lịch sử theo quyền.")
        return redirect("projects:detail", pk=pk)
    form = ProjectPostForm(
        request.POST if request.method == "POST" else None,
        request.FILES or None,
        initial={
            "request_token": request_token(request.user, "UC-PRJ-05", pk),
            "che_do_xu_ly": request.GET.get("issue") == "1",
            "tieu_de": request.GET.get("context", "")[:250],
            "noi_dung": request.GET.get("context", ""),
        },
    )
    status_code = 200
    if request.method == "POST" and form.is_valid():
        try:
            post_id = create_post(request.user, project, form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        except PermissionDenied as exc:
            form.add_error(None, str(exc))
            status_code = 403
        except DatabaseError:
            form.add_error(None, "Chưa lưu được bài. Thay đổi dở dang được hoàn tác. Bạn có thể thử lại.")
        else:
            messages.success(request, "Đã tạo bài đăng dự án.")
            if form.cleaned_data["che_do_xu_ly"]:
                return redirect("projects:issue", pk=pk, post_id=post_id)
            return redirect(reverse("projects:feed", kwargs={"pk": pk}) + f"#post-{post_id}")
    from knowledge.views import _knowledge_sources_for, _ordered_items

    related_knowledge = []
    try:
        sources = _knowledge_sources_for(request.user)
        related_knowledge = _ordered_items({
            "lessons": sources["lessons"].filter(bai_viet_nguon__du_an=project),
            "articles": sources["articles"].filter(phien_ban_dang_cong_bo__du_an=project),
            "conclusions": sources["conclusions"].filter(bai_viet_nguon__du_an=project),
        }, 3)[:3]
    except DatabaseError:
        pass
    return form_page(
        request,
        form,
        "Tạo bài đăng dự án",
        reverse("projects:detail" if project.da_luu_tru else "projects:feed", kwargs={"pk": pk}),
        project,
        membership,
        section="feed",
        submit_label="Đăng bài",
        status=status_code,
        show_related_knowledge=True,
        related_knowledge=related_knowledge,
        notice="Chọn chế độ xử lý khi muốn mở vấn đề kỹ thuật. Bài thông thường dùng cho chia sẻ và trao đổi.",
    )
