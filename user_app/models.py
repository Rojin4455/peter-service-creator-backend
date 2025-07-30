from django.db import models
import uuid
from decimal import Decimal
from service_app.models import Service, Package, Location, Question, QuestionOption
# Add these models to your existing models.py

class Contact(models.Model):
    """Contact model for user submissions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField()
    address = models.TextField()
    latitude = models.DecimalField(max_digits=10, decimal_places=8)
    longitude = models.DecimalField(max_digits=11, decimal_places=8)
    google_place_id = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contacts'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.first_name} - {self.phone_number}"


class Quote(models.Model):
    """Quote model for storing user selections and pricing"""
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('confirmed', 'Confirmed'),
        ('expired', 'Expired'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey(Contact, related_name='quotes', on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='quotes')
    package = models.ForeignKey(Package, on_delete=models.PROTECT, related_name='quotes')
    
    # Nearest location (if within 3km)
    nearest_location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True)
    distance_to_location = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # in km
    
    # Pricing breakdown
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    trip_surcharge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    question_adjustments = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # For quote expiration

    class Meta:
        db_table = 'quotes'
        ordering = ['-created_at']

    def __str__(self):
        return f"Quote {self.id} - {self.contact.first_name} - {self.service.name}"


class QuoteQuestionAnswer(models.Model):
    """Store user answers to questions for each quote"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quote = models.ForeignKey(Quote, related_name='question_answers', on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    
    # For Yes/No questions
    yes_no_answer = models.BooleanField(null=True, blank=True)
    
    # For Option questions
    selected_option = models.ForeignKey(QuestionOption, on_delete=models.PROTECT, null=True, blank=True)
    
    # Price impact from this answer
    price_adjustment = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'quote_question_answers'
        unique_together = ['quote', 'question']

    def __str__(self):
        return f"Quote {self.quote.id} - {self.question.question_text[:30]}..."
