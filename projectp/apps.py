from django.apps import AppConfig
from django.contrib.admin import apps as admin_apps


class ProjectpConfig(AppConfig):
    name = 'projectp'


class OzzoneAdminConfig(admin_apps.AdminConfig):
    default = False
    default_site = 'projectp.admin_site.OzzoneAdminSite'
