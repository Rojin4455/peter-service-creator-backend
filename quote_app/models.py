# user_models.py - Updated with package selection
from django.db import models
from decimal import Decimal
import uuid
from service_app.models import Service, Package, Location, Question, QuestionOption, SubQuestion,GlobalSizePackage,AddOnService, Coupon

class CustomerSubmission(models.Model):
    """Main customer submission model (revamped)"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('responses_completed', 'Responses Completed'),
        ('packages_selected', 'Packages Selected'),
        ('submitted', 'Submitted'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Customer Information
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    company_name = models.CharField(max_length=255, null=True, blank=True)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    ghl_contact_id = models.CharField(max_length=100, null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)

    allow_sms = models.BooleanField(default=False)
    allow_email = models.BooleanField(default=True)

    # Address info
    street_address = models.TextField(null=True, blank=True)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True)

    # Discovery
    heard_about_us = models.CharField(max_length=255, null=True, blank=True)

    # Property info
    PROPERTY_TYPE_CHOICES = [
        ("residential", "Residential"),
        ("commercial", "Commercial"),
    ]
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPE_CHOICES, null=True, blank=True)
    property_name = models.CharField(max_length=255, null=True, blank=True)  # only for commercial

    num_floors = models.CharField(max_length=50, null=True, blank=True)  # e.g., "1 story", "2 story"
    is_previous_customer = models.BooleanField(default=False)

    # Size info
    size_range = models.ForeignKey(GlobalSizePackage, on_delete=models.SET_NULL, null=True, blank=True)
    actual_sqft = models.PositiveIntegerField(null=True, blank=True)

    # Submission details

    selected_services = models.ManyToManyField(Service, through="CustomerServiceSelection")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    is_bid_in_person = models.BooleanField(default=False)
    # Pricing
    total_base_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_adjustments = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_surcharges = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    quote_surcharge_applicable = models.BooleanField(default=False)
    final_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    additional_data = models.JSONField(default=dict, null=True, blank=True)

    # # addons = models.ManyToManyField(AddOnService, blank=True, related_name="submissions")
    # old_addons = models.ManyToManyField(
    #     AddOnService,
    #     blank=True,
    #     related_name="old_submissions"
    # )

    # # ✅ New through model relationship
    addons = models.ManyToManyField(
        AddOnService,
        through="SubmissionAddOn",
        related_name="submissions",
        blank=True
    )
    total_addons_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # applied_coupon = models.ForeignKey(
    #     Coupon,
    #     on_delete=models.SET_NULL,
    #     null=True,
    #     blank=True,
    #     related_name="submissions"
    # )
    # is_coupon_applied = models.BooleanField(default=False)
    # discounted_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "customer_submissions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.customer_email}"
    



class SubmissionAddOn(models.Model):
    submission = models.ForeignKey(
        CustomerSubmission,
        on_delete=models.CASCADE,
        related_name="submission_addons"
    )
    addon = models.ForeignKey(
        AddOnService,
        on_delete=models.CASCADE,
        related_name="addon_submissions"
    )
    quantity = models.PositiveIntegerField(default=1)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        unique_together = ("submission", "addon")

    def save(self, *args, **kwargs):
        self.subtotal = self.addon.base_price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.addon.name} x {self.quantity} ({self.submission.id})"


class CustomerServiceSelection(models.Model):
    """Through model for customer service selections"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(CustomerSubmission, on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    
    # Selected package (set after user chooses)
    selected_package = models.ForeignKey(Package, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Service-level pricing summary
    question_adjustments = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    surcharge_applicable = models.BooleanField(default=False)
    surcharge_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Final pricing (calculated after package selection)
    final_base_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    final_sqft_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    final_total_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'customer_service_selections'
        unique_together = ['submission', 'service']

# Keep all other models the same...
class CustomerQuestionResponse(models.Model):
    """Customer responses to questions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_selection = models.ForeignKey(CustomerServiceSelection, related_name='question_responses', on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    
    # Response data based on question type
    yes_no_answer = models.BooleanField(null=True, blank=True)
    text_answer = models.TextField(null=True, blank=True)
    
    # Pricing impact
    price_adjustment = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'customer_question_responses'
        unique_together = ['service_selection', 'question']

class CustomerOptionResponse(models.Model):
    """Customer responses to question options"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_response = models.ForeignKey(CustomerQuestionResponse, related_name='option_responses', on_delete=models.CASCADE)
    option = models.ForeignKey(QuestionOption, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    
    # Pricing impact
    price_adjustment = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'customer_option_responses'

class CustomerSubQuestionResponse(models.Model):
    """Customer responses to sub-questions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_response = models.ForeignKey(CustomerQuestionResponse, related_name='sub_question_responses', on_delete=models.CASCADE)
    sub_question = models.ForeignKey(SubQuestion, on_delete=models.CASCADE)
    answer = models.BooleanField()
    
    # Pricing impact
    price_adjustment = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'customer_sub_question_responses'

class CustomerPackageQuote(models.Model):
    """Package quotes for customer (all available packages)"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_selection = models.ForeignKey(CustomerServiceSelection, related_name='package_quotes', on_delete=models.CASCADE)
    package = models.ForeignKey(Package, on_delete=models.CASCADE)
    
    # Pricing breakdown
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    sqft_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    question_adjustments = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    surcharge_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Features breakdown
    included_features = models.JSONField(default=list)  # List of included feature IDs
    excluded_features = models.JSONField(default=list)  # List of excluded feature IDs
    
    # Selection status
    is_selected = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'customer_package_quotes'
        unique_together = ['service_selection', 'package']
