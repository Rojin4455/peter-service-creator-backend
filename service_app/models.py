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
        ('options', 'Multiple Options'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.ForeignKey(Service, related_name='questions', on_delete=models.CASCADE)
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


class QuestionOption(models.Model):
    """Options for multiple choice questions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, related_name='options', on_delete=models.CASCADE)
    option_text = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'question_options'
        ordering = ['order', 'option_text']

    def __str__(self):
        return f"{self.question.question_text[:30]}... - {self.option_text}"


class QuestionPricing(models.Model):
    """Pricing rules for questions per package"""
    
    PRICING_TYPES = [
        ('upcharge_percent', 'Fixed Upcharge Amount'),  # Updated label
        ('discount_percent', 'Fixed Discount Amount'),  # Updated label
        ('fixed_price', 'Fixed Price'),
        ('ignore', 'Ignore'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, related_name='pricing_rules', on_delete=models.CASCADE)
    package = models.ForeignKey(Package, related_name='question_pricing', on_delete=models.CASCADE)
    
    # For Yes/No questions - pricing when answer is "Yes"
    yes_pricing_type = models.CharField(max_length=20, choices=PRICING_TYPES, default='ignore')
    yes_value = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Fixed amount to add/subtract (e.g., 12.00 for $12)"  # Updated help text
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'question_pricing'
        unique_together = ['question', 'package']

    def __str__(self):
        return f"{self.package.name} - {self.question.question_text[:30]}..."


class OptionPricing(models.Model):
    """Pricing rules for question options per package"""
    
    PRICING_TYPES = [
        ('upcharge_percent', 'Fixed Upcharge Amount'),  # Updated label
        ('discount_percent', 'Fixed Discount Amount'),  # Updated label
        ('fixed_price', 'Fixed Price'),
        ('ignore', 'Ignore'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    option = models.ForeignKey(QuestionOption, related_name='pricing_rules', on_delete=models.CASCADE)
    package = models.ForeignKey(Package, related_name='option_pricing', on_delete=models.CASCADE)
    
    pricing_type = models.CharField(max_length=20, choices=PRICING_TYPES, default='ignore')
    value = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Fixed amount to add/subtract (e.g., 12.00 for $12)"  # Updated help text
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'option_pricing'
        unique_together = ['option', 'package']

    def __str__(self):
        return f"{self.package.name} - {self.option.option_text}"

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