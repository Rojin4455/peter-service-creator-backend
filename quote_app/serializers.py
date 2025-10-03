# user_serializers.py - Serializers for user-side functionality
from rest_framework import serializers
from decimal import Decimal
from service_app.models import (
    Service, Package, Feature, PackageFeature, Location, 
    Question, QuestionOption, SubQuestion, GlobalSizePackage,
    ServicePackageSizeMapping, QuestionPricing, OptionPricing, SubQuestionPricing, AddOnService,Coupon
)
from .models import (
    CustomerSubmission, CustomerServiceSelection, CustomerQuestionResponse,
    CustomerOptionResponse, CustomerSubQuestionResponse, CustomerPackageQuote
)

from service_app.serializers import ServiceSettingsSerializer, CouponSerializer

class LocationPublicSerializer(serializers.ModelSerializer):
    """Public serializer for locations"""
    class Meta:
        model = Location
        fields = ['id', 'name', 'address', 'trip_surcharge','latitude','longitude']

class ServicePublicSerializer(serializers.ModelSerializer):
    packages_count = serializers.SerializerMethodField()
    service_settings = ServiceSettingsSerializer(read_only=True, source='settings')
    
    class Meta:
        model = Service
        fields = ['id', 'name', 'description', 'packages_count', 'service_settings']
    
    # class Meta:
    #     model = Service
    #     fields = ['id', 'name', 'description', 'packages_count','service_settings']
    
    def get_packages_count(self, obj):
        return obj.packages.filter(is_active=True).count()

class PackagePublicSerializer(serializers.ModelSerializer):
    """Public serializer for packages"""
    class Meta:
        model = Package
        fields = ['id', 'name', 'base_price', 'order']

class FeaturePublicSerializer(serializers.ModelSerializer):
    """Public serializer for features"""
    class Meta:
        model = Feature
        fields = ['id', 'name', 'description']

class QuestionOptionPublicSerializer(serializers.ModelSerializer):
    """Public serializer for question options"""
    class Meta:
        model = QuestionOption
        fields = ['id', 'option_text', 'order', 'allow_quantity', 'max_quantity','image']

class SubQuestionPublicSerializer(serializers.ModelSerializer):
    """Public serializer for sub-questions"""
    class Meta:
        model = SubQuestion
        fields = ['id', 'sub_question_text', 'order','image']

class QuestionPublicSerializer(serializers.ModelSerializer):
    """Public serializer for questions"""
    options = QuestionOptionPublicSerializer(many=True, read_only=True)
    sub_questions = SubQuestionPublicSerializer(many=True, read_only=True)
    child_questions = serializers.SerializerMethodField()
    
    class Meta:
        model = Question
        fields = [
            'id', 'question_text', 'question_type', 'order',
            'parent_question', 'condition_answer', 'condition_option',
            'options', 'sub_questions', 'child_questions','image'
        ]
    
    def get_child_questions(self, obj):
        child_questions = obj.child_questions.filter(is_active=True).order_by('order')
        return QuestionPublicSerializer(child_questions, many=True, context=self.context).data

class GlobalSizePackagePublicSerializer(serializers.ModelSerializer):
    """Public serializer for global size packages"""
    class Meta:
        model = GlobalSizePackage
        fields = ['id', 'min_sqft', 'max_sqft']

# Customer submission serializers
class CustomerSubmissionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating customer submissions"""

    class Meta:
        model = CustomerSubmission
        fields = [
            "first_name", "last_name", "company_name",
            "customer_email", "customer_phone", "postal_code",
            "allow_sms", "allow_email",
            "street_address", "location",
            "heard_about_us",
            "property_type", "property_name", "num_floors", "is_previous_customer",
            "size_range", "actual_sqft",
        ]

    def create(self, validated_data):
        from django.utils import timezone
        from datetime import timedelta

        submission = CustomerSubmission.objects.create(**validated_data)
        submission.expires_at = timezone.now() + timedelta(days=30)
        submission.save()
        return submission

class CustomerServiceSelectionSerializer(serializers.ModelSerializer):
    """Serializer for service selections"""
    service_name = serializers.CharField(source='service.name', read_only=True)
    
    class Meta:
        model = CustomerServiceSelection
        fields = [
            'id', 'service', 'service_name', 'base_price_total',
            'question_adjustments', 'surcharge_applicable', 'surcharge_amount'
        ]
        read_only_fields = ['id', 'base_price_total', 'question_adjustments', 'surcharge_amount']

class CustomerOptionResponseSerializer(serializers.ModelSerializer):
    """Serializer for option responses"""
    option_text = serializers.CharField(source='option.option_text', read_only=True)
    
    class Meta:
        model = CustomerOptionResponse
        fields = ['id', 'option', 'option_text', 'quantity', 'price_adjustment']
        read_only_fields = ['id', 'price_adjustment']

class CustomerSubQuestionResponseSerializer(serializers.ModelSerializer):
    """Serializer for sub-question responses"""
    sub_question_text = serializers.CharField(source='sub_question.sub_question_text', read_only=True)
    
    class Meta:
        model = CustomerSubQuestionResponse
        fields = ['id', 'sub_question', 'sub_question_text', 'answer', 'price_adjustment']
        read_only_fields = ['id', 'price_adjustment']

class CustomerQuestionResponseSerializer(serializers.ModelSerializer):
    """Serializer for question responses"""
    question_text = serializers.CharField(source='question.question_text', read_only=True)
    question_type = serializers.CharField(source='question.question_type', read_only=True)
    option_responses = CustomerOptionResponseSerializer(many=True, read_only=True)
    sub_question_responses = CustomerSubQuestionResponseSerializer(many=True, read_only=True)
    
    class Meta:
        model = CustomerQuestionResponse
        fields = [
            'id', 'question', 'question_text', 'question_type',
            'yes_no_answer', 'text_answer', 'option_responses',
            'sub_question_responses', 'price_adjustment'
        ]
        read_only_fields = ['id', 'price_adjustment']

class ServiceQuestionResponseSerializer(serializers.Serializer):
    """Serializer for submitting service question responses"""
    service_id = serializers.UUIDField()
    responses = serializers.ListField(child=serializers.DictField())

class CustomerPackageQuoteSerializer(serializers.ModelSerializer):
    """Serializer for package quotes"""
    package_name = serializers.CharField(source='package.name', read_only=True)
    package_description = serializers.CharField(source='package.description', read_only=True, default='')
    service_name = serializers.CharField(source='service_selection.service.name', read_only=True)
    included_features_details = serializers.SerializerMethodField()
    excluded_features_details = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomerPackageQuote
        fields = [
            'id', 'package', 'package_name', 'package_description', 'service_name',
            'base_price', 'sqft_price', 'question_adjustments',
            'surcharge_amount', 'total_price', 'is_selected',
            'included_features', 'excluded_features',
            'included_features_details', 'excluded_features_details'
        ]
    
    def get_included_features_details(self, obj):
        if not obj.included_features:
            return []
        features = Feature.objects.filter(id__in=obj.included_features)
        return FeaturePublicSerializer(features, many=True).data
    
    def get_excluded_features_details(self, obj):
        if not obj.excluded_features:
            return []
        features = Feature.objects.filter(id__in=obj.excluded_features)
        return FeaturePublicSerializer(features, many=True).data

class AddOnServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddOnService
        fields = ["id", "name", "description", "base_price"]


from service_app.serializers import GlobalSizePackageSerializer
class CustomerSubmissionDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for customer submissions"""
    location_details = LocationPublicSerializer(source='location', read_only=True)
    service_selections = serializers.SerializerMethodField()
    size_range = GlobalSizePackageSerializer(read_only=True)
    addons = AddOnServiceSerializer(many=True, read_only=True)
    applied_coupon = CouponSerializer(read_only=True)
    

    class Meta:
        model = CustomerSubmission
        fields = [
            'id',
            # Customer info
            'first_name', 'last_name', 'company_name',
            'customer_email', 'customer_phone', 'postal_code',
            'allow_sms', 'allow_email','is_bid_in_person',

            # Address info
            'street_address', 'location', 'location_details',

            # Discovery
            'heard_about_us',

            # Property info
            'property_type', 'property_name', 'num_floors', 'is_previous_customer',

            # Size info
            'size_range', 'actual_sqft',

            # Submission details
            'status', 'selected_services',

            # Pricing
            'total_base_price', 'total_adjustments', 'total_surcharges',
            'final_total', 'quote_surcharge_applicable',

            # Extra
            'additional_data','total_addons_price','addons',

            # Timestamps
            'created_at', 'updated_at', 'expires_at',

            # Relations
            'service_selections',

            #coupon
            'applied_coupon',
            'is_coupon_applied'
        ]

    def get_service_selections(self, obj):
        selections = obj.customerserviceselection_set.all().prefetch_related(
            'package_quotes__package',
            'question_responses__option_responses',
            'question_responses__sub_question_responses'
        )
        return CustomerServiceSelectionDetailSerializer(selections, many=True).data

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        return fields
    


class CustomerServiceSelectionDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for service selections"""
    service_details = ServicePublicSerializer(source='service', read_only=True)
    selected_package_details = PackagePublicSerializer(source='selected_package', read_only=True)
    package_quotes = serializers.SerializerMethodField()
    question_responses = CustomerQuestionResponseSerializer(many=True, read_only=True)

    class Meta:
        model = CustomerServiceSelection
        fields = [
            'id', 'service', 'service_details',
            'selected_package', 'selected_package_details',
            'question_adjustments', 'surcharge_applicable', 'surcharge_amount',
            'final_base_price', 'final_sqft_price', 'final_total_price',
            'package_quotes', 'question_responses'
        ]

    def get_package_quotes(self, obj):
        if obj.selected_package:
            quotes = obj.package_quotes.filter(is_selected=True)
        else:
            quotes = obj.package_quotes.all().order_by('package__order')

        filtered_quotes = []
        for quote in quotes:
            package = quote.package

            # Gather pricing rules
            q_rules = package.question_pricing.all()
            sq_rules = package.sub_question_pricing.all()
            o_rules = package.option_pricing.all()

            # Collect only rules that match the customer's responses
            active_rules = []

            # Check question responses
            for response in obj.question_responses.all():
                # Yes/No type
                if response.yes_no_answer is True:
                    active_rules += list(q_rules.filter(question=response.question))

                # Options type
                for opt_response in response.option_responses.all():
                    active_rules += list(o_rules.filter(option=opt_response.option))

                # Sub-questions
                for sub_resp in response.sub_question_responses.all():
                    if sub_resp.answer is True:  # ✅ use 'answer' field
                        active_rules += list(sq_rules.filter(sub_question=sub_resp.sub_question))

            # If no active rules → keep it
            if not active_rules:
                filtered_quotes.append(quote)
                continue

            # Skip package if *all active rules* are fixed_price
            effective_types = [r.yes_pricing_type if hasattr(r, "yes_pricing_type") else r.pricing_type for r in active_rules]
            if all(t == "fixed_price" for t in effective_types):
                continue

            filtered_quotes.append(quote)

        return CustomerPackageQuoteSerializer(filtered_quotes, many=True).data

    

# Utility serializers
class PricingCalculationRequestSerializer(serializers.Serializer):
    """Serializer for pricing calculation requests"""
    submission_id = serializers.UUIDField()
    service_responses = ServiceQuestionResponseSerializer(many=True)

class ConditionalQuestionRequestSerializer(serializers.Serializer):
    """Serializer for conditional question requests"""
    parent_question_id = serializers.UUIDField()
    answer = serializers.CharField(required=False, allow_blank=True)
    option_id = serializers.UUIDField(required=False, allow_null=True)


class PackageSelectionSerializer(serializers.Serializer):
    """Serializer for package selection"""
    service_selection_id = serializers.UUIDField()
    package_id = serializers.UUIDField()




class ConditionalQuestionResponseSerializer(serializers.Serializer):
    """Enhanced serializer for question responses including conditional logic"""
    question_id = serializers.UUIDField()
    question_type = serializers.CharField()
    
    # For conditional questions
    parent_question_id = serializers.UUIDField(required=False, allow_null=True)
    condition_type = serializers.CharField(required=False, allow_blank=True)
    condition_value = serializers.CharField(required=False, allow_blank=True)
    
    # Response data based on question type
    yes_no_answer = serializers.BooleanField(required=False, allow_null=True)
    text_answer = serializers.CharField(required=False, allow_blank=True)
    
    # For option-based questions
    selected_options = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True
    )
    
    # For multiple_yes_no questions
    sub_question_answers = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True
    )
    
    def validate(self, data):
        """Validate response data based on question type"""
        question_type = data.get('question_type')
        
        if question_type == 'yes_no':
            if data.get('yes_no_answer') is None:
                raise serializers.ValidationError("yes_no_answer is required for yes_no questions")
        
        elif question_type in ['describe', 'quantity']:
            if not data.get('selected_options'):
                raise serializers.ValidationError("selected_options is required for describe/quantity questions")
        
        elif question_type == 'multiple_yes_no':
            if not data.get('sub_question_answers'):
                raise serializers.ValidationError("sub_question_answers is required for multiple_yes_no questions")
        
        # Validate conditional question requirements
        if data.get('parent_question_id'):
            if not data.get('condition_type') or not data.get('condition_value'):
                raise serializers.ValidationError(
                    "condition_type and condition_value are required for conditional questions"
                )
        
        return data

class ServiceResponseSubmissionSerializer(serializers.Serializer):
    """Serializer for the complete service response submission"""
    responses = ConditionalQuestionResponseSerializer(many=True)
    
    def validate_responses(self, value):
        """Validate the responses list"""
        if not value:
            raise serializers.ValidationError("At least one response is required")
        
        # Check for duplicate question responses
        question_ids = [r['question_id'] for r in value]
        if len(question_ids) != len(set(question_ids)):
            raise serializers.ValidationError("Duplicate question responses found")
        
        return value
    



class SelectedPackageSerializer(serializers.Serializer):
    """Serializer for selected package information"""
    service_selection_id = serializers.UUIDField()
    package_id = serializers.UUIDField()
    package_name = serializers.CharField(read_only=True)
    total_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

class SubmitFinalQuoteSerializer(serializers.Serializer):
    """Serializer for final quote submission"""
    customer_confirmation = serializers.BooleanField(default=True)
    selected_packages = SelectedPackageSerializer(many=True, required=False)
    additional_notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    signature = serializers.CharField(required=False, allow_blank=True)
    coupon_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    preferred_contact_method = serializers.ChoiceField(
        choices=[('email', 'Email'), ('phone', 'Phone'), ('both', 'Both')],
        default='email'
    )
    preferred_start_date = serializers.DateField(required=False, allow_null=True)
    terms_accepted = serializers.BooleanField(default=True)
    marketing_consent = serializers.BooleanField(default=False)
    
    def validate_customer_confirmation(self, value):
        if not value:
            raise serializers.ValidationError("Customer confirmation is required")
        return value
    
    def validate_terms_accepted(self, value):
        if not value:
            raise serializers.ValidationError("Terms and conditions must be accepted")
        return value
    









class CouponSerializer(serializers.ModelSerializer):
    is_valid = serializers.SerializerMethodField()

    class Meta:
        model = Coupon
        fields = [
            "id", "code", "discount_type", "discount_value",
            "expiration_date", "used_count", "is_active",
            "is_valid", "created_at", "updated_at"
        ]

    def get_is_valid(self, obj):
        return obj.is_valid()
    


class SubmissionCouponSerializer(serializers.ModelSerializer):
    applied_coupon = CouponSerializer()

    class Meta:
        model = CustomerSubmission
        fields = ["id", "final_total", "discounted_total", "applied_coupon"]