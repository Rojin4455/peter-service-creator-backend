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
    ConditionalQuestionRequestSerializer, CustomerPackageQuoteSerializer,ConditionalQuestionResponseSerializer,ServiceResponseSubmissionSerializer
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
    """Submit responses for a service including conditional questions"""
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
                # Validate conditional question logic first
                validation_result = self._validate_conditional_responses(responses, service_id)
                if not validation_result['valid']:
                    return Response({
                        'error': 'Invalid conditional question responses',
                        'details': validation_result['errors']
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # Clear existing responses
                service_selection.question_responses.all().delete()
                
                # Process responses in dependency order (parents first, then children)
                ordered_responses = self._order_responses_by_dependency(responses)
                
                total_adjustment = Decimal('0.00')
                
                for response_data in ordered_responses:
                    question_id = response_data['question_id']
                    question = get_object_or_404(Question, id=question_id)
                    
                    # Create question response
                    question_response = CustomerQuestionResponse.objects.create(
                        service_selection=service_selection,
                        question=question,
                        yes_no_answer=response_data.get('yes_no_answer'),
                        text_answer=response_data.get('text_answer', '')
                    )
                    
                    # Calculate pricing adjustment
                    question_adjustment = self._calculate_question_adjustment(
                        question, response_data, question_response, service_selection
                    )
                    
                    question_response.price_adjustment = question_adjustment
                    question_response.save()
                    
                    total_adjustment += question_adjustment
                
                # Update service selection totals
                service_selection.question_adjustments = total_adjustment
                service_selection.save()
                
                # Generate package quotes for ALL packages
                self._generate_all_package_quotes(service_selection, submission)
                
                # Check if all services have responses
                all_services_completed = self._check_all_services_completed(submission)
                all_services_completed = True
                if all_services_completed:
                    submission.status = 'responses_completed'
                    submission.save()
                
                return Response({
                    'message': 'Responses submitted successfully',
                    'all_services_completed': all_services_completed,
                    'total_questions_answered': len(ordered_responses),
                    'conditional_questions_answered': len([r for r in responses if r.get('parent_question_id')])
                })
        
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    def _validate_conditional_responses(self, responses, service_id):
        """Validate that conditional questions are only answered when conditions are met"""
        validation_errors = []
        
        # Create lookup maps
        responses_by_question = {r['question_id']: r for r in responses}
        
        for response in responses:
            question_id = response['question_id']
            
            # Skip validation for non-conditional questions
            if not response.get('parent_question_id'):
                continue
                
            try:
                question = Question.objects.get(id=question_id)
                parent_question_id = response['parent_question_id']
                
                # Check if parent question was answered
                if parent_question_id not in responses_by_question:
                    validation_errors.append(
                        f"Conditional question {question_id} answered but parent {parent_question_id} not found"
                    )
                    continue
                
                parent_response = responses_by_question[parent_question_id]
                parent_question = Question.objects.get(id=parent_question_id)
                
                # Validate condition based on type
                condition_met = self._check_condition_met(
                    parent_question, parent_response, question, response
                )
                
                if not condition_met:
                    validation_errors.append(
                        f"Conditional question {question_id} answered but condition not met"
                    )
                    
            except Question.DoesNotExist:
                validation_errors.append(f"Question {question_id} not found")
        
        return {
            'valid': len(validation_errors) == 0,
            'errors': validation_errors
        }
    
    def _check_condition_met(self, parent_question, parent_response, conditional_question, conditional_response):
        """Check if the condition for a conditional question is met"""
        
        # For yes/no parent questions
        if parent_question.question_type == 'yes_no':
            expected_answer = conditional_question.condition_answer
            actual_answer = 'yes' if parent_response.get('yes_no_answer') else 'no'
            return expected_answer == actual_answer
        
        # For option-based parent questions (describe/quantity)
        elif parent_question.question_type in ['describe', 'quantity']:
            expected_option_id = str(conditional_question.condition_option_id) if conditional_question.condition_option_id else None
            selected_options = parent_response.get('selected_options', [])
            selected_option_ids = [str(opt['option_id']) for opt in selected_options]
            
            return expected_option_id in selected_option_ids
        
        # For multiple_yes_no parent questions
        elif parent_question.question_type == 'multiple_yes_no':
            # This would need custom logic based on your requirements
            # For now, assume condition is met if any sub-question is answered yes
            sub_answers = parent_response.get('sub_question_answers', [])
            return any(sub['answer'] for sub in sub_answers)
        
        return False
    
    def _order_responses_by_dependency(self, responses):
        """Order responses so parent questions are processed before conditional questions"""
        parent_responses = []
        conditional_responses = []
        
        for response in responses:
            if response.get('parent_question_id'):
                conditional_responses.append(response)
            else:
                parent_responses.append(response)
        
        # Sort conditional responses by their parent order
        conditional_responses.sort(key=lambda x: x.get('parent_question_id', ''))
        
        return parent_responses + conditional_responses
    
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


    def _generate_all_package_quotes(self, service_selection, submission):
        """Generate quotes for ALL packages in the service"""
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
            try:
                settings = service.settings
                if settings.apply_trip_charge_to_bid:
                    surcharge_amount = submission.location.trip_surcharge
                    service_selection.surcharge_applicable = True
                    service_selection.surcharge_amount = surcharge_amount
                    service_selection.save()
            except ServiceSettings.DoesNotExist:
                # Service doesn't have settings, no surcharge
                pass
        
        # Clear existing quotes for this service
        service_selection.package_quotes.all().delete()
        
        # Generate quotes for each package
        for package in packages:
            base_price = package.base_price
            sqft_price = sqft_pricing.get(package.id, Decimal('0.00'))
            
            # Calculate package-specific question adjustments
            question_adjustments = self._calculate_package_specific_adjustments(
                service_selection, package
            )
            
            total_price = base_price + sqft_price + question_adjustments + surcharge_amount
            
            # Get package features
            package_features = PackageFeature.objects.filter(package=package).select_related('feature')
            included_features = [str(pf.feature.id) for pf in package_features if pf.is_included]
            excluded_features = [str(pf.feature.id) for pf in package_features if not pf.is_included]
            
            CustomerPackageQuote.objects.create(
                service_selection=service_selection,
                package=package,
                base_price=base_price,
                sqft_price=sqft_price,
                question_adjustments=question_adjustments,
                surcharge_amount=surcharge_amount,
                total_price=total_price,
                included_features=included_features,
                excluded_features=excluded_features,
                is_selected=False  # Initially not selected
            )

    def _calculate_package_specific_adjustments(self, service_selection, package):
        """Calculate question adjustments specific to a package"""
        total_adjustment = Decimal('0.00')
        
        for question_response in service_selection.question_responses.all():
            question = question_response.question
            
            # Handle different question types
            if question.question_type == 'yes_no':
                if question_response.yes_no_answer is True:
                    pricing = QuestionPricing.objects.filter(
                        question=question, package=package
                    ).first()
                    if pricing and pricing.yes_pricing_type != 'ignore':
                        if pricing.yes_pricing_type == 'upcharge_percent':
                            total_adjustment += pricing.yes_value
                        elif pricing.yes_pricing_type == 'discount_percent':
                            total_adjustment -= pricing.yes_value
                        elif pricing.yes_pricing_type == 'fixed_price':
                            total_adjustment += pricing.yes_value
            
            elif question.question_type in ['describe', 'quantity']:
                for option_response in question_response.option_responses.all():
                    pricing = OptionPricing.objects.filter(
                        option=option_response.option, package=package
                    ).first()
                    if pricing and pricing.pricing_type != 'ignore':
                        if pricing.pricing_type == 'per_quantity':
                            adjustment = pricing.value * option_response.quantity
                        elif pricing.pricing_type == 'upcharge_percent':
                            adjustment = pricing.value
                        elif pricing.pricing_type == 'discount_percent':
                            adjustment = -pricing.value
                        elif pricing.pricing_type == 'fixed_price':
                            adjustment = pricing.value
                        else:
                            adjustment = pricing.value
                        
                        total_adjustment += adjustment
            
            elif question.question_type == 'multiple_yes_no':
                for sub_response in question_response.sub_question_responses.all():
                    if sub_response.answer is True:
                        pricing = SubQuestionPricing.objects.filter(
                            sub_question=sub_response.sub_question, package=package
                        ).first()
                        if pricing and pricing.yes_pricing_type != 'ignore':
                            if pricing.yes_pricing_type == 'upcharge_percent':
                                total_adjustment += pricing.yes_value
                            elif pricing.yes_pricing_type == 'discount_percent':
                                total_adjustment -= pricing.yes_value
                            elif pricing.yes_pricing_type == 'fixed_price':
                                total_adjustment += pricing.yes_value
            
            # Handle conditional questions
            elif question.question_type == 'conditional':
                # Check if the condition is met before applying pricing
                if self._is_conditional_question_condition_met(question_response, service_selection):
                    if question_response.yes_no_answer is True:
                        pricing = QuestionPricing.objects.filter(
                            question=question, package=package
                        ).first()
                        if pricing and pricing.yes_pricing_type != 'ignore':
                            if pricing.yes_pricing_type == 'upcharge_percent':
                                total_adjustment += pricing.yes_value
                            elif pricing.yes_pricing_type == 'discount_percent':
                                total_adjustment -= pricing.yes_value
                            elif pricing.yes_pricing_type == 'fixed_price':
                                total_adjustment += pricing.yes_value
        
        return total_adjustment

    def _is_conditional_question_condition_met(self, question_response, service_selection):
        """Check if a conditional question's condition is met"""
        question = question_response.question
        
        if not question.parent_question:
            return True  # Not a conditional question
        
        # Find the parent question response
        parent_response = service_selection.question_responses.filter(
            question=question.parent_question
        ).first()
        
        if not parent_response:
            return False  # Parent not answered
        
        # Check condition based on parent question type
        if question.parent_question.question_type == 'yes_no':
            expected_answer = question.condition_answer
            actual_answer = 'yes' if parent_response.yes_no_answer else 'no'
            return expected_answer == actual_answer
        
        elif question.parent_question.question_type in ['describe', 'quantity']:
            if question.condition_option:
                # Check if the specific option was selected
                selected_options = parent_response.option_responses.all()
                selected_option_ids = [opt.option.id for opt in selected_options]
                return question.condition_option.id in selected_option_ids
        
        return False

    def _check_all_services_completed(self, submission):
        """Check if all selected services have responses"""
        service_selections = submission.customerserviceselection_set.all()
        
        for selection in service_selections:
            # Check if this service has any question responses
            if not selection.question_responses.exists():
                return False
            
            # Get all root questions (non-conditional) for this service
            root_questions = Question.objects.filter(
                service=selection.service,
                is_active=True,
                parent_question__isnull=True
            )
            
            # Check if all root questions have responses
            answered_question_ids = set(
                selection.question_responses.values_list('question_id', flat=True)
            )
            
            for root_question in root_questions:
                if root_question.id not in answered_question_ids:
                    return False
                
                # Check conditional questions if they should be answered
                conditional_questions = Question.objects.filter(
                    parent_question=root_question,
                    is_active=True
                )
                
                for conditional_question in conditional_questions:
                    # Check if condition is met
                    root_response = selection.question_responses.filter(
                        question=root_question
                    ).first()
                    
                    if self._should_conditional_question_be_answered(
                        conditional_question, root_response
                    ):
                        if conditional_question.id not in answered_question_ids:
                            return False
        
        return True

    def _should_conditional_question_be_answered(self, conditional_question, parent_response):
        """Check if a conditional question should be answered based on parent response"""
        if not parent_response:
            return False
        
        parent_question = conditional_question.parent_question
        
        # For yes/no parent questions
        if parent_question.question_type == 'yes_no':
            expected_answer = conditional_question.condition_answer
            actual_answer = 'yes' if parent_response.yes_no_answer else 'no'
            return expected_answer == actual_answer
        
        # For option-based parent questions
        elif parent_question.question_type in ['describe', 'quantity']:
            if conditional_question.condition_option:
                selected_options = parent_response.option_responses.all()
                selected_option_ids = [opt.option.id for opt in selected_options]
                return conditional_question.condition_option.id in selected_option_ids
        
        # For multiple_yes_no parent questions
        elif parent_question.question_type == 'multiple_yes_no':
            # This would depend on your specific business logic
            # For example, show conditional if any sub-question is answered yes
            sub_responses = parent_response.sub_question_responses.all()
            return any(sub.answer for sub in sub_responses)
        
        return False


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
