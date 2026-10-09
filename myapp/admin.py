from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CustomUser, SurveyResponse


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    ordering = ["email"]
    list_display = ["email", "last_name", "first_name", "role", "is_staff", "is_active"]
    list_filter = ["role", "is_staff", "is_active"]
    search_fields = ["email", "last_name", "first_name"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "middle_name", "last_name", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "middle_name", "last_name", "role", "password1", "password2"),
        }),
    )


admin.site.register(CustomUser, CustomUserAdmin)

@admin.register(SurveyResponse)
class SurveyResponseAdmin(admin.ModelAdmin):
    list_display = ["id", "survey_type", "user", "created_at"]
    list_filter = ["survey_type", "created_at"]
    readonly_fields = ["survey_type", "user", "data", "created_at"]