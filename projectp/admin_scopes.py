"""Phạm vi theo Use Case cấp qua Django Groups, độc lập với quyền model."""

SOC_MODERATION_PREFIX = "OZZONE:SOC-10:"
COMMUNITY_ADMIN_PREFIX = "OZZONE:COM-08:"
KNOWLEDGE_ADMIN_PREFIX = "OZZONE:KNW-06:"
OBJECT_SCOPE_PREFIXES = (SOC_MODERATION_PREFIX, COMMUNITY_ADMIN_PREFIX, KNOWLEDGE_ADMIN_PREFIX)


def assigned_scopes(user, prefix):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return set()
    return {
        name.removeprefix(prefix)
        for name in user.groups.filter(name__startswith=prefix).values_list("name", flat=True)
    }


def scope_ids(scopes, resource):
    prefix = resource + ":"
    suffixes = (scope.removeprefix(prefix) for scope in scopes if scope.startswith(prefix))
    return [
        int(value) for value in suffixes
        if value.isascii() and value.isdecimal() and len(value) <= 18
    ]
