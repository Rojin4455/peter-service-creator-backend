from django.contrib import admin
from service_app.models import ServicePackageSizeMapping
from .models import CustomerSubmission

admin.site.register(ServicePackageSizeMapping)


@admin.register(CustomerSubmission)
class CustomerSubmissionAdmin(admin.ModelAdmin):
    """Admin configuration for CustomerSubmission"""
    list_display = ['id', 'first_name', 'last_name', 'customer_email', 'status', 'created_at']
    list_filter = ['status', 'created_at', 'property_type']
    search_fields = ['first_name', 'last_name', 'customer_email', 'company_name']
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Customer Information', {
            'fields': ('first_name', 'last_name', 'company_name', 'customer_email', 'customer_phone', 'postal_code')
        }),
        ('Address Information', {
            'fields': ('street_address', 'location')
        }),
        ('Property Information', {
            'fields': ('property_type', 'property_name', 'num_floors', 'is_previous_customer', 'size_range', 'actual_sqft')
        }),
        ('Submission Details', {
            'fields': ('status', 'is_bid_in_person', 'quote_url')
        }),
        ('Pricing', {
            'fields': ('total_base_price', 'total_adjustments', 'total_surcharges', 'final_total', 'quote_surcharge_applicable')
        }),
        ('Admin Notes', {
            'fields': ('bid_notes_private', 'bid_notes_public'),
            'description': 'Notes that can be added by admins. Private notes are only visible to admins, public notes are visible to customers.'
        }),
        ('Additional Information', {
            'fields': ('heard_about_us', 'allow_sms', 'allow_email', 'additional_data', 'is_on_the_go')
        }),
        ('Coupon Information', {
            'fields': ('applied_coupon', 'is_coupon_applied', 'discounted_amount')
        }),
        ('Edit History', {
            'fields': ('last_edited_at', 'edited_by', 'edit_count', 'original_final_total', 'edit_history')
        }),
        ('Timestamps', {
            'fields': ('id', 'created_at', 'updated_at', 'expires_at', 'declined_at')
        }),
    )

# Register your models here.
