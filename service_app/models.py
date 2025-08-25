# models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
import uuid


class User(AbstractUser):
    """Extended User model for admin authentication"""
    is_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'auth_user'


class Location(models.Model):
    """Location model with Google Places API integration"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    address = models.TextField()
    latitude = models.DecimalField(max_digits=20, decimal_places=16)
    longitude = models.DecimalField(max_digits=21, decimal_places=16)
    trip_surcharge = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    google_place_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = 'locations'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - {self.address}"


class Service(models.Model):
    """Main service model"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = 'services'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name
    
class ServiceSettings(models.Model):
    service = models.OneToOneField('Service', on_delete=models.CASCADE, related_name='settings')

    # Disclaimers
    general_disclaimer = models.TextField(blank=True, null=True)
    bid_in_person_disclaimer = models.TextField(blank=True, null=True)

    # Boolean settings (based on the UI)
    apply_area_minimum = models.BooleanField(default=False)
    apply_house_size_minimum = models.BooleanField(default=False)
    apply_trip_charge_to_bid = models.BooleanField(default=False)
    enable_dollar_minimum = models.BooleanField(default=False)

    def __str__(self):
        return f"Settings for {self.service.name}"


class Package(models.Model):
    """Package model with one-to-many relationship to Service"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.ForeignKey(Service, related_name='packages', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    base_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'packages'
        ordering = ['order', 'name']
        unique_together = ['service', 'name']

    def __str__(self):
        return f"{self.service.name} - {self.name}"


class Feature(models.Model):
    """Feature model with many-to-many relationship to Package"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.ForeignKey(Service, related_name='features', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'features'
        unique_together = ['service', 'name']

    def __str__(self):
        return f"{self.service.name} - {self.name}"


class PackageFeature(models.Model):
    """Through model for Package-Feature relationship with additional logic"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    package = models.ForeignKey(Package, related_name='package_features', on_delete=models.CASCADE)
    feature = models.ForeignKey(Feature, related_name='package_features', on_delete=models.CASCADE)
    is_included = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'package_features'
        unique_together = ['package', 'feature']

    def __str__(self):
        return f"{self.package.name} - {self.feature.name}"


class Question(models.Model):
    """Base question model for dynamic question builder"""
    
    QUESTION_TYPES = [
        ('yes_no', 'Yes/No'),
        ('describe', 'Describe (Multiple Options)'),  # Renamed from 'options'
        ('multiple_yes_no', 'Multiple Yes/No Sub-Questions'),
        ('conditional', 'Conditional Questions'),
        ('quantity', 'How Many (Quantity Selection)'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.ForeignKey(Service, related_name='questions', on_delete=models.CASCADE)
    parent_question = models.ForeignKey('self', related_name='child_questions', 
                                      on_delete=models.CASCADE, null=True, blank=True)
    
    # Conditional logic fields
    condition_answer = models.CharField(max_length=20, null=True, blank=True, 
                                      help_text="Answer value that triggers this conditional question (e.g., 'yes', 'no', or option ID)")
    condition_option = models.ForeignKey('QuestionOption', related_name='conditional_questions', 
                                       on_delete=models.CASCADE, null=True, blank=True,
                                       help_text="Option that triggers this conditional question")
    
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'questions'
        ordering = ['order', 'created_at']

    def __str__(self):
        return f"{self.service.name} - {self.question_text[:50]}..."

    @property
    def is_conditional(self):
        """Check if this is a conditional question"""
        return self.parent_question is not None

    @property
    def is_parent(self):
        """Check if this question has child questions"""
        return self.child_questions.exists()


class QuestionOption(models.Model):
    """Options for describe/quantity type questions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, related_name='options', on_delete=models.CASCADE)
    option_text = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    # For quantity questions
    allow_quantity = models.BooleanField(default=False, 
                                       help_text="Allow quantity input for this option")
    max_quantity = models.PositiveIntegerField(default=1, 
                                             help_text="Maximum allowed quantity")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'question_options'
        ordering = ['order', 'option_text']

    def __str__(self):
        return f"{self.question.question_text[:30]}... - {self.option_text}"
    


class SubQuestion(models.Model):
    """Sub-questions for multiple_yes_no type questions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent_question = models.ForeignKey(Question, related_name='sub_questions', on_delete=models.CASCADE)
    sub_question_text = models.TextField()
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sub_questions'
        ordering = ['order', 'sub_question_text']

    def __str__(self):
        return f"{self.parent_question.question_text[:30]}... - {self.sub_question_text[:30]}..."
    



class QuestionPricing(models.Model):
    """Pricing rules for questions per package"""
    
    PRICING_TYPES = [
        ('upcharge_percent', 'Fixed Upcharge Amount'),
        ('discount_percent', 'Fixed Discount Amount'),
        ('fixed_price', 'Fixed Price'),
        ('ignore', 'Ignore'),
    ]
    VALUE_TYPES = [
        ('amount', 'Amount'),
        ('percent', 'Percentage')
    ]

    
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, related_name='pricing_rules', on_delete=models.CASCADE)
    package = models.ForeignKey('Package', related_name='question_pricing', on_delete=models.CASCADE)
    
    # For Yes/No questions - pricing when answer is "Yes"
    yes_pricing_type = models.CharField(max_length=20, choices=PRICING_TYPES, default='ignore')
    value_type = models.CharField(max_length=20, choices=VALUE_TYPES, default='amount')

    yes_value = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Fixed amount to add/subtract (e.g., 12.00 for $12)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'question_pricing'
        unique_together = ['question', 'package']

    def __str__(self):
        return f"{self.package.name} - {self.question.question_text[:30]}..."


class SubQuestionPricing(models.Model):
    """Pricing rules for sub-questions per package"""
    
    PRICING_TYPES = [
        ('upcharge_percent', 'Fixed Upcharge Amount'),
        ('discount_percent', 'Fixed Discount Amount'),
        ('fixed_price', 'Fixed Price'),
        ('ignore', 'Ignore'),
    ]
    VALUE_TYPES = [
        ('amount', 'Amount'),
        ('percent', 'Percentage')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sub_question = models.ForeignKey(SubQuestion, related_name='pricing_rules', on_delete=models.CASCADE)
    package = models.ForeignKey('Package', related_name='sub_question_pricing', on_delete=models.CASCADE)
    
    yes_pricing_type = models.CharField(max_length=20, choices=PRICING_TYPES, default='ignore')
    value_type = models.CharField(max_length=20, choices=VALUE_TYPES, default='amount')

    yes_value = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Fixed amount to add/subtract for 'Yes' answer"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sub_question_pricing'
        unique_together = ['sub_question', 'package']

    def __str__(self):
        return f"{self.package.name} - {self.sub_question.sub_question_text[:30]}..."


class OptionPricing(models.Model):
    """Pricing rules for question options per package"""
    
    PRICING_TYPES = [
        ('upcharge_percent', 'Fixed Upcharge Amount'),
        ('discount_percent', 'Fixed Discount Amount'),
        ('fixed_price', 'Fixed Price'),
        ('per_quantity', 'Price Per Quantity'),  # New for quantity questions
        ('ignore', 'Ignore'),
    ]

    VALUE_TYPES = [
        ('amount', 'Amount'),
        ('percent', 'Percentage')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    option = models.ForeignKey(QuestionOption, related_name='pricing_rules', on_delete=models.CASCADE)
    package = models.ForeignKey('Package', related_name='option_pricing', on_delete=models.CASCADE)
    
    pricing_type = models.CharField(max_length=20, choices=PRICING_TYPES, default='ignore')
    value_type = models.CharField(max_length=20, choices=VALUE_TYPES, default='amount')

    value = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Fixed amount to add/subtract (e.g., 12.00 for $12) or price per quantity"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'option_pricing'
        unique_together = ['option', 'package']

    def __str__(self):
        return f"{self.package.name} - {self.option.option_text}"



class QuestionResponse(models.Model):
    """Store customer responses to questions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    # You can add user/session reference here
    
    # For different question types
    yes_no_answer = models.BooleanField(null=True, blank=True)
    text_answer = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'question_responses'


