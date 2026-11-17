"""UC-PRJ-09, hệ thống kiểm tra căn cứ và ghi kết luận cùng nhu cầu đánh giá tri thức."""

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from projectp.models import KetLuanXuLy, KetQuaThu
from .forms_resolution import ResolutionForm
from .permissions import can_resolve, project_access
from .presentation import handled
from .services_technical import record_resolution
from .views_collaboration import get_issue, technical_form
from .views_feed import attachments_for


@login_required(login_url="projects:login")
@require_http_methods(["GET", "POST"])
@handled
def resolution_create(request, pk, post_id):
    """GD-062. Gửi một căn cứ thành công để hệ thống kiểm tra và ghi kết luận."""
    project, _ = project_access(request.user, pk)
    if not can_resolve(request.user, project):
        raise PermissionDenied("Bạn cần có tư cách thành viên hợp lệ trong dự án để đề nghị kết luận xử lý.")
    post = get_issue(request.user, project, post_id)
    if request.method == "GET" and KetLuanXuLy.objects.filter(bai_viet_nguon=post).exists():
        messages.info(request, "Vấn đề đã có kết luận. Xem kết luận hiện hành và căn cứ.")
        return redirect(
            reverse("projects:issue", kwargs={"pk": pk, "post_id": post.pk}) + "#resolution"
        )
    # GD-062 B2 cho đối chiếu toàn bộ nội dung và minh chứng trước khi chọn đúng một căn cứ.
    candidates = KetQuaThu.objects.filter(
        lan_thu__phuong_an__bai_viet=post,
        thanh_cong=True,
        lan_thu__trang_thai="da_co_ket_qua",
    ).select_related("lan_thu__phuong_an", "lan_thu__nguoi_thuc_hien", "nguoi_ghi_nhan")
    evidence = [
        {
            "result": result,
            "solution": result.lan_thu.phuong_an,
            "solution_files": attachments_for(phuong_an=result.lan_thu.phuong_an),
            "result_files": attachments_for(ket_qua_thu=result),
        }
        for result in candidates.order_by("-ngay_ghi_nhan", "-pk")
    ]
    return technical_form(
        request,
        pk,
        post,
        ResolutionForm,
        "UC-PRJ-09",
        "Đề nghị kết luận xử lý",
        lambda data: record_resolution(request.user, project, post, data),
        form_kwargs={"post": post},
        submit_label="Gửi đề nghị kết luận",
        evidence=evidence,
        evidence_required=True,
        notice="Chọn đúng một kết quả thành công của vấn đề làm căn cứ. "
        "Khi đủ điều kiện, hệ thống ghi kết luận, trạng thái Đã giải quyết và nhu cầu xem xét tri thức. "
        "Các lần thử còn chờ của vấn đề sẽ được dừng và lưu lý do trong lịch sử.",
    )
