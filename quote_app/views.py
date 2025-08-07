# user_views.py - Views for user-side functionality
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q, Prefetch
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone

from service_app.models import (
    Service, Package, Feature, PackageFeature, Location, 
    Question, QuestionOption, SubQuestion, GlobalSizePackage,
    ServicePackageSizeMapping, QuestionPricing, OptionPricing, SubQuestionPricing
)
from .models import (
    CustomerSubmission, CustomerServiceSelection, CustomerQuestionResponse,
    CustomerOptionResponse, CustomerSubQuestionResponse, CustomerPackageQuote
)
from .serializers import (
    LocationPublicSerializer, ServicePublicSerializer, PackagePublicSerializer,
    QuestionPublicSerializer, GlobalSizePackagePublicSerializer,
    CustomerSubmissionCreateSerializer, CustomerSubmissionDetailSerializer,
    ServiceQuestionResponseSerializer, PricingCalculationRequestSerializer,
    ConditionalQuestionRequestSerializer, CustomerPackageQuoteSerializer
)

# Step 1: Get initial data (locations, services, size ranges)
class InitialDataView(APIView):
    """Get initial data for the quote form"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        locations = Location.objects.filter(is_active=True).order_by('name')
        services = Service.objects.filter(is_active=True).order_by('order', 'name')
        size_ranges = GlobalSizePackage.objects.all().order_by('order', 'min_sqft')
        
        return Response({
            'locations': LocationPublicSerializer(locations, many=True).data,
            'services': ServicePublicSerializer(services, many=True).data,
            'size_ranges': GlobalSizePackagePublicSerializer(size_ranges, many=True).data
        })

# Step 2: Create customer submission
class CustomerSubmissionCreateView(generics.CreateAPIView):
    """Create a new customer submission"""
    queryset = CustomerSubmission.objects.all()
    serializer_class = CustomerSubmissionCreateSerializer
    permission_classes = [AllowAny]
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submission = serializer.save()
        
        return Response({
            'submission_id': submission.id,
            'message': 'Customer information saved successfully'
        }, status=status.HTTP_201_CREATED)

# Step 3: Add services to submission
class AddServicesToSubmissionView(APIView):
    """Add selected services to customer submission"""
    permission_classes = [AllowAny]
    
    def post(self, request, submission_id):
        submission = get_object_or_404(CustomerSubmission, id=submission_id)
        service_ids = request.data.get('service_ids', [])
        
        if not service_ids:
            return Response({'error': 'No services selected'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            with transaction.atomic():
                # Clear existing selections
                submission.customerserviceselection_set.all().delete()
                
                # Add new selections
                for service_id in service_ids:
                    service = get_object_or_404(Service, id=service_id, is_active=True)
                    CustomerServiceSelection.objects.create(
                        submission=submission,
                        service=service
                    )
                
                return Response({'message': 'Services added successfully'})
        
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

# Step 4: Get questions for a specific service
class ServiceQuestionsView(APIView):
    """Get questions for a specific service"""
    permission_classes = [AllowAny]
    
    def get(self, request, service_id):
        service = get_object_or_404(Service, id=service_id, is_active=True)
        
        # Get root questions (no parent)
        root_questions = Question.objects.filter(
            service=service,
            is_active=True,
            parent_question__isnull=True
        ).prefetch_related(
            'options',
            'sub_questions',
            'child_questions__options',
            'child_questions__sub_questions'
        ).order_by('order')
        
        serializer = QuestionPublicSerializer(root_questions, many=True, context={'request': request})
        
        return Response({
            'service': {
                'id': service.id,
                'name': service.name,
                'description': service.description
            },
            'questions': serializer.data
        })

# Step 5: Get conditional questions
class ConditionalQuestionsView(APIView):
    """Get conditional questions based on parent answer"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = ConditionalQuestionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        parent_question_id = serializer.validated_data['parent_question_id']
        answer = serializer.validated_data.get('answer')
        option_id = serializer.validated_data.get('option_id')
        
        parent_question = get_object_or_404(Question, id=parent_question_id)
        
        # Build filter for conditional questions
        filter_kwargs = {
            'parent_question': parent_question,
            'is_active': True
        }
        
        if answer:
            filter_kwargs['condition_answer'] = answer
        if option_id:
            filter_kwargs['condition_option_id'] = option_id
        
        conditional_questions = Question.objects.filter(**filter_kwargs).prefetch_related(
            'options',
            'sub_questions'
        ).order_by('order')
        
        questions_serializer = QuestionPublicSerializer(conditional_questions, many=True, context={'request': request})
        
        return Response({
            'parent_question_id': parent_question_id,
            'conditional_questions': questions_serializer.data
        })

# Step 6: Submit service responses and calculate pricing
class SubmitServiceResponsesView(APIView):
    """Submit responses for a service and calculate pricing"""
    permission_classes = [AllowAny]
    
    def post(self, request, submission_id, service_id):
        submission = get_object_or_404(CustomerSubmission, id=submission_id)
        service_selection = get_object_or_404(
            CustomerServiceSelection, 
            submission=submission, 
            service_id=service_id
        )
        
        responses = request.data.get('responses', [])
        
        try:
            with transaction.atomic():
                # Clear existing responses
                service_selection.question_responses.all().delete()
                
                total_adjustment = Decimal('0.00')
                
                # Process each response
                for response_data in responses:
                    question_id = response_data['question_id']
                    question = get_object_or_404(Question, id=question_id)
                    
                    # Create question response
                    question_response = CustomerQuestionResponse.objects.create(
                        service_selection=service_selection,
                        question=question,
                        yes_no_answer=response_data.get('yes_no_answer'),
                        text_answer=response_data.get('text_answer', '')
                    )
                    
                    question_adjustment = self._calculate_question_adjustment(
                        question, response_data, question_response, service_selection
                    )
                    
                    question_response.price_adjustment = question_adjustment
                    question_response.save()
                    
                    total_adjustment += question_adjustment
                
                # Update service selection totals
                service_selection.question_adjustments = total_adjustment
                service_selection.save()
                
                # Generate package quotes
                self._generate_package_quotes(service_selection, submission)
                
                return Response({'message': 'Responses submitted successfully'})
        
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    def _calculate_question_adjustment(self, question, response_data, question_response, service_selection):
        """Calculate price adjustment for a question response"""
        total_adjustment = Decimal('0.00')
        
        # Get all packages for this service
        packages = Package.objects.filter(service=question.service, is_active=True)
        
        if question.question_type == 'yes_no':
            if response_data.get('yes_no_answer') is True:
                for package in packages:
                    pricing = QuestionPricing.objects.filter(
                        question=question, package=package
                    ).first()
                    if pricing and pricing.yes_pricing_type != 'ignore':
                        total_adjustment += pricing.yes_value
        
        elif question.question_type in ['describe', 'quantity']:
            selected_options = response_data.get('selected_options', [])
            for option_data in selected_options:
                option_id = option_data['option_id']
                quantity = option_data.get('quantity', 1)
                
                option = get_object_or_404(QuestionOption, id=option_id)
                
                # Create option response
                option_response = CustomerOptionResponse.objects.create(
                    question_response=question_response,
                    option=option,
                    quantity=quantity
                )
                
                # Calculate option pricing
                option_adjustment = Decimal('0.00')
                for package in packages:
                    pricing = OptionPricing.objects.filter(
                        option=option, package=package
                    ).first()
                    if pricing and pricing.pricing_type != 'ignore':
                        if pricing.pricing_type == 'per_quantity':
                            option_adjustment += pricing.value * quantity
                        else:
                            option_adjustment += pricing.value
                
                option_response.price_adjustment = option_adjustment
                option_response.save()
                total_adjustment += option_adjustment
        
        elif question.question_type == 'multiple_yes_no':
            sub_question_answers = response_data.get('sub_question_answers', [])
            for sub_answer in sub_question_answers:
                if sub_answer.get('answer') is True:
                    sub_question_id = sub_answer['sub_question_id']
                    sub_question = get_object_or_404(SubQuestion, id=sub_question_id)
                    
                    # Create sub-question response
                    sub_response = CustomerSubQuestionResponse.objects.create(
                        question_response=question_response,
                        sub_question=sub_question,
                        answer=True
                    )
                    
                    # Calculate sub-question pricing
                    sub_adjustment = Decimal('0.00')
                    for package in packages:
                        pricing = SubQuestionPricing.objects.filter(
                            sub_question=sub_question, package=package
                        ).first()
                        if pricing and pricing.yes_pricing_type != 'ignore':
                            sub_adjustment += pricing.yes_value
                    
                    sub_response.price_adjustment = sub_adjustment
                    sub_response.save()
                    total_adjustment += sub_adjustment
        
        return total_adjustment
    
    def _generate_package_quotes(self, service_selection, submission):
        """Generate package quotes for the service"""
        service = service_selection.service
        packages = Package.objects.filter(service=service, is_active=True)
        
        # Get square footage pricing
        sqft_mappings = ServicePackageSizeMapping.objects.filter(
            service_package__service=service,
            global_size__min_sqft__lte=submission.house_sqft,
            global_size__max_sqft__gte=submission.house_sqft
        ).select_related('service_package', 'global_size')
        
        # Create mapping dict for quick lookup
        sqft_pricing = {mapping.service_package_id: mapping.price for mapping in sqft_mappings}
        
        # Check if location surcharge applies
        surcharge_amount = Decimal('0.00')
        if submission.location and hasattr(service, 'settings'):
            settings = service.settings
            if settings.apply_trip_charge_to_bid:
                surcharge_amount = submission.location.trip_surcharge
                service_selection.surcharge_applicable = True
                service_selection.surcharge_amount = surcharge_amount
                service_selection.save()
        
        # Generate quotes for each package
        for package in packages:
            base_price = package.base_price
            sqft_price = sqft_pricing.get(package.id, Decimal('0.00'))
            question_adjustments = service_selection.question_adjustments
            
            total_price = base_price + sqft_price + question_adjustments + surcharge_amount
            
            # Get package features
            package_features = PackageFeature.objects.filter(package=package).select_related('feature')
            
            # Convert UUIDs to strings here
            included_features = [str(pf.feature.id) for pf in package_features if pf.is_included]
            excluded_features = [str(pf.feature.id) for pf in package_features if not pf.is_included]
            
            CustomerPackageQuote.objects.update_or_create(
                service_selection=service_selection,
                package=package,
                defaults={
                    'base_price': base_price,
                    'sqft_price': sqft_price,
                    'question_adjustments': question_adjustments,
                    'surcharge_amount': surcharge_amount,
                    'total_price': total_price,
                    'included_features': included_features,
                    'excluded_features': excluded_features
                }
            )

