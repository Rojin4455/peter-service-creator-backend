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
from service_app.models import ServiceSettings
from service_app.models import (
    Service, Package, Feature, PackageFeature, Location,
    Question, QuestionOption, SubQuestion, GlobalSizePackage,
    ServicePackageSizeMapping, QuestionPricing, OptionPricing, SubQuestionPricing,QuantityDiscount, AddOnService
)
from django.db.models import Sum
from .models import (
    CustomerSubmission, CustomerServiceSelection, CustomerQuestionResponse,
    CustomerOptionResponse, CustomerSubQuestionResponse, CustomerPackageQuote
)
from .serializers import (
    LocationPublicSerializer, ServicePublicSerializer, PackagePublicSerializer,
    QuestionPublicSerializer, GlobalSizePackagePublicSerializer,
    CustomerSubmissionCreateSerializer, CustomerSubmissionDetailSerializer,AddOnServiceSerializer,
    ServiceQuestionResponseSerializer, PricingCalculationRequestSerializer,SubmitFinalQuoteSerializer,
    ConditionalQuestionRequestSerializer, CustomerPackageQuoteSerializer,ConditionalQuestionResponseSerializer,ServiceResponseSubmissionSerializer
)

from service_app.serializers import GlobalSizePackageSerializer

from quote_app.helpers import create_or_update_ghl_contact

# Step 1: Get initial data (locations, services, size ranges)
class InitialDataView(APIView):
    """Get initial data for the quote form"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        property_type = request.query_params.get('property_type')  # ?property_type=<uuid>

        locations = Location.objects.filter(is_active=True).order_by('name')
        services = Service.objects.filter(is_active=True).order_by('order', 'name')

        size_ranges = GlobalSizePackage.objects.all().order_by('order', 'min_sqft')
        if property_type:
            size_ranges = size_ranges.filter(property_type__name=property_type)

        return Response({
            'locations': LocationPublicSerializer(locations, many=True).data,
            'services': ServicePublicSerializer(services, many=True).data,
            'size_ranges': GlobalSizePackagePublicSerializer(size_ranges, many=True).data,
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
            "submission_id": str(submission.id),
            "message": "Customer information saved successfully"
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
                # submission.customerserviceselection_set.all().delete()
                CustomerServiceSelection.objects.filter(
                    submission=submission
                ).exclude(service_id__in=service_ids).delete()
                
                # Add new selections
                for service_id in service_ids:
                    service = get_object_or_404(Service, id=service_id, is_active=True)
                    CustomerServiceSelection.objects.get_or_create(
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

        self.bid_in_person=False
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
                    
                    # Process response data and store related objects
                    self._process_question_response_data(question, response_data, question_response)
                    
                    # Calculate pricing adjustment (for averaging only)
                    question_adjustment = self._calculate_question_adjustment_for_averaging(
                        question, response_data, question_response, service_selection
                    )
                    
                    question_response.price_adjustment = question_adjustment
                    question_response.save()
                    
                    total_adjustment += question_adjustment
                
                # Update service selection totals (this is just for averaging display)
                service_selection.question_adjustments = total_adjustment
                service_selection.save()
                
                surcharge_for_submission = False
                # Generate package quotes for ALL packages
                surcharge_applied, surcharge_price = self._generate_all_package_quotes(service_selection, submission)
                
                print("+++++++++++++surcharge_applied, surcharge_price++++++++++",surcharge_applied, surcharge_price)
                if surcharge_applied:
                    surcharge_for_submission = True

                # After all services processed

                    
                    
                
                # Check if all services have responses
                all_services_completed = self._check_all_services_completed(submission)
                if all_services_completed:
                    submission.status = 'responses_completed'
                    submission.save()
                if surcharge_for_submission:
                    submission.quote_surcharge_applicable = True
                    submission.total_surcharges = surcharge_price
                
                submission.is_bid_in_person = self.bid_in_person
                submission.save()
                print("submission.total_surcharges",submission.total_surcharges)
                create_or_update_ghl_contact(submission)
                
                return Response({
                    'message': 'Responses submitted successfully',
                    'all_services_completed': all_services_completed,
                    'total_questions_answered': len(ordered_responses),
                    'conditional_questions_answered': len([r for r in responses if r.get('parent_question_id')])
                })
        
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    def _process_question_response_data(self, question, response_data, question_response):
        """Process and store response data for different question types"""
        if question.question_type in ['describe', 'quantity']:
            selected_options = response_data.get('selected_options', [])
            
            # Use set to prevent duplicates
            processed_options = set()
            
            for option_data in selected_options:
                option_id = option_data['option_id']
                quantity = option_data.get('quantity', 1)
                
                # Create unique key to prevent duplicates
                option_key = f"{option_id}_{quantity}"
                if option_key in processed_options:
                    continue
                processed_options.add(option_key)
                
                option = get_object_or_404(QuestionOption, id=option_id)
                
                CustomerOptionResponse.objects.create(
                    question_response=question_response,
                    option=option,
                    quantity=quantity
                )
        
        elif question.question_type == 'multiple_yes_no':
            sub_question_answers = response_data.get('sub_question_answers', [])
            
            # Use set to prevent duplicates
            processed_sub_questions = set()
            
            for sub_answer in sub_question_answers:
                if sub_answer.get('answer') is True:
                    sub_question_id = sub_answer['sub_question_id']
                    
                    if sub_question_id in processed_sub_questions:
                        continue
                    processed_sub_questions.add(sub_question_id)
                    
                    sub_question = get_object_or_404(SubQuestion, id=sub_question_id)
                    
                    CustomerSubQuestionResponse.objects.create(
                        question_response=question_response,
                        sub_question=sub_question,
                        answer=True
                    )
    
    def _calculate_question_adjustment_for_averaging(self, question, response_data, question_response, service_selection):
        """Calculate average adjustment across packages (for display only)"""
        packages = Package.objects.filter(service=question.service, is_active=True)
        if not packages.exists():
            return Decimal('0.00')
        
        total_adjustment = Decimal('0.00')
        package_count = 0
        
        for package in packages:
            # Get package-specific sqft price
            package_sqft_price = self._get_package_sqft_price(service_selection.submission, package)
            
            package_adjustment = self._calculate_single_package_adjustment(
                question, response_data, question_response, package, package_sqft_price
            )
            total_adjustment += package_adjustment
            package_count += 1
        
        return total_adjustment / package_count if package_count > 0 else Decimal('0.00')
    
    def _get_package_sqft_price(self, submission, package):
        """Get the package-specific square footage price"""
        if not submission.size_range:
            return Decimal('0.00')
            
        sqft_mapping = ServicePackageSizeMapping.objects.filter(
            service_package=package,
            global_size=submission.size_range
        ).first()

        print("sqft_mapping.price: ", sqft_mapping.price)
        
        return sqft_mapping.price if sqft_mapping else Decimal('0.00')
    
    def _calculate_single_package_adjustment(self, question, response_data, question_response, package, base_sqft_price):
        """Calculate adjustment for a single package"""
        package_adjustment = Decimal('0.00')
        
        if question.question_type == 'yes_no':
            if response_data.get('yes_no_answer') is True:
                pricing = QuestionPricing.objects.filter(
                    question=question, package=package
                ).first()
                if pricing and pricing.yes_pricing_type not in ['ignore', 'fixed_price']:
                    package_adjustment = self._apply_pricing_rule(
                        pricing.yes_pricing_type, pricing.yes_value,
                        pricing.value_type, base_sqft_price
                    )
        
        elif question.question_type in ['describe', 'quantity']:
            # Use stored responses to prevent duplication
            package_adjustment = self._calculate_options_question_adjustment_from_stored(
                question_response, package, base_sqft_price
            )
        
        elif question.question_type == 'multiple_yes_no':
            # Use stored responses to prevent duplication
            package_adjustment = self._calculate_sub_questions_adjustment_from_stored(
                question_response, package, base_sqft_price
            )
        
        elif question.question_type == 'conditional':
            # Handle conditional questions (same as yes_no for now)
            if response_data.get('yes_no_answer') is True:
                pricing = QuestionPricing.objects.filter(
                    question=question, package=package
                ).first()
                if pricing and pricing.yes_pricing_type not in ['ignore', 'fixed_price']:
                    package_adjustment = self._apply_pricing_rule(
                        pricing.yes_pricing_type, pricing.yes_value,
                        pricing.value_type, base_sqft_price
                    )
        
        return package_adjustment
    
    def _calculate_options_question_adjustment_from_stored(self, question_response, package, base_sqft_price):
        """Calculate adjustment for options question using stored responses (prevents duplication)"""
        total_adjustment = Decimal('0.00')
        total_quantity = 0
        
        # Calculate base adjustments and total quantity from stored responses
        option_adjustments = {}
        for option_response in question_response.option_responses.all():
            option = option_response.option
            quantity = option_response.quantity
            total_quantity += quantity
            
            pricing = OptionPricing.objects.filter(
                option=option, package=package
            ).first()
            
            if pricing and pricing.pricing_type not in ['ignore', 'fixed_price']:
                base_adjustment = self._apply_pricing_rule(
                    pricing.pricing_type, pricing.value,
                    pricing.value_type, base_sqft_price, quantity
                )
                option_adjustments[str(option.id)] = {
                    'base_adjustment': base_adjustment,
                    'quantity': quantity,
                    'option': option
                }
                total_adjustment += base_adjustment
            elif pricing and pricing.pricing_type in ['fixed_price']:
                print("reached herererreeerererererereerererrrrrrrr122")
                self.bid_in_person=True
        
        
        # Apply quantity discounts if this is a quantity question
        if question_response.question.question_type == 'quantity':
            total_adjustment = self._apply_quantity_discounts(
                question_response.question, option_adjustments, total_quantity, total_adjustment
            )
        
        return total_adjustment
    
    def _calculate_sub_questions_adjustment_from_stored(self, question_response, package, base_sqft_price):
        """Calculate adjustment for multiple yes/no questions using stored responses"""
        total_adjustment = Decimal('0.00')
        
        print(f"[DEBUG] Processing sub-questions from stored responses with base_sqft_price={base_sqft_price}")
        
        for sub_response in question_response.sub_question_responses.all():
            if sub_response.answer:  # Only process True answers
                sub_question = sub_response.sub_question
                
                # Get pricing for this sub-question and package
                pricing = SubQuestionPricing.objects.filter(
                    sub_question=sub_question, 
                    package=package
                ).first()
                
                if pricing and pricing.yes_pricing_type not in ['ignore', 'fixed_price']:
                    adjustment = self._apply_pricing_rule(
                        pricing.yes_pricing_type, 
                        pricing.yes_value,
                        pricing.value_type, 
                        base_sqft_price
                    )
                    print(f"[DEBUG] Sub-question {sub_question.id} adjustment: {adjustment}")
                    total_adjustment += adjustment
                elif pricing and pricing.yes_pricing_type in ['fixed_price']:
                    print("reached herererreeerererererereerererrrrrrrr122")
                    self.bid_in_person=True
                    print(f"[DEBUG] Sub-question {sub_question.id} pricing ignored or not found")
        
        print(f"[DEBUG] Total sub-questions adjustment: {total_adjustment}")
        return total_adjustment
    
    def _apply_pricing_rule(self, pricing_type, value, value_type, base_sqft_price, quantity=1):
        """Apply pricing rule based on type and value type"""
        if pricing_type in ['ignore', 'fixed_price']:
            return Decimal('0.00')
        
        print(f"[DEBUG] Pricing calculation: type={pricing_type}, value={value}, value_type={value_type}, base_sqft_price={base_sqft_price}, quantity={quantity}")
        
        # Calculate base amount based on value_type
        if value_type == 'percent':
            if base_sqft_price == 0:
                print(f"[DEBUG] Warning: base_sqft_price is 0, percentage calculation will result in 0")
                base_amount = Decimal('0.00')
            else:
                base_amount = base_sqft_price * (Decimal(str(value)) / Decimal('100'))
                print(f"[DEBUG] Percentage calculation: {base_sqft_price} * ({value}/100) = {base_amount}")
        else:
            # Fixed amount
            base_amount = Decimal(str(value))
            print(f"[DEBUG] Fixed amount: {base_amount}")
        
        # Apply quantity multiplier for relevant pricing types
        if pricing_type == 'per_quantity':
            base_amount *= quantity
            print(f"[DEBUG] Applied per_quantity: {base_amount}")
        elif pricing_type in ['upcharge_percent', 'discount_percent', 'fixed_price'] and quantity > 1:
            # For quantity questions, multiply by quantity
            base_amount *= quantity
            print(f"[DEBUG] Applied quantity multiplier: {base_amount}")
        
        # Apply sign based on pricing type
        if pricing_type == 'discount_percent':
            result = -base_amount
            print(f"[DEBUG] Applied discount (negative): {result}")
            return result
        else:
            print(f"[DEBUG] Final result (positive): {base_amount}")
            return base_amount
    
    def _apply_quantity_discounts(self, question, option_adjustments, total_quantity, base_total):
        """Apply quantity discounts for quantity-type questions"""
        discounted_total = base_total
        
        # Get all quantity discounts for this question
        quantity_discounts = QuantityDiscount.objects.filter(
            question=question,
            min_quantity__lte=total_quantity
        ).order_by('-min_quantity')
        
        # Apply option-specific discounts
        for option_id, adjustment_data in option_adjustments.items():
            option_discounts = quantity_discounts.filter(
                option_id=option_id,
                scope='option'
            )
            
            if option_discounts.exists():
                discount = option_discounts.first()
                if discount.discount_type == 'percent':
                    discount_amount = adjustment_data['base_adjustment'] * (discount.value / 100)
                    discounted_total -= discount_amount
        
        # Apply whole-question discounts
        whole_question_discounts = quantity_discounts.filter(
            option__isnull=True,
            scope='question'
        )
        
        if whole_question_discounts.exists():
            discount = whole_question_discounts.first()
            if discount.discount_type == 'percent':
                discount_amount = base_total * (discount.value / 100)
                discounted_total -= discount_amount
        
        return discounted_total
    
    def _generate_all_package_quotes(self, service_selection, submission):
        """Generate quotes for ALL packages in the service with correct package-specific pricing"""
        service = service_selection.service
        packages = Package.objects.filter(service=service, is_active=True)
        
        surcharge_applied = False
        surcharge_amount_applied = Decimal('0.00')
        
        if submission.location and hasattr(service, 'settings'):
            try:
                settings = service.settings
                if settings.apply_trip_charge_to_bid:
                    surcharge_amount_applied = submission.location.trip_surcharge
                    service_selection.surcharge_applicable = True
                    service_selection.surcharge_amount = surcharge_amount_applied
                    surcharge_applied = True
                    service_selection.save()
            except ServiceSettings.DoesNotExist:
                pass
        
        # Clear existing quotes for this service
        service_selection.package_quotes.all().delete()
        
        # Generate quotes for each package
        for package in packages:
            base_price = package.base_price
            
            # Get package-specific sqft price
            sqft_price = self._get_package_sqft_price(submission, package)
            
            # Calculate package-specific question adjustments
            question_adjustments = self._calculate_package_specific_adjustments_new(
                service_selection, package, sqft_price
            )
            
            total_price = base_price + sqft_price + question_adjustments
            
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
                surcharge_amount=Decimal('0.00'),
                total_price=total_price,
                included_features=included_features,
                excluded_features=excluded_features,
                is_selected=False
            )
        
        return surcharge_applied, surcharge_amount_applied
    
    def _calculate_package_specific_adjustments_new(self, service_selection, package, base_sqft_price):
        """Calculate question adjustments specific to a package with package-specific sqft pricing"""
        total_adjustment = Decimal('0.00')
        
        print(f"[DEBUG] Calculating adjustments for package {package.id} ({package.name}) with package_sqft_price={base_sqft_price}")
        
        for question_response in service_selection.question_responses.all():
            question = question_response.question
            
            if question.question_type == 'yes_no':
                if question_response.yes_no_answer is True:
                    pricing = QuestionPricing.objects.filter(
                        question=question, package=package
                    ).first()
                    if pricing and pricing.yes_pricing_type not in ['ignore', 'fixed_price']:
                        adjustment = self._apply_pricing_rule(
                            pricing.yes_pricing_type, pricing.yes_value,
                            pricing.value_type, base_sqft_price
                        )
                        print(f"[DEBUG] Yes/No question {question.id} adjustment for package {package.id}: {adjustment}")
                        total_adjustment += adjustment
                    elif pricing and pricing.yes_pricing_type in ['fixed_price']:
                        print("reached herererreeerererererereerererrrrrrrr")
                        self.bid_in_person=True
                        
            
            elif question.question_type in ['describe', 'quantity']:
                adjustment = self._calculate_options_question_adjustment_from_stored(
                    question_response, package, base_sqft_price
                )
                print(f"[DEBUG] Options question {question.id} adjustment for package {package.id}: {adjustment}")
                total_adjustment += adjustment
            
            elif question.question_type == 'multiple_yes_no':
                adjustment = self._calculate_sub_questions_adjustment_from_stored(
                    question_response, package, base_sqft_price
                )
                print(f"[DEBUG] Multi yes/no question {question.id} adjustment for package {package.id}: {adjustment}")
                total_adjustment += adjustment
            
            elif question.question_type == 'conditional':
                if question_response.yes_no_answer is True:
                    pricing = QuestionPricing.objects.filter(
                        question=question, package=package
                    ).first()
                    if pricing and pricing.yes_pricing_type not in ['ignore', 'fixed_price']:
                        adjustment = self._apply_pricing_rule(
                            pricing.yes_pricing_type, pricing.yes_value,
                            pricing.value_type, base_sqft_price
                        )
                        print(f"[DEBUG] Conditional question {question.id} adjustment for package {package.id}: {adjustment}")
                        total_adjustment += adjustment

                    elif pricing and pricing.yes_pricing_type in ['fixed_price']:
                        print("reached herererreeerererererereerererrrrrrrr122")
                        self.bid_in_person=True
        
        print(f"[DEBUG] Total adjustment for package {package.id} ({package.name}): {total_adjustment}")
        return total_adjustment

    # Keep all other methods unchanged...
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
            sub_responses = parent_response.sub_question_responses.all()
            return any(sub.answer for sub in sub_responses)
        
        return False
    

class SubmissionDetailView(generics.RetrieveUpdateAPIView):
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
    """Submit the final quote with updated pricing logic including add-ons"""
    permission_classes = [AllowAny]
    
    def post(self, request, submission_id):
        submission = get_object_or_404(CustomerSubmission, id=submission_id)

        print("submission: ", submission.total_surcharges)
        
        # Check if packages are already selected (from Step 8)
        if submission.status == 'packages_selected':
            # Packages already selected, just need final confirmation
            serializer = SubmitFinalQuoteSerializer(data=request.data)
        elif submission.status == 'draft' or submission.status == 'responses_completed':
            # Need to select packages first, then submit
            serializer = SubmitFinalQuoteSerializer(data=request.data)
            # if not request.data.get('selected_packages'):
            #     return Response({
            #         'error': 'Please select packages first or use the package selection endpoint'
            #     }, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({
                'error': f'Invalid submission status: {submission.status}. Complete all steps first.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            with transaction.atomic():
                # If packages are provided in payload, update selections
                if serializer.validated_data.get('selected_packages'):
                    self._update_package_selections(submission, serializer.validated_data['selected_packages'])
                
                # Update submission with additional information
                submission.status = 'submitted'
                
                # Store additional submission details
                additional_data = {
                    'additional_notes': serializer.validated_data.get('additional_notes', ''),
                    'preferred_contact_method': serializer.validated_data.get('preferred_contact_method', 'email'),
                    'preferred_start_date': (
                        serializer.validated_data.get('preferred_start_date').isoformat()
                        if serializer.validated_data.get('preferred_start_date') else None
                    ),                    
                    'marketing_consent': serializer.validated_data.get('marketing_consent', False),
                    'signature': serializer.validated_data.get('signature', ""),
                    'submitted_at': timezone.now().isoformat()
                }
                
                submission.additional_data = additional_data
                submission.save()
                
                # Calculate final totals with new logic (including add-ons)
                if submission.final_total == Decimal('0.00'):
                    self._calculate_final_totals_new(submission)
                    
                # Send notifications, create orders, etc.
                create_or_update_ghl_contact(submission, is_submit=True)
                
                return Response({
                    'message': 'Quote submitted successfully',
                    'submission_id': submission.id,
                    'final_total': submission.final_total,
                    'quote_url': f'/quote/{submission.id}/',
                    'status': submission.status,
                    'submitted_at': timezone.now().isoformat()
                })
        
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    def _update_package_selections(self, submission, selected_packages):
        """Update package selections if provided in payload"""
        for package_data in selected_packages:
            service_selection = get_object_or_404(
                CustomerServiceSelection,
                id=package_data['service_selection_id'],
                submission=submission
            )
            
            package = get_object_or_404(Package, id=package_data['package_id'])
            
            # Update service selection
            service_selection.selected_package = package
            
            # Get the quote for this package
            quote = get_object_or_404(
                CustomerPackageQuote,
                service_selection=service_selection,
                package=package
            )
            
            service_selection.final_base_price = quote.base_price + quote.sqft_price
            service_selection.final_sqft_price = quote.sqft_price
            service_selection.final_total_price = quote.total_price
            service_selection.save()
            
            # Mark this quote as selected
            service_selection.package_quotes.update(is_selected=False)
            quote.is_selected = True
            quote.save()
        
        # Update submission status
        submission.status = 'packages_selected'
        submission.save()
    
    def _calculate_final_totals_new(self, submission):
        """Calculate final totals for the submission with new pricing logic including add-ons"""
        service_selections = submission.customerserviceselection_set.filter(
            selected_package__isnull=False
        )
        
        total_base_price = Decimal('0.00')
        total_sqft_price = Decimal('0.00')
        total_adjustments = Decimal('0.00')
        total_addons_price = Decimal('0.00')
        
        print(f"[DEBUG] Calculating final totals for submission {submission.id}")
        
        # Calculate service totals
        for selection in service_selections:
            selected_quote = selection.package_quotes.filter(is_selected=True).first()
            if selected_quote:
                # Base price from package
                total_base_price += selected_quote.base_price
                # Square footage price from size range
                total_sqft_price += selected_quote.sqft_price
                # Question adjustments (with new percentage/amount logic)
                total_adjustments += selected_quote.question_adjustments
                
                print(f"[DEBUG] Service {selection.service.name}: base={selected_quote.base_price}, sqft={selected_quote.sqft_price}, adjustments={selected_quote.question_adjustments}")
        
        # Calculate add-ons total
        if submission.addons.exists():
            for addon in submission.addons.all():
                total_addons_price += addon.base_price
                print(f"[DEBUG] Add-on {addon.name}: price={addon.base_price}")
        
        print(f"[DEBUG] Total add-ons price: {total_addons_price}")
        
        # Final total includes base price + sqft price + adjustments + surcharges + add-ons
        final_total = total_base_price + total_sqft_price + total_adjustments + submission.total_surcharges + total_addons_price
        
        print(f"[DEBUG] Final calculation: base={total_base_price} + sqft={total_sqft_price} + adjustments={total_adjustments} + surcharges={submission.total_surcharges} + addons={total_addons_price} = {final_total}")
        
        # Update submission totals
        submission.total_base_price = total_base_price + total_sqft_price  # Combined base and sqft
        submission.total_adjustments = total_adjustments
        submission.total_addons_price = total_addons_price  # Store add-ons total separately
        submission.final_total = final_total
        submission.save()
        
        print(f"[DEBUG] Updated submission totals: total_base_price={submission.total_base_price}, total_adjustments={submission.total_adjustments}, total_addons_price={submission.total_addons_price}, final_total={submission.final_total}")
    
    def _get_package_sqft_price(self, submission, package):
        """Get the package-specific square footage price"""
        if not submission.size_range:
            return Decimal('0.00')
            
        sqft_mapping = ServicePackageSizeMapping.objects.filter(
            service_package=package,
            global_size=submission.size_range
        ).first()

        print(f"[DEBUG] sqft_mapping.price for package {package.id}: {sqft_mapping.price if sqft_mapping else 'None'}")
        
        return sqft_mapping.price if sqft_mapping else Decimal('0.00')
    




class SelectPackagesView(APIView):
    """Select packages for each service before final submission"""
    permission_classes = [AllowAny]
    
    def post(self, request, submission_id):
        submission = get_object_or_404(CustomerSubmission, id=submission_id)
        
        if submission.status != 'responses_completed':
            return Response({
                'error': 'Cannot select packages. Complete service responses first.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        selected_packages = request.data.get('selected_packages', [])
        
        if not selected_packages:
            return Response({
                'error': 'No packages selected'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            with transaction.atomic():
                for package_data in selected_packages:
                    service_selection = get_object_or_404(
                        CustomerServiceSelection,
                        id=package_data['service_selection_id'],
                        submission=submission
                    )
                    
                    package = get_object_or_404(Package, id=package_data['package_id'])
                    
                    # Verify this package exists for this service
                    if package.service != service_selection.service:
                        return Response({
                            'error': f'Package {package.name} does not belong to service {service_selection.service.name}'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    # Update service selection
                    service_selection.selected_package = package
                    
                    # Get the quote for this package
                    quote = get_object_or_404(
                        CustomerPackageQuote,
                        service_selection=service_selection,
                        package=package
                    )
                    
                    # Update service selection with final pricing
                    service_selection.final_base_price = quote.base_price + quote.sqft_price
                    service_selection.final_sqft_price = quote.sqft_price
                    service_selection.final_total_price = quote.total_price
                    service_selection.save()
                    
                    # Mark this quote as selected
                    service_selection.package_quotes.update(is_selected=False)
                    quote.is_selected = True
                    quote.save()
                
                # Update submission status
                submission.status = 'packages_selected'
                submission.save()
                
                # Calculate final totals
                self._calculate_final_totals_new(submission)
                
                return Response({
                    'message': 'Packages selected successfully',
                    'submission_id': submission.id,
                    'status': submission.status,
                    'final_total': submission.final_total
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




class AddOnServiceListView(generics.ListAPIView):
    queryset = AddOnService.objects.all()
    serializer_class = AddOnServiceSerializer
    permission_classes = [AllowAny]


class AddAddOnsToSubmissionView(APIView):
    permission_classes = [AllowAny]  # ✅ no auth

    def post(self, request, submission_id):
        addon_ids = request.data.get("addon_ids", [])
        if not addon_ids:
            return Response({"error": "addon_ids list is required"}, status=400)

        try:
            submission = get_object_or_404(CustomerSubmission, id=submission_id)
            addons = AddOnService.objects.filter(id__in=addon_ids)
            
            if not addons.exists():
                return Response({"error": "No valid add-ons found"}, status=400)

            # Attach addons (many-to-many add)
            submission.addons.add(*addons)

            # ✅ Recalculate total_addons_price
            total_price = submission.addons.aggregate(
                total=Sum("base_price")
            )["total"] or Decimal("0.00")
            submission.total_addons_price = total_price
            submission.save()

            return Response({
                "message": "Add-ons added successfully",
                "total_addons_price": str(submission.total_addons_price),
                "addons": AddOnServiceSerializer(submission.addons.all(), many=True).data
            })
        except Exception as e:
            return Response({"error": str(e)}, status=400)
        
    def delete(self, request, submission_id):
        addon_ids = request.data.get("addon_ids", [])
        if not addon_ids:
            return Response({"error": "addon_ids list is required"}, status=400)

        try:
            submission = get_object_or_404(CustomerSubmission, id=submission_id)
            addons = AddOnService.objects.filter(id__in=addon_ids)

            if not addons.exists():
                return Response({"error": "No valid add-ons found"}, status=400)

            # Remove addons (many-to-many remove)
            submission.addons.remove(*addons)

            # ✅ Recalculate total_addons_price
            total_price = submission.addons.aggregate(
                total=Sum("base_price")
            )["total"] or Decimal("0.00")
            submission.total_addons_price = total_price
            submission.save()

            return Response({
                "message": "Add-ons removed successfully",
                "total_addons_price": str(submission.total_addons_price),
                "addons": AddOnServiceSerializer(submission.addons.all(), many=True).data
            })
        except Exception as e:
            return Response({"error": str(e)}, status=400)
        



class DeclineSubmissionView(APIView):
    """
    Endpoint to decline a submission
    """
    permission_classes = [AllowAny]

    def post(self, request, submission_id):
        submission = get_object_or_404(CustomerSubmission, id=submission_id)

        if submission.status == "declined":
            return Response(
                {"message": "Submission is already declined."},
                status=status.HTTP_400_BAD_REQUEST
            )

        submission.status = "declined"
        submission.declined_at = timezone.now()
        submission.save(update_fields=["status", "declined_at"])        
        create_or_update_ghl_contact(submission,is_declined=True)

        return Response(
            {
                "message": f"Submission {submission_id} has been declined.",
                "submission_id": str(submission.id),
                "status": submission.status,
            },
            status=status.HTTP_200_OK,
        )
