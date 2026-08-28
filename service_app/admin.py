from django.contrib import admin
from .models import (
    Package,
    GlobalSizePackage,
    SubQuestionPricing,
    QuestionPricing,
    OptionPricing,
    DashboardApiKey,
)

admin.site.register(Package)
admin.site.register(GlobalSizePackage)
admin.site.register(SubQuestionPricing)
admin.site.register(QuestionPricing)
admin.site.register(OptionPricing)


@admin.register(DashboardApiKey)
class DashboardApiKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'key_prefix', 'is_active', 'created_at', 'last_used_at')
    list_filter = ('is_active',)
    readonly_fields = ('id', 'key_prefix', 'key_hash', 'created_at', 'last_used_at')
    search_fields = ('name', 'key_prefix')
