# views.py
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from decimal import Decimal

from .models import (
    Contact, Service, Package, Question, Quote, 
    QuoteQuestionAnswer, QuestionOption
)
from .serializers import (
    ContactSerializer, ServiceListSerializer, ServiceSerializer,
    QuestionSerializer, QuoteSerializer, QuoteCreateSerializer
)
from .utils import calculate_total_quote_price
from service_app.serializers import PackageSerializer


# Step 1: Submit Contact Info
class ContactCreateView(generics.CreateAPIView):
    """Create a new contact"""
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    permission_classes = [AllowAny]


# Step 2: List All Services
class ServiceListView(generics.ListAPIView):
    """List all active services"""
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceListSerializer
    permission_classes = [AllowAny]


# Step 3: Get Service Details with Packages
class ServiceDetailView(generics.RetrieveAPIView):
    """Get service details with all packages and features"""
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceSerializer
    permission_classes = [AllowAny]
    lookup_field = 'id'


# Step 4: Get Package Details (Optional - if you need individual package info)
class PackageDetailView(generics.RetrieveAPIView):
    """Get package details"""
    queryset = Package.objects.filter(is_active=True)
    serializer_class = PackageSerializer
    permission_classes = [AllowAny]
    lookup_field = 'id'


# Step 5: Get Questions for a Service
class ServiceQuestionsView(generics.ListAPIView):
    """Get all questions for a specific service"""
    serializer_class = QuestionSerializer
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        service_id = self.kwargs['service_id']
        return Question.objects.filter(
            service_id=service_id, 
            is_active=True
        ).order_by('order', 'created_at')


# Step 6: Create Quote (Checkout Summary)
class QuoteCreateView(generics.CreateAPIView):
    """Create a quote with all selections and calculate pricing"""
    serializer_class = QuoteCreateSerializer
    permission_classes = [AllowAny]
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        validated_data = serializer.validated_data
        contact = validated_data['contact']
        service = validated_data['service']
        package = validated_data['package']
        answers_data = validated_data.get('answers', [])
        
        # Calculate pricing
        price_breakdown = calculate_total_quote_price(
            contact, package, answers_data
        )
        
        # Create quote
        quote = Quote.objects.create(
            contact=contact,
            service=service,
            package=package,
            nearest_location=price_breakdown['nearest_location'],
            distance_to_location=price_breakdown['distance_to_location'],
            base_price=price_breakdown['base_price'],
            trip_surcharge=price_breakdown['trip_surcharge'],
            question_adjustments=price_breakdown['question_adjustments'],
            total_price=price_breakdown['total_price'],
            status='draft'
        )
        
        # Create question answers
        for answer_data in answers_data:
            question_id = answer_data['question_id']
            
            try:
                question = service.questions.get(id=question_id, is_active=True)
            except Question.DoesNotExist:
                continue
            
            # Calculate individual price adjustment for this answer
            price_adjustment = Decimal('0.00')
            selected_option = None
            yes_no_answer = None
            
            if question.question_type == 'yes_no':
                yes_no_answer = answer_data.get('yes_no_answer', False)
                from .utils import calculate_question_price_adjustment
                price_adjustment = calculate_question_price_adjustment(
                    question, yes_no_answer, package
                )
                
            elif question.question_type == 'options':
                option_id = answer_data.get('selected_option_id')
                if option_id:
                    try:
                        selected_option = question.options.get(id=option_id, is_active=True)
                        from .utils import calculate_option_price_adjustment
                        price_adjustment = calculate_option_price_adjustment(
                            selected_option, package
                        )
                    except QuestionOption.DoesNotExist:
                        continue
            
            QuoteQuestionAnswer.objects.create(
                quote=quote,
                question=question,
                yes_no_answer=yes_no_answer,
                selected_option=selected_option,
                price_adjustment=price_adjustment
            )
        
        # Return quote details
        quote_serializer = QuoteSerializer(quote)
        return Response(quote_serializer.data, status=status.HTTP_201_CREATED)


# Get Quote Details
class QuoteDetailView(generics.RetrieveAPIView):
    """Get quote details"""
    queryset = Quote.objects.all()
    serializer_class = QuoteSerializer
    permission_classes = [AllowAny]
    lookup_field = 'id'


# Update Quote Status (for admin use or future features)
@api_view(['PATCH'])
@permission_classes([AllowAny])
def update_quote_status(request, quote_id):
    """Update quote status"""
    quote = get_object_or_404(Quote, id=quote_id)
    
    new_status = request.data.get('status')
    if new_status not in dict(Quote.STATUS_CHOICES):
        return Response(
            {'error': 'Invalid status'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    quote.status = new_status
    quote.save()
    
    serializer = QuoteSerializer(quote)
    return Response(serializer.data)


# Price Calculator Endpoint (Optional - for real-time price updates)
@api_view(['POST'])
@permission_classes([AllowAny])
def calculate_price(request):
    """Calculate price without creating a quote"""
    serializer = QuoteCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    validated_data = serializer.validated_data
    contact = validated_data['contact']
    package = validated_data['package']
    answers_data = validated_data.get('answers', [])
    
    price_breakdown = calculate_total_quote_price(
        contact, package, answers_data
    )
    
    return Response({
        'base_price': str(price_breakdown['base_price']),
        'trip_surcharge': str(price_breakdown['trip_surcharge']),
        'question_adjustments': str(price_breakdown['question_adjustments']),
        'total_price': str(price_breakdown['total_price']),
        'nearest_location': price_breakdown['nearest_location'].name if price_breakdown['nearest_location'] else None,
        'distance_to_location': str(price_breakdown['distance_to_location']) if price_breakdown['distance_to_location'] else None
    })


# Get Contact's Quotes
class ContactQuotesView(generics.ListAPIView):
    """Get all quotes for a contact"""
    serializer_class = QuoteSerializer
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        contact_id = self.kwargs['contact_id']
        return Quote.objects.filter(contact_id=contact_id)