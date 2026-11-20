"""UC-PRJ-08, tác giả bài nêu vấn đề ghi kết quả thực tế của đúng lần thử."""

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from projectp.models import KetQuaThu, LanThuPhuongAn
from .forms_results import ResultForm
from .permissions import project_access
from .presentation import handled
from .services_technical import record_result
from .views_collaboration import get_issue, technical_form


@login_required(login_url="projects:login")
@require_http_methods(["GET", "POST"])
@handled
def result_create(request, pk, target):
    """GD-061. Người thực hiện ghi kết quả thực tế của đúng lần thử."""
    project, _ = project_access(request.user, pk)
    trial = get_object_or_404(
        LanThuPhuongAn.objects.select_related("phuong_an", "nguoi_thuc_hien"),
        pk=target,
        phuong_an__bai_viet__du_an=project,
    )
    post = get_issue(request.user, project, trial.phuong_an.bai_viet_id)
    if post.nguoi_dang_id != request.user.pk:
        raise PermissionDenied("Chỉ người đăng bài nêu vấn đề được ghi kết quả thực hiện.")
    if request.method == "GET":
        if KetQuaThu.objects.filter(lan_thu=trial).exists():
            messages.info(request, "Lần thử đã có kết quả. Xem kết quả và minh chứng đã ghi nhận.")
            return redirect(
                reverse("projects:issue", kwargs={"pk": pk, "post_id": post.pk}) + "#trials"
            )
        if trial.trang_thai not in ("cho_ket_qua", "dang_thuc_hien"):
            messages.info(request, "Lần thử đã kết thúc. Xem lý do, thời điểm và kết luận liên quan trong lịch sử.")
            return redirect(
                reverse("projects:issue", kwargs={"pk": pk, "post_id": post.pk}) + "#trials"
            )
        if trial.nguoi_thuc_hien_id != request.user.pk:
            messages.error(request, "Người thực hiện của lần thử chưa khớp với người đăng bài. Hãy kiểm tra lại phân công.")
            return redirect(reverse("projects:issue", kwargs={"pk": pk, "post_id": post.pk}) + "#trials")
    return technical_form(
        request,
        pk,
        post,
        ResultForm,
        "UC-PRJ-08",
        "Ghi nhận kết quả thực hiện",
        lambda data: record_result(request.user, project, trial, data),
        target=target,
        submit_label="Lưu kết quả",
        trial=trial,
        notice="Người đăng bài nêu vấn đề trực tiếp thực hiện và ghi nhận kết quả của lần thử. "
        "Kết quả thành công được dùng để xem xét kết luận ở bước sau.",
    )