# Step 7: Get submission details with quotes
class SubmissionDetailView(generics.RetrieveAPIView):
    """Get detailed submission with all quotes"""
    queryset = CustomerSubmission.objects.all()
    serializer_class = CustomerSubmissionDetailSerializer
    permission_classes = [AllowAny]
    lookup_field = 'id'
    
    def get_object(self):
        submission_id = self.kwargs['id']
        return get_object_or_404(
            CustomerSubmission.objects.prefetch_related(
                'customerserviceselection_set__service',
                'customerserviceselection_set__package_quotes__package',
                'customerserviceselection_set__question_responses__question',
                'customerserviceselection_set__question_responses__option_responses__option',
                'customerserviceselection_set__question_responses__sub_question_responses__sub_question'
            ),
            id=submission_id
        )

# Step 8: Submit final quote
class SubmitFinalQuoteView(APIView):
    """Submit the final quote"""
    permission_classes = [AllowAny]
    
    def post(self, request, submission_id):
        submission = get_object_or_404(CustomerSubmission, id=submission_id)
        
        try:
            with transaction.atomic():
                # Calculate final totals
                service_selections = submission.customerserviceselection_set.all()
                
                total_base_price = Decimal('0.00')
                total_adjustments = Decimal('0.00')
                total_surcharges = Decimal('0.00')
                
                for selection in service_selections:
                    quotes = selection.package_quotes.all()
                    if quotes:
                        # Use the first package as default (you might want to let user choose)
                        quote = quotes.first()
                        total_base_price += quote.base_price + quote.sqft_price
                        total_adjustments += quote.question_adjustments
                        total_surcharges += quote.surcharge_amount
                
                final_total = total_base_price + total_adjustments + total_surcharges
                
                # Update submission
                submission.total_base_price = total_base_price
                submission.total_adjustments = total_adjustments
                submission.total_surcharges = total_surcharges
                submission.final_total = final_total
                submission.status = 'submitted'
                submission.save()
                
                return Response({
                    'message': 'Quote submitted successfully',
                    'submission_id': submission.id,
                    'final_total': final_total,
                    'quote_url': f'/quote/{submission.id}/'
                })
        
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

# Utility views
class SubmissionStatusView(APIView):
    """Check submission status"""
    permission_classes = [AllowAny]
    
    def get(self, request, submission_id):
        submission = get_object_or_404(CustomerSubmission, id=submission_id)
        
        # Check if expired
        if submission.expires_at and submission.expires_at < timezone.now():
            submission.status = 'expired'
            submission.save()
        
        return Response({
            'id': submission.id,
            'status': submission.status,
            'expires_at': submission.expires_at,
            'created_at': submission.created_at
        })

class ServicePackagesView(APIView):
    """Get packages for a specific service"""
    permission_classes = [AllowAny]
    
    def get(self, request, service_id):
        service = get_object_or_404(Service, id=service_id, is_active=True)
        packages = Package.objects.filter(service=service, is_active=True).order_by('order')
        
        return Response({
            'service': ServicePublicSerializer(service).data,
            'packages': PackagePublicSerializer(packages, many=True).data
        })
