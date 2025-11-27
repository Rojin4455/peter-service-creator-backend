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
    ServicePackageSizeMapping, QuestionPricing, OptionPricing, SubQuestionPricing,QuantityDiscount, AddOnService,Coupon
)
from django.db.models import Sum
from .models import (
    CustomerSubmission, CustomerServiceSelection, CustomerQuestionResponse,
    CustomerOptionResponse, CustomerSubQuestionResponse, CustomerPackageQuote, SubmissionAddOn,CustomerAvailability
)
from .serializers import (
    LocationPublicSerializer, ServicePublicSerializer, PackagePublicSerializer,
    QuestionPublicSerializer, GlobalSizePackagePublicSerializer,CouponSerializer,
    CustomerSubmissionCreateSerializer, CustomerSubmissionDetailSerializer,AddOnServiceSerializer,
    ServiceQuestionResponseSerializer, PricingCalculationRequestSerializer,SubmitFinalQuoteSerializer,SubmissionAddOnSerializer,
    ConditionalQuestionRequestSerializer, CustomerPackageQuoteSerializer,ConditionalQuestionResponseSerializer,ServiceResponseSubmissionSerializer,CustomerAvailabilitySerializer,MultipleAvailabilitySerializer
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
        # Optimize: Prefetch related objects to avoid N+1 queries
        submission = get_object_or_404(
            CustomerSubmission.objects.select_related('location', 'size_range'), 
            id=submission_id
        )
        service_selection = get_object_or_404(
            CustomerServiceSelection.objects.select_related('service', 'service__settings'), 
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
                
                # OPTIMIZATION: Prefetch all packages and related data once
                packages = Package.objects.filter(service=service_selection.service, is_active=True).select_related('service')
                
                # OPTIMIZATION: Prefetch all sqft mappings for all packages at once
                sqft_mappings = {}
                if submission.size_range:
                    sqft_mappings = {
                        mapping.service_package_id: mapping.price
                        for mapping in ServicePackageSizeMapping.objects.filter(
                            service_package__in=packages,
                            global_size=submission.size_range
                        ).select_related('service_package', 'global_size')
                    }
                
                # OPTIMIZATION: Prefetch all questions at once to avoid N+1 queries
                question_ids = [r['question_id'] for r in ordered_responses]
                questions_dict = {
                    q.id: q for q in Question.objects.filter(id__in=question_ids).select_related('service')
                }
                
                total_adjustment = Decimal('0.00')
                
                for response_data in ordered_responses:
                    question_id = response_data['question_id']
                    question = questions_dict.get(question_id)
                    if not question:
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
                    
                    # Calculate pricing adjustment (for averaging only) - optimized
                    question_adjustment = self._calculate_question_adjustment_for_averaging_optimized(
                        question, response_data, question_response, service_selection, packages, sqft_mappings
                    )
                    
                    question_response.price_adjustment = question_adjustment
                    question_response.save()
                    
                    total_adjustment += question_adjustment
                
                # Update service selection totals (this is just for averaging display)
                service_selection.question_adjustments = total_adjustment
                service_selection.save()
                
                surcharge_for_submission = False
                # Generate package quotes for ALL packages - optimized
                surcharge_applied, surcharge_price = self._generate_all_package_quotes_optimized(
                    service_selection, submission, packages, sqft_mappings
                )
                
                print("+++++++++++++surcharge_applied, surcharge_price++++++++++",surcharge_applied, surcharge_price)
                if surcharge_applied:
                    surcharge_for_submission = True

                # After all services processed

                    
                    
                
                # Check if all services have responses - optimized
                all_services_completed = self._check_all_services_completed_optimized(submission)
                if all_services_completed:
                    submission.status = 'responses_completed'
                    submission.save()
                if surcharge_for_submission:
                    submission.quote_surcharge_applicable = True
                    submission.total_surcharges = surcharge_price
                
                submission.is_bid_in_person = self.bid_in_person
                submission.save()
                print("submission.total_surcharges",submission.total_surcharges)

                if not submission.is_on_the_go:
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
        
        # Prefetch sqft mappings
        sqft_mappings = {}
        if service_selection.submission.size_range:
            sqft_mappings = {
                mapping.service_package_id: mapping.price
                for mapping in ServicePackageSizeMapping.objects.filter(
                    service_package__in=packages,
                    global_size=service_selection.submission.size_range
                )
            }
        
        return self._calculate_question_adjustment_for_averaging_optimized(
            question, response_data, question_response, service_selection, packages, sqft_mappings
        )
    
    def _calculate_question_adjustment_for_averaging_optimized(self, question, response_data, question_response, service_selection, packages, sqft_mappings):
        """Calculate average adjustment across packages (for display only) - OPTIMIZED"""
        if not packages.exists():
            return Decimal('0.00')
        
        total_adjustment = Decimal('0.00')
        package_count = 0
        
        # Prefetch all pricing data for this question across all packages
        question_pricings = {
            qp.package_id: qp 
            for qp in QuestionPricing.objects.filter(
                question=question, 
                package__in=packages
            ).select_related('package', 'question')
        }
        
        for package in packages:
            # Get package-specific sqft price from pre-fetched dict
            package_sqft_price = sqft_mappings.get(package.id, Decimal('0.00'))
            
            # Get pricing from pre-fetched dict
            pricing = question_pricings.get(package.id)
            
            package_adjustment = self._calculate_single_package_adjustment_optimized(
                question, response_data, question_response, package, package_sqft_price, pricing
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
        # Get pricing for this call
        pricing = None
        if question.question_type in ['yes_no', 'conditional'] and response_data.get('yes_no_answer') is True:
            pricing = QuestionPricing.objects.filter(
                question=question, package=package
            ).first()
        
        return self._calculate_single_package_adjustment_optimized(
            question, response_data, question_response, package, base_sqft_price, pricing
        )
    
    def _calculate_single_package_adjustment_optimized(self, question, response_data, question_response, package, base_sqft_price, pricing=None):
        """Calculate adjustment for a single package - OPTIMIZED"""
        package_adjustment = Decimal('0.00')
        
        if question.question_type == 'yes_no':
            if response_data.get('yes_no_answer') is True:
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
                if pricing and pricing.yes_pricing_type not in ['ignore', 'fixed_price']:
                    package_adjustment = self._apply_pricing_rule(
                        pricing.yes_pricing_type, pricing.yes_value,
                        pricing.value_type, base_sqft_price
                    )
        
        return package_adjustment
    
    def _calculate_options_question_adjustment_from_stored(self, question_response, package, base_sqft_price):
        """Calculate adjustment for options question using stored responses (prevents duplication)"""
        # Prefetch pricing for all options
        option_ids = [opt_resp.option_id for opt_resp in question_response.option_responses.all()]
        all_option_pricings = {}
        if option_ids:
            all_option_pricings = {
                (op.option_id, op.package_id): op
                for op in OptionPricing.objects.filter(
                    option_id__in=option_ids,
                    package=package
                ).select_related('option', 'package')
            }
        
        return self._calculate_options_question_adjustment_from_stored_optimized(
            question_response, package, base_sqft_price, all_option_pricings
        )
    
    def _calculate_options_question_adjustment_from_stored_optimized(self, question_response, package, base_sqft_price, all_option_pricings):
        """Calculate adjustment for options question using stored responses (prevents duplication) - OPTIMIZED"""
        total_adjustment = Decimal('0.00')
        total_quantity = 0
        
        # Calculate base adjustments and total quantity from stored responses
        option_adjustments = {}
        for option_response in question_response.option_responses.all():
            option = option_response.option
            quantity = option_response.quantity
            total_quantity += quantity
            
            pricing = all_option_pricings.get((option.id, package.id))
            
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
        # Prefetch pricing for all sub-questions
        sub_question_ids = [sub_resp.sub_question_id for sub_resp in question_response.sub_question_responses.all()]
        all_sub_question_pricings = {}
        if sub_question_ids:
            all_sub_question_pricings = {
                (sqp.sub_question_id, sqp.package_id): sqp
                for sqp in SubQuestionPricing.objects.filter(
                    sub_question_id__in=sub_question_ids,
                    package=package
                ).select_related('sub_question', 'package')
            }
        
        return self._calculate_sub_questions_adjustment_from_stored_optimized(
            question_response, package, base_sqft_price, all_sub_question_pricings
        )
    
    def _calculate_sub_questions_adjustment_from_stored_optimized(self, question_response, package, base_sqft_price, all_sub_question_pricings):
        """Calculate adjustment for multiple yes/no questions using stored responses - OPTIMIZED"""
        total_adjustment = Decimal('0.00')
        
        print(f"[DEBUG] Processing sub-questions from stored responses with base_sqft_price={base_sqft_price}")
        
        for sub_response in question_response.sub_question_responses.all():
            if sub_response.answer:  # Only process True answers
                sub_question = sub_response.sub_question
                
                # Get pricing from pre-fetched dict
                pricing = all_sub_question_pricings.get((sub_question.id, package.id))
                
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
        packages = Package.objects.filter(service=service, is_active=True).select_related('service')
        
        # Prefetch sqft mappings
        sqft_mappings = {}
        if submission.size_range:
            sqft_mappings = {
                mapping.service_package_id: mapping.price
                for mapping in ServicePackageSizeMapping.objects.filter(
                    service_package__in=packages,
                    global_size=submission.size_range
                ).select_related('service_package', 'global_size')
            }
        
        return self._generate_all_package_quotes_optimized(service_selection, submission, packages, sqft_mappings)
    
    def _generate_all_package_quotes_optimized(self, service_selection, submission, packages, sqft_mappings):
        """Generate quotes for ALL packages in the service with correct package-specific pricing - OPTIMIZED"""
        service = service_selection.service
        
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
        
        # OPTIMIZATION: Prefetch all package features for all packages at once
        all_package_features = PackageFeature.objects.filter(
            package__in=packages
        ).select_related('package', 'feature')
        
        # Organize features by package
        features_by_package = {}
        for pf in all_package_features:
            package_id = pf.package_id
            if package_id not in features_by_package:
                features_by_package[package_id] = {'included': [], 'excluded': []}
            if pf.is_included:
                features_by_package[package_id]['included'].append(str(pf.feature.id))
            else:
                features_by_package[package_id]['excluded'].append(str(pf.feature.id))
        
        # OPTIMIZATION: Prefetch all question responses with related data at once
        question_responses = service_selection.question_responses.all().prefetch_related(
            'question',
            'option_responses__option',
            'sub_question_responses__sub_question'
        )
        
        # OPTIMIZATION: Prefetch all pricing rules for all packages and questions
        question_ids = [qr.question_id for qr in question_responses]
        all_question_pricings = {}
        if question_ids:
            all_question_pricings = {
                (qp.question_id, qp.package_id): qp
                for qp in QuestionPricing.objects.filter(
                    question_id__in=question_ids,
                    package__in=packages
                ).select_related('question', 'package')
            }
        
        all_option_pricings = {}
        all_sub_question_pricings = {}
        
        # Get all option IDs and sub-question IDs
        option_ids = []
        sub_question_ids = []
        for qr in question_responses:
            for opt_resp in qr.option_responses.all():
                option_ids.append(opt_resp.option_id)
            for sub_resp in qr.sub_question_responses.all():
                sub_question_ids.append(sub_resp.sub_question_id)
        
        if option_ids:
            all_option_pricings = {
                (op.option_id, op.package_id): op
                for op in OptionPricing.objects.filter(
                    option_id__in=option_ids,
                    package__in=packages
                ).select_related('option', 'package')
            }
        
        if sub_question_ids:
            all_sub_question_pricings = {
                (sqp.sub_question_id, sqp.package_id): sqp
                for sqp in SubQuestionPricing.objects.filter(
                    sub_question_id__in=sub_question_ids,
                    package__in=packages
                ).select_related('sub_question', 'package')
            }
        
        # Generate quotes for each package
        for package in packages:
            base_price = package.base_price
            
            # Get package-specific sqft price from pre-fetched dict
            sqft_price = sqft_mappings.get(package.id, Decimal('0.00'))
            
            # Calculate package-specific question adjustments - optimized
            question_adjustments = self._calculate_package_specific_adjustments_new_optimized(
                question_responses, package, sqft_price, 
                all_question_pricings, all_option_pricings, all_sub_question_pricings
            )

            # New total logic:
            # - Compute the quoted total WITHOUT base_price
            # - If quoted total is below the package base_price, use base_price
            # - Otherwise, do not add base_price again
            # - Include surcharge in the total
            quoted_total = sqft_price + question_adjustments + surcharge_amount_applied
            total_price = base_price if quoted_total < base_price else quoted_total
            
            # Get package features from pre-fetched dict
            package_features_data = features_by_package.get(package.id, {'included': [], 'excluded': []})
            included_features = package_features_data['included']
            excluded_features = package_features_data['excluded']
            
            CustomerPackageQuote.objects.create(
                service_selection=service_selection,
                package=package,
                base_price=base_price,
                sqft_price=sqft_price,
                question_adjustments=question_adjustments,
                surcharge_amount=surcharge_amount_applied,  # Store actual surcharge amount
                total_price=total_price,
                included_features=included_features,
                excluded_features=excluded_features,
                is_selected=False
            )
        
        return surcharge_applied, surcharge_amount_applied
    
    def _calculate_package_specific_adjustments_new(self, service_selection, package, base_sqft_price):
        """Calculate question adjustments specific to a package with package-specific sqft pricing"""
        # Fallback to optimized version with prefetching
        question_responses = service_selection.question_responses.all().prefetch_related(
            'question',
            'option_responses__option',
            'sub_question_responses__sub_question'
        )
        
        # Prefetch pricing data
        question_ids = [qr.question_id for qr in question_responses]
        all_question_pricings = {}
        if question_ids:
            all_question_pricings = {
                (qp.question_id, qp.package_id): qp
                for qp in QuestionPricing.objects.filter(
                    question_id__in=question_ids,
                    package=package
                ).select_related('question', 'package')
            }
        
        option_ids = []
        sub_question_ids = []
        for qr in question_responses:
            for opt_resp in qr.option_responses.all():
                option_ids.append(opt_resp.option_id)
            for sub_resp in qr.sub_question_responses.all():
                sub_question_ids.append(sub_resp.sub_question_id)
        
        all_option_pricings = {}
        if option_ids:
            all_option_pricings = {
                (op.option_id, op.package_id): op
                for op in OptionPricing.objects.filter(
                    option_id__in=option_ids,
                    package=package
                ).select_related('option', 'package')
            }
        
        all_sub_question_pricings = {}
        if sub_question_ids:
            all_sub_question_pricings = {
                (sqp.sub_question_id, sqp.package_id): sqp
                for sqp in SubQuestionPricing.objects.filter(
                    sub_question_id__in=sub_question_ids,
                    package=package
                ).select_related('sub_question', 'package')
            }
        
        return self._calculate_package_specific_adjustments_new_optimized(
            question_responses, package, base_sqft_price,
            all_question_pricings, all_option_pricings, all_sub_question_pricings
        )
    
    def _calculate_package_specific_adjustments_new_optimized(self, question_responses, package, base_sqft_price, 
                                                               all_question_pricings, all_option_pricings, all_sub_question_pricings):
        """Calculate question adjustments specific to a package with package-specific sqft pricing - OPTIMIZED"""
        total_adjustment = Decimal('0.00')
        
        print(f"[DEBUG] Calculating adjustments for package {package.id} ({package.name}) with package_sqft_price={base_sqft_price}")
        
        for question_response in question_responses:
            question = question_response.question
            
            if question.question_type == 'yes_no':
                if question_response.yes_no_answer is True:
                    pricing = all_question_pricings.get((question.id, package.id))
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
                adjustment = self._calculate_options_question_adjustment_from_stored_optimized(
                    question_response, package, base_sqft_price, all_option_pricings
                )
                print(f"[DEBUG] Options question {question.id} adjustment for package {package.id}: {adjustment}")
                total_adjustment += adjustment
            
            elif question.question_type == 'multiple_yes_no':
                adjustment = self._calculate_sub_questions_adjustment_from_stored_optimized(
                    question_response, package, base_sqft_price, all_sub_question_pricings
                )
                print(f"[DEBUG] Multi yes/no question {question.id} adjustment for package {package.id}: {adjustment}")
                total_adjustment += adjustment
            
            elif question.question_type == 'conditional':
                if question_response.yes_no_answer is True:
                    pricing = all_question_pricings.get((question.id, package.id))
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
        return self._check_all_services_completed_optimized(submission)
    
    def _check_all_services_completed_optimized(self, submission):
        """Check if all selected services have responses - OPTIMIZED"""
        service_selections = submission.customerserviceselection_set.all().prefetch_related(
            'question_responses__question',
            'service'
        )
        
        # OPTIMIZATION: Prefetch all root questions for all services at once
        service_ids = [ss.service_id for ss in service_selections]
        all_root_questions = Question.objects.filter(
            service_id__in=service_ids,
            is_active=True,
            parent_question__isnull=True
        ).select_related('service')
        
        # Organize questions by service
        root_questions_by_service = {}
        for q in all_root_questions:
            service_id = q.service_id
            if service_id not in root_questions_by_service:
                root_questions_by_service[service_id] = []
            root_questions_by_service[service_id].append(q)
        
        # OPTIMIZATION: Prefetch all conditional questions at once
        root_question_ids = [q.id for q in all_root_questions]
        all_conditional_questions = Question.objects.filter(
            parent_question_id__in=root_question_ids,
            is_active=True
        ).select_related('parent_question', 'service')
        
        # Organize conditional questions by parent
        conditional_questions_by_parent = {}
        for q in all_conditional_questions:
            parent_id = q.parent_question_id
            if parent_id not in conditional_questions_by_parent:
                conditional_questions_by_parent[parent_id] = []
            conditional_questions_by_parent[parent_id].append(q)
        
        for selection in service_selections:
            # Check if this service has any question responses
            if not selection.question_responses.exists():
                return False
            
            # Get root questions for this service from pre-fetched dict
            root_questions = root_questions_by_service.get(selection.service_id, [])
            
            # Check if all root questions have responses
            answered_question_ids = set(
                selection.question_responses.values_list('question_id', flat=True)
            )
            
            for root_question in root_questions:
                if root_question.id not in answered_question_ids:
                    return False
                
                # Get conditional questions from pre-fetched dict
                conditional_questions = conditional_questions_by_parent.get(root_question.id, [])
                
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

                if not serializer.validated_data.get('coupon_id', ''):
                    submission.is_coupon_applied=False
                    submission.applied_coupon=None
                
                submission.additional_data = additional_data
                submission.save()
                
                # Calculate final totals with new logic (including add-ons)
                # if submission.final_total == Decimal('0.00'):
                self._calculate_final_totals_new(submission)
                    
                # Send notifications, create orders, etc.

                if not submission.is_on_the_go:
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
        total_services_price = Decimal('0.00')
        total_services_price = Decimal('0.00')
        
        print(f"[DEBUG] Calculating final totals for submission {submission.id}")
        
        # Calculate service totals
        for selection in service_selections:
            selected_quote = selection.package_quotes.filter(is_selected=True).first()
            if selected_quote:
                # Track components for reporting (optional)
                total_base_price += selected_quote.base_price
                total_sqft_price += selected_quote.sqft_price
                total_adjustments += selected_quote.question_adjustments
                # Use computed package total (with base-price-minimum logic applied and surcharge included)
                total_services_price += selected_quote.total_price
                print(f"[DEBUG] Service {selection.service.name}: base={selected_quote.base_price}, sqft={selected_quote.sqft_price}, adjustments={selected_quote.question_adjustments}, surcharge={selected_quote.surcharge_amount}, package_total={selected_quote.total_price}")
        
        # # Calculate add-ons total
        # if submission.addons.exists():
        #     for addon in submission.addons.all():
        #         total_addons_price += addon.base_price
        #         print(f"[DEBUG] Add-on {addon.name}: price={addon.base_price}")
        
        # print(f"[DEBUG] Total add-ons price: {total_addons_price}")

        submission_addons = submission.submission_addons.select_related("addon")
        for sub_addon in submission_addons:
            subtotal = sub_addon.addon.base_price * sub_addon.quantity
            total_addons_price += subtotal
            print(
                f"[DEBUG] Add-on {sub_addon.addon.name}: base_price={sub_addon.addon.base_price}, "
                f"quantity={sub_addon.quantity}, subtotal={subtotal}"
            )

        print(f"[DEBUG] Total add-ons price: {total_addons_price}")

        
        # Final total uses package totals (which already enforce base price minimum and include surcharges) + add-ons
        # NOTE: Do NOT add submission.total_surcharges again since surcharges are already included in each package total
        final_total = total_services_price + total_addons_price
        
        print(f"[DEBUG] Final calculation: base={total_base_price} + sqft={total_sqft_price} + adjustments={total_adjustments} + addons={total_addons_price} = {final_total}")
        print(f"[DEBUG] Note: Surcharges are already included in package totals, so not added separately")


        if submission.applied_coupon and submission.applied_coupon.is_valid():
            final_total = submission.applied_coupon.apply_discount(final_total)
            submission.is_coupon_applied = True
            print(f"[DEBUG] Coupon {submission.applied_coupon.code} applied: new total = {final_total}")
        else:
            submission.is_coupon_applied = False
            print("[DEBUG] No valid coupon applied")
        
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
    



class EditServiceResponsesView(APIView):
    """Edit responses for a submitted service while preserving package selection"""
    permission_classes = [AllowAny]  # Or your custom permission
    
    # Add this property to reuse in helper methods
    bid_in_person = False
    
    def put(self, request, submission_id, service_id):
        """
        Edit service responses after submission.
        Preserves package selection and recalculates all totals.
        """
        self.bid_in_person = False  # Reset for each request
        
        submission = get_object_or_404(CustomerSubmission, id=submission_id)
        
        # Verify submission is in submitted state
        if submission.status != 'submitted':
            return Response({
                'error': 'Can only edit responses for submitted quotes'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        service_selection = get_object_or_404(
            CustomerServiceSelection,
            submission=submission,
            service_id=service_id
        )
        
        # Capture current state for history
        old_package_quote = service_selection.package_quotes.filter(is_selected=True).first()
        old_total = submission.final_total
        old_responses_snapshot = self._capture_responses_snapshot(service_selection)
        
        responses_present = 'responses' in request.data
        responses = request.data.get('responses', [])
        edited_by = request.data.get('edited_by', 'admin')
        edit_reason = request.data.get('edit_reason', '')
        
        try:
            with transaction.atomic():
                # Package-only edit path: switch package and preserve existing responses
                new_package_id = request.data.get('new_package_id')
                is_package_only = bool(new_package_id) and (not responses_present or not responses)
                if is_package_only:
                    # Regenerate quotes based on existing stored responses
                    surcharge_applied, surcharge_price = self._generate_all_package_quotes(
                        service_selection, submission
                    )

                    # Switch the selected package
                    self._restore_package_selection(
                        service_selection,
                        new_package_id,
                        submission
                    )

                    if surcharge_applied:
                        submission.quote_surcharge_applicable = True
                        submission.total_surcharges = surcharge_price

                    submission.is_bid_in_person = self.bid_in_person

                    # Recalculate totals
                    self._recalculate_final_totals_after_edit(submission)

                    # Track edit
                    submission.last_edited_at = timezone.now()
                    submission.edited_by = edited_by
                    submission.edit_count += 1
                    submission.save()

                    new_package_quote = service_selection.package_quotes.filter(is_selected=True).first()
                    return Response({
                        'message': 'Package switched successfully (responses preserved)',
                        'submission_id': submission.id,
                        'service_id': service_id,
                        'selected_package': {
                            'id': new_package_quote.package.id,
                            'name': new_package_quote.package.name,
                            'new_price': new_package_quote.total_price
                        } if new_package_quote else None,
                        'final_total': submission.final_total
                    })

                # Validate conditional question logic for full edits
                validation_result = self._validate_conditional_responses(responses, service_id)
                if not validation_result['valid']:
                    return Response({
                        'error': 'Invalid conditional question responses',
                        'details': validation_result['errors']
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # IMPORTANT: Save the currently selected package before clearing responses
                previously_selected_package = service_selection.selected_package
                previously_selected_package_id = previously_selected_package.id if previously_selected_package else None
                
                # Clear existing responses (but not the service selection itself)
                service_selection.question_responses.all().delete()
                
                # Process new responses
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
                    
                    # Process response data
                    self._process_question_response_data(question, response_data, question_response)
                    
                    # Calculate adjustment
                    question_adjustment = self._calculate_question_adjustment_for_averaging(
                        question, response_data, question_response, service_selection
                    )
                    
                    question_response.price_adjustment = question_adjustment
                    question_response.save()
                    
                    total_adjustment += question_adjustment
                
                # Update service selection adjustments
                service_selection.question_adjustments = total_adjustment
                service_selection.save()
                
                # Regenerate ALL package quotes with new pricing
                surcharge_applied, surcharge_price = self._generate_all_package_quotes(
                    service_selection, submission
                )
                
                # CRITICAL: Optionally switch package if admin provided new_package_id; else restore previous selection
                new_package_id = request.data.get('new_package_id')
                if new_package_id:
                    self._restore_package_selection(
                        service_selection,
                        new_package_id,
                        submission
                    )
                elif previously_selected_package_id:
                    self._restore_package_selection(
                        service_selection, 
                        previously_selected_package_id,
                        submission
                    )
                
                # Refresh service selection from database to get latest package quotes
                service_selection.refresh_from_db()
                
                # Update submission-level surcharge if applicable
                if surcharge_applied:
                    submission.quote_surcharge_applicable = True
                    submission.total_surcharges = surcharge_price
                
                submission.is_bid_in_person = self.bid_in_person
                
                # ALWAYS recalculate final totals after edit
                self._recalculate_final_totals_after_edit(submission)
                
                # Update edit tracking
                submission.last_edited_at = timezone.now()
                submission.edited_by = edited_by
                submission.edit_count += 1
                
                # Add to edit history
                edit_history_entry = {
                    'edited_at': timezone.now().isoformat(),
                    'edited_by': edited_by,
                    'service_id': str(service_id),
                    'service_name': service_selection.service.name,
                    'edit_reason': edit_reason,
                    'old_total': str(old_total),
                    'new_total': str(submission.final_total),
                    'old_question_adjustments': str(old_responses_snapshot.get('question_adjustments', '0.00')),
                    'new_question_adjustments': str(service_selection.question_adjustments),
                    'changes_summary': self._generate_changes_summary(old_responses_snapshot, responses)
                }
                
                if not submission.edit_history:
                    submission.edit_history = []
                submission.edit_history.append(edit_history_entry)
                
                submission.save()
                
                # Update GHL contact if needed
                if not submission.is_on_the_go:
                    create_or_update_ghl_contact(submission, is_submit=True)
                
                # Get updated quote for response
                new_package_quote = service_selection.package_quotes.filter(is_selected=True).first()
                
                return Response({
                    'message': 'Responses updated successfully',
                    'submission_id': submission.id,
                    'service_id': service_id,
                    'total_questions_answered': len(ordered_responses),
                    'old_total': old_total,
                    'new_total': submission.final_total,
                    'total_change': submission.final_total - old_total,
                    'package_preserved': previously_selected_package_id is not None,
                    'selected_package': {
                        'id': new_package_quote.package.id,
                        'name': new_package_quote.package.name,
                        'old_price': old_package_quote.total_price if old_package_quote else None,
                        'new_price': new_package_quote.total_price
                    } if new_package_quote else None,
                    'edit_count': submission.edit_count,
                    'surcharge_applied': surcharge_applied
                })
        
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    def _restore_package_selection(self, service_selection, package_id, submission):
        """Restore the previously selected package and update service selection totals"""
        try:
            package_quote = CustomerPackageQuote.objects.get(
                service_selection=service_selection,
                package_id=package_id
            )
            
            service_selection.package_quotes.update(is_selected=False)
            package_quote.is_selected = True
            package_quote.save()
            
            service_selection.selected_package_id = package_id
            service_selection.final_base_price = package_quote.base_price + package_quote.sqft_price
            service_selection.final_sqft_price = package_quote.sqft_price
            service_selection.final_total_price = package_quote.total_price
            service_selection.save()
            
            print(f"[DEBUG] Restored package selection: {package_id} with new price: {package_quote.total_price}")
            
        except CustomerPackageQuote.DoesNotExist:
            print(f"[ERROR] Could not restore package {package_id} - quote not found after regeneration")
            service_selection.selected_package = None
            service_selection.save()
    
    def _recalculate_final_totals_after_edit(self, submission):
        """Recalculate final totals after editing responses"""
        # Refresh submission from database to get latest data
        submission.refresh_from_db()
        
        # Prefetch package quotes to ensure we get the latest data
        service_selections = submission.customerserviceselection_set.filter(
            selected_package__isnull=False
        ).prefetch_related('package_quotes')
        
        total_base_price = Decimal('0.00')
        total_sqft_price = Decimal('0.00')
        total_adjustments = Decimal('0.00')
        total_addons_price = Decimal('0.00')
        total_services_price = Decimal('0.00')
        
        print(f"[DEBUG] Recalculating totals after edit for submission {submission.id}")
        
        for selection in service_selections:
            # Refresh selection to ensure we have latest package quotes
            selection.refresh_from_db()
            selected_quote = selection.package_quotes.filter(is_selected=True).first()
            if selected_quote:
                total_base_price += selected_quote.base_price
                total_sqft_price += selected_quote.sqft_price
                total_adjustments += selected_quote.question_adjustments
                total_services_price += selected_quote.total_price
                print(f"[DEBUG] Service {selection.service.name}: base={selected_quote.base_price}, "
                      f"sqft={selected_quote.sqft_price}, adjustments={selected_quote.question_adjustments}, "
                      f"surcharge={selected_quote.surcharge_amount}, package_total={selected_quote.total_price}")
        
        submission_addons = submission.submission_addons.select_related("addon")
        for sub_addon in submission_addons:
            subtotal = sub_addon.addon.base_price * sub_addon.quantity
            total_addons_price += subtotal
        
        print(f"[DEBUG] Total add-ons price: {total_addons_price}")
        
        # NOTE: Do NOT add submission.total_surcharges again since surcharges are already included in each package total
        pre_discount_total = (total_services_price + total_addons_price)
        
        final_total = pre_discount_total
        if submission.applied_coupon and submission.applied_coupon.is_valid():
            final_total = submission.applied_coupon.apply_discount(pre_discount_total)
            submission.is_coupon_applied = True
            submission.discounted_amount = pre_discount_total - final_total
        else:
            submission.is_coupon_applied = False
            submission.discounted_amount = Decimal('0.00')
        
        submission.total_base_price = total_base_price + total_sqft_price
        submission.total_adjustments = total_adjustments
        submission.total_addons_price = total_addons_price
        submission.final_total = final_total
        
        if submission.edit_count == 0 and not submission.original_final_total:
            submission.original_final_total = submission.final_total
        
        submission.save()
    
    def _capture_responses_snapshot(self, service_selection):
        """Capture current state of responses for history tracking"""
        snapshot = {
            'question_adjustments': service_selection.question_adjustments,
            'responses': []
        }
        
        for qr in service_selection.question_responses.all():
            response_data = {
                'question_id': str(qr.question.id),
                'question_text': qr.question.question_text,
                'yes_no_answer': qr.yes_no_answer,
                'text_answer': qr.text_answer,
            }
            snapshot['responses'].append(response_data)
        
        return snapshot
    
    def _generate_changes_summary(self, old_snapshot, new_responses):
        """Generate a human-readable summary of what changed"""
        changes = []
        
        old_responses_dict = {r['question_id']: r for r in old_snapshot.get('responses', [])}
        new_responses_dict = {r['question_id']: r for r in new_responses}
        
        for qid, new_resp in new_responses_dict.items():
            if qid in old_responses_dict:
                old_resp = old_responses_dict[qid]
                if old_resp.get('yes_no_answer') != new_resp.get('yes_no_answer'):
                    changes.append(f"Question {qid}: answer changed")
            else:
                changes.append(f"Question {qid}: new response added")
        
        for qid in old_responses_dict:
            if qid not in new_responses_dict:
                changes.append(f"Question {qid}: response removed")
        
        return changes if changes else ["No significant changes detected"]
    
    # ============ REUSE METHODS FROM SubmitServiceResponsesView ============
    # Import all necessary helper methods
    
    def _validate_conditional_responses(self, responses, service_id):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._validate_conditional_responses(self, responses, service_id)
    
    def _check_condition_met(self, parent_question, parent_response, conditional_question, conditional_response):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._check_condition_met(
            self, parent_question, parent_response, conditional_question, conditional_response
        )
    
    def _order_responses_by_dependency(self, responses):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._order_responses_by_dependency(self, responses)
    
    def _process_question_response_data(self, question, response_data, question_response):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._process_question_response_data(
            self, question, response_data, question_response
        )
    
    def _calculate_question_adjustment_for_averaging(self, question, response_data, question_response, service_selection):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._calculate_question_adjustment_for_averaging(
            self, question, response_data, question_response, service_selection
        )
    
    def _get_package_sqft_price(self, submission, package):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._get_package_sqft_price(self, submission, package)
    
    def _calculate_single_package_adjustment(self, question, response_data, question_response, package, base_sqft_price):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._calculate_single_package_adjustment(
            self, question, response_data, question_response, package, base_sqft_price
        )
    
    def _calculate_options_question_adjustment_from_stored(self, question_response, package, base_sqft_price):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._calculate_options_question_adjustment_from_stored(
            self, question_response, package, base_sqft_price
        )
    
    def _calculate_sub_questions_adjustment_from_stored(self, question_response, package, base_sqft_price):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._calculate_sub_questions_adjustment_from_stored(
            self, question_response, package, base_sqft_price
        )
    
    def _apply_pricing_rule(self, pricing_type, value, value_type, base_sqft_price, quantity=1):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._apply_pricing_rule(
            self, pricing_type, value, value_type, base_sqft_price, quantity
        )
    
    def _apply_quantity_discounts(self, question, option_adjustments, total_quantity, base_total):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._apply_quantity_discounts(
            self, question, option_adjustments, total_quantity, base_total
        )
    
    def _generate_all_package_quotes(self, service_selection, submission):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._generate_all_package_quotes(self, service_selection, submission)
    
    def _calculate_package_specific_adjustments_new(self, service_selection, package, base_sqft_price):
        """Reuse from SubmitServiceResponsesView"""
        return SubmitServiceResponsesView._calculate_package_specific_adjustments_new(
            self, service_selection, package, base_sqft_price
        )
    



class CustomerAvailabilityView(APIView):
    """
    API endpoint to manage availability slots for a submission.
    Supports bulk creation (multiple dates/times in one request).
    """
    permission_classes=[AllowAny]
    def post(self, request, submission_id):
        """Add one or more availability options for a submission"""
        try:
            submission = CustomerSubmission.objects.get(id=submission_id)
        except CustomerSubmission.DoesNotExist:
            return Response({"error": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = MultipleAvailabilitySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        availabilities_data = serializer.validated_data["availabilities"]

        # Enforce max 2 total per submission
        existing_count = submission.availabilities.count()
        if existing_count + len(availabilities_data) > 2:
            return Response(
                {"error": f"You already have {existing_count} availability option(s). "
                          "You can only have a total of 2."},
                status=status.HTTP_400_BAD_REQUEST
            )

        created = []
        with transaction.atomic():
            for item in availabilities_data:
                date = item["date"]
                time = item["time"]

                # Avoid duplicate entries for same date/time
                if not CustomerAvailability.objects.filter(submission=submission, date=date, time=time).exists():
                    availability = CustomerAvailability.objects.create(
                        submission=submission, date=date, time=time
                    )
                    created.append(availability)

        response_serializer = CustomerAvailabilitySerializer(created, many=True)
        return Response(
            {"message": "Availabilities added successfully", "data": response_serializer.data},
            status=status.HTTP_201_CREATED,
        )

    def get(self, request, submission_id):
        """Fetch all availability options for a submission"""
        try:
            submission = CustomerSubmission.objects.get(id=submission_id)
        except CustomerSubmission.DoesNotExist:
            return Response({"error": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        availabilities = submission.availabilities.all()
        serializer = CustomerAvailabilitySerializer(availabilities, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)



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


# class AddAddOnsToSubmissionView(APIView):
#     permission_classes = [AllowAny]  # ✅ no auth

#     def post(self, request, submission_id):
#         addon_ids = request.data.get("addon_ids", [])
#         if not addon_ids:
#             return Response({"error": "addon_ids list is required"}, status=400)

#         try:
#             submission = get_object_or_404(CustomerSubmission, id=submission_id)
#             addons = AddOnService.objects.filter(id__in=addon_ids)
            
#             if not addons.exists():
#                 return Response({"error": "No valid add-ons found"}, status=400)

#             # Attach addons (many-to-many add)
#             submission.addons.add(*addons)

#             # ✅ Recalculate total_addons_price
#             total_price = submission.addons.aggregate(
#                 total=Sum("base_price")
#             )["total"] or Decimal("0.00")
#             submission.total_addons_price = total_price
#             submission.save()

#             return Response({
#                 "message": "Add-ons added successfully",
#                 "total_addons_price": str(submission.total_addons_price),
#                 "addons": AddOnServiceSerializer(submission.addons.all(), many=True).data
#             })
#         except Exception as e:
#             return Response({"error": str(e)}, status=400)
        
#     def delete(self, request, submission_id):
#         addon_ids = request.data.get("addon_ids", [])
#         if not addon_ids:
#             return Response({"error": "addon_ids list is required"}, status=400)

#         try:
#             submission = get_object_or_404(CustomerSubmission, id=submission_id)
#             addons = AddOnService.objects.filter(id__in=addon_ids)

#             if not addons.exists():
#                 return Response({"error": "No valid add-ons found"}, status=400)

#             # Remove addons (many-to-many remove)
#             submission.addons.remove(*addons)

#             # ✅ Recalculate total_addons_price
#             total_price = submission.addons.aggregate(
#                 total=Sum("base_price")
#             )["total"] or Decimal("0.00")
#             submission.total_addons_price = total_price
#             submission.save()

#             return Response({
#                 "message": "Add-ons removed successfully",
#                 "total_addons_price": str(submission.total_addons_price),
#                 "addons": AddOnServiceSerializer(submission.addons.all(), many=True).data
#             })
#         except Exception as e:
#             return Response({"error": str(e)}, status=400)
        

from django.db.models import F
class AddAddOnsToSubmissionView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, submission_id):
        """
        Add or update add-ons with quantity for a submission.
        Example payload:
        {
            "addons": [
                {"addon_id": "uuid1", "quantity": 2},
                {"addon_id": "uuid2", "quantity": 1}
            ]
        }
        """
        addons_data = request.data.get("addons", [])
        if not addons_data:
            return Response({"error": "addons list is required"}, status=400)

        submission = get_object_or_404(CustomerSubmission, id=submission_id)

        total_addons_price = Decimal("0.00")

        for item in addons_data:
            addon_id = item.get("addon_id")
            quantity = int(item.get("quantity", 1))
            addon = get_object_or_404(AddOnService, id=addon_id)

            submission_addon, created = SubmissionAddOn.objects.update_or_create(
                submission=submission,
                addon=addon,
                defaults={"quantity": quantity}
            )

            total_addons_price += addon.base_price * quantity

        # Update submission total
        submission.total_addons_price = total_addons_price
        submission.save()

        serializer = SubmissionAddOnSerializer(submission.submission_addons.all(), many=True)
        return Response({
            "message": "Add-ons added/updated successfully",
            "total_addons_price": str(submission.total_addons_price),
            "addons": serializer.data
        })

    def delete(self, request, submission_id):
        addon_ids = request.data.get("addon_ids", [])
        if not addon_ids:
            return Response({"error": "addon_ids list is required"}, status=400)

        submission = get_object_or_404(CustomerSubmission, id=submission_id)

        SubmissionAddOn.objects.filter(submission=submission, addon_id__in=addon_ids).delete()

        # Recalculate total
        total = SubmissionAddOn.objects.filter(submission=submission).aggregate(
            total=Sum(F("addon__base_price") * F("quantity"))
        )["total"] or Decimal("0.00")

        submission.total_addons_price = total
        submission.save()

        serializer = SubmissionAddOnSerializer(submission.submission_addons.all(), many=True)
        return Response({
            "message": "Add-ons removed successfully",
            "total_addons_price": str(submission.total_addons_price),
            "addons": serializer.data
        })



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





# ✅ List all active & valid coupons
class CouponListView(generics.ListAPIView):
    serializer_class = CouponSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return Coupon.objects.filter(is_active=True).order_by("-created_at")


# ✅ Get details of a single coupon by code
class CouponDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, code):
        try:
            coupon = Coupon.objects.get(code=code, is_active=True)
        except Coupon.DoesNotExist:
            return Response({"detail": "Coupon not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = CouponSerializer(coupon)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ✅ Apply coupon to a specific submission
class ApplyCouponView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        code = request.data.get("code")
        amount = request.data.get("amount")
        submission_id = request.data.get("submission_id")

        # Validate request fields
        if not code or amount is None or not submission_id:
            return Response(
                {"detail": "Code, amount, and submission_id are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate amount format
        try:
            amount = Decimal(amount)
        except Exception:
            return Response({"detail": "Invalid amount format"}, status=status.HTTP_400_BAD_REQUEST)

        # Get coupon
        try:
            coupon = Coupon.objects.get(code=code, is_active=True)
        except Coupon.DoesNotExist:
            return Response({"detail": "Invalid coupon"}, status=status.HTTP_404_NOT_FOUND)

        # Check if coupon is valid
        if not coupon.is_valid():
            return Response({"detail": "Coupon is expired or inactive"}, status=status.HTTP_400_BAD_REQUEST)

        # Calculate discounts
        final_price = coupon.apply_discount(amount)
        discount_value = coupon.get_discount_amount(amount)

        # Attach coupon to submission
        submission = get_object_or_404(CustomerSubmission, id=submission_id)
        submission.applied_coupon = coupon
        submission.discounted_amount = discount_value
        submission.is_coupon_applied = True
        submission.final_total = final_price
        submission.save(update_fields=[
            "applied_coupon",
            "is_coupon_applied",
            "discounted_amount",
            "final_total",
            "updated_at",
        ])

        return Response({
            "original_amount": str(amount),
            "discounted_amount": str(discount_value),
            "final_price": str(final_price),
            "coupon": CouponSerializer(coupon).data,
            "submission_id": str(submission.id),
        }, status=status.HTTP_200_OK)


# ✅ Get only global coupons
class GlobalCouponListView(generics.ListAPIView):
    """View to fetch only global coupons - accessible by anyone"""
    serializer_class = CouponSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return Coupon.objects.filter(
            is_global=True,
            is_active=True
        ).order_by("-created_at")