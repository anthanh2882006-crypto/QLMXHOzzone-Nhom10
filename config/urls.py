from django.contrib import admin
from django.conf import settings
from django.urls import include, path
from accounts import views as account_views
from accounts.urls import urlpatterns as account_patterns
from .media import media_file


urlpatterns = [
    path("knowledge/", include("knowledge.urls")),
    path("tai-khoan/", include((account_patterns + [
        path("doi-mat-khau-lan-dau/", account_views.first_password, name="first_password_change"),
    ], "accounts"))),
    path("accounts/login/", account_views.OzzoneLoginView.as_view(), name="legacy_account_login"),
    path("accounts/logout/", account_views.legacy_logout, name="legacy_account_logout"),
    path("accounts/doi-mat-khau-lan-dau/", account_views.first_password, name="legacy_first_password"),
    path("cong-dong/", include("communities.urls")),
    path("social/", include("social.urls")),
    path("notifications/", include("notifications.urls")),
    path("", include("core.urls")),
    path(
        "admin/",
        admin.site.urls,
    ),

    path(
        "projects/",
        include("projects.urls"),
    ),
]

if settings.DEBUG:
    urlpatterns += [path("media/<path:path>", media_file, name="media_file")]
