"""Đầu mối views của projects. Mỗi use case được xử lý trong file riêng.

URL chỉ import từ đây để giữ tên gọi thống nhất khi nối 10 use case.
"""

from .views_create import project_create
from .views_auth import project_login, project_logout
from .views_browse import project_list, project_detail
from .views_manage import (
    project_manage,
    member_list,
    member_add,
    member_role_update,
    member_end,
    equipment_list,
    equipment_create,
    equipment_update,
    knowledge_assign,
    knowledge_end,
    project_archive,
)
from .views_feed import project_feed, post_detail, attachment_download
from .views_posts import project_post_create
from .views_field import equipment_detail, field_update_create
from .views_collaboration import (
    issue_list,
    issue_detail,
    analysis_create,
    solution_create,
    trial_create,
    trial_assign,
)
from .views_results import result_create
from .views_resolution import resolution_create
from .views_history import project_history, history_detail