class OptionResponse(models.Model):
    """Store customer responses to options"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_response = models.ForeignKey(QuestionResponse, related_name='option_responses', on_delete=models.CASCADE)
    option = models.ForeignKey(QuestionOption, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'option_responses'


class SubQuestionResponse(models.Model):
    """Store customer responses to sub-questions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_response = models.ForeignKey(QuestionResponse, related_name='sub_question_responses', on_delete=models.CASCADE)
    sub_question = models.ForeignKey(SubQuestion, on_delete=models.CASCADE)
    answer = models.BooleanField()
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sub_question_responses'

# Future-ready models for orders/invoices (when user side is built)
class Order(models.Model):
    """Order model for future user side implementation"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # user = models.ForeignKey(User, related_name='orders', on_delete=models.CASCADE)  # Future
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='orders')
    package = models.ForeignKey(Package, on_delete=models.PROTECT, related_name='orders')
    location = models.ForeignKey(Location, on_delete=models.PROTECT, null=True, blank=True)
    
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    trip_surcharge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    question_adjustments = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'orders'
        ordering = ['-created_at']

    def __str__(self):
        return f"Order {self.id} - {self.service.name}"


class OrderQuestionAnswer(models.Model):
    """Store user answers to questions for each order"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, related_name='question_answers', on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    
    # For Yes/No questions
    yes_no_answer = models.BooleanField(null=True, blank=True)
    
    # For Option questions
    selected_option = models.ForeignKey(QuestionOption, on_delete=models.PROTECT, null=True, blank=True)
    
    # Price impact from this answer
    price_adjustment = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'order_question_answers'
        unique_together = ['order', 'question']

    def __str__(self):
        return f"Order {self.order.id} - {self.question.question_text[:30]}..."
    


class PropertyType(models.Model):
    """Property type model for Residential/Commercial classification"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, unique=True)  # 'Residential' or 'Commercial'
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'property_types'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

# models.py
class GlobalSizePackage(models.Model):
    """Defines a size range globally applicable to all services, separated by property type"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property_type = models.ForeignKey(
        PropertyType, 
        on_delete=models.CASCADE, 
        related_name='size_packages',null=True, blank=True
    )
    min_sqft = models.PositiveIntegerField()
    max_sqft = models.PositiveIntegerField(null=True, blank=True, default=100000000)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    

    class Meta:
        db_table = 'global_size_packages'
        ordering = ['property_type__order', 'order', 'min_sqft']
        unique_together = ['property_type', 'min_sqft', 'max_sqft']

    def __str__(self):
        return f"{self.property_type.name}: {self.min_sqft} - {self.max_sqft} sqft"
    

class GlobalPackageTemplate(models.Model):
    """Defines prices per package type for a global size range"""
    # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    global_size = models.ForeignKey(GlobalSizePackage, related_name='template_prices', on_delete=models.CASCADE)
    label = models.CharField(max_length=255)  # Example: Package 1, Package 2
    price = models.DecimalField(max_digits=10, decimal_places=2)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True , null=True, blank=True)

    class Meta:
        db_table = 'global_package_templates'
        ordering = ['order']
        unique_together = ['global_size', 'label']

    def __str__(self):
        return f"{self.label} @ {self.global_size}"
    

class ServicePackageSizeMapping(models.Model):
    """Actual price mapping for service-level packages against size range"""
    # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_package = models.ForeignKey(Package, related_name='size_pricings', on_delete=models.CASCADE)
    global_size = models.ForeignKey(GlobalSizePackage, on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        db_table = 'service_package_size_mappings'
        unique_together = ['service_package', 'global_size']
        ordering = ['global_size__property_type__order', 'global_size__order']

    def __str__(self):
        return f"{self.service_package} ({self.global_size}) - ${self.price}"
    


class AddOnService(models.Model):
    """
    Represents extra add-ons (upsells, extras, etc.) with base price, name, and description.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name