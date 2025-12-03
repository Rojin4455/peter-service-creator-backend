# serializers.py
from rest_framework import serializers
from django.contrib.auth import authenticate
from decimal import Decimal
from .models import (
    User, Location, Service, Package, Feature, PackageFeature,
    Question, QuestionOption, QuestionPricing, OptionPricing,
    Order, OrderQuestionAnswer,ServiceSettings, QuestionResponse, SubQuestion, SubQuestionPricing, SubQuestionResponse,
    OptionResponse,AddOnService,QuantityDiscount,Coupon
)
from quote_app.models import CustomerSubmission


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model"""
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_admin', 'created_at']
        read_only_fields = ['id', 'created_at']


class LoginSerializer(serializers.Serializer):
    """Login serializer for admin authentication"""
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        username = data.get('username')
        password = data.get('password')

        if username and password:
            user = authenticate(username=username, password=password)
            if user:
                if not user.is_admin:
                    raise serializers.ValidationError("Only admins can access this interface.")
                if not user.is_active:
                    raise serializers.ValidationError("User account is disabled.")
                data['user'] = user
            else:
                raise serializers.ValidationError("Invalid credentials.")
        else:
            raise serializers.ValidationError("Must include username and password.")
        
        return data


class LocationSerializer(serializers.ModelSerializer):
    """Serializer for Location model"""
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Location
        fields = [
            'id', 'name', 'address', 'latitude', 'longitude', 
            'trip_surcharge', 'google_place_id', 'is_active',
            'created_at', 'updated_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']

    def create(self, validated_data):
        # Set created_by from request user
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['created_by'] = request.user
        return super().create(validated_data)


class PackageSerializer(serializers.ModelSerializer):
    """Serializer for Package model"""
    service_name = serializers.CharField(source='service.name', read_only=True)
    features = serializers.SerializerMethodField()

    class Meta:
        model = Package
        fields = [
            'id', 'service', 'service_name', 'name', 'base_price', 
            'order', 'is_active', 'created_at', 'updated_at', 'features'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_features(self, obj):
        """Get features included in the package"""
        package_features = PackageFeature.objects.filter(package=obj)
        return [
            {
                'id':pf.id,
                'feature': pf.feature.id,
                'name': pf.feature.name,
                'description': pf.feature.description,
                'is_included': pf.is_included
            }
            for pf in package_features
        ]

    
    def create(self, validated_data):
        package = super().create(validated_data)

        # Automatically link to all existing features under the same service
        features = Feature.objects.filter(service=package.service, is_active=True)
        package_features = [
            PackageFeature(package=package, feature=feature, is_included=False)
            for feature in features
        ]
        PackageFeature.objects.bulk_create(package_features)
        return package


class BulkSubQuestionPricingSerializer(serializers.Serializer):
    """Serializer for bulk updating sub-question pricing rules"""
    sub_question_id = serializers.UUIDField()
    pricing_rules = serializers.ListField(
        child=serializers.DictField(), 
        allow_empty=False
    )


class OptionResponseSerializer(serializers.ModelSerializer):
    """Serializer for customer option responses"""
    option_text = serializers.CharField(source='option.option_text', read_only=True)
    
    class Meta:
        model = OptionResponse
        fields = ['id', 'option', 'option_text', 'quantity', 'created_at']
        read_only_fields = ['id', 'created_at']


class SubQuestionResponseSerializer(serializers.ModelSerializer):
    """Serializer for customer sub-question responses"""
    sub_question_text = serializers.CharField(source='sub_question.sub_question_text', read_only=True)
    
    class Meta:
        model = SubQuestionResponse
        fields = ['id', 'sub_question', 'sub_question_text', 'answer', 'created_at']
        read_only_fields = ['id', 'created_at']


class QuestionResponseSerializer(serializers.ModelSerializer):
    """Serializer for customer question responses"""
    question_text = serializers.CharField(source='question.question_text', read_only=True)
    question_type = serializers.CharField(source='question.question_type', read_only=True)
    option_responses = OptionResponseSerializer(many=True, read_only=True)
    sub_question_responses = SubQuestionResponseSerializer(many=True, read_only=True)
    
    class Meta:
        model = QuestionResponse
        fields = [
            'id', 'question', 'question_text', 'question_type',
            'yes_no_answer', 'text_answer', 'option_responses', 
            'sub_question_responses', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class PricingCalculationSerializer(serializers.Serializer):
    """Serializer for pricing calculation requests"""
    service_id = serializers.UUIDField()
    package_id = serializers.UUIDField()
    responses = serializers.ListField(child=serializers.DictField())

    def validate_responses(self, value):
        """Validate response format"""
        for response in value:
            if 'question_id' not in response:
                raise serializers.ValidationError("Each response must have a question_id")
        return value

class FeatureSerializer(serializers.ModelSerializer):
    """Serializer for Feature model"""
    service_name = serializers.CharField(source='service.name', read_only=True)

    class Meta:
        model = Feature
        fields = [
            'id', 'service', 'service_name', 'name', 'description',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def create(self, validated_data):
        feature = super().create(validated_data)

        # Automatically link to all existing packages under the same service
        packages = Package.objects.filter(service=feature.service, is_active=True)
        package_features = [
            PackageFeature(package=package, feature=feature, is_included=False)
            for package in packages
        ]
        PackageFeature.objects.bulk_create(package_features)
        return feature


class PackageFeatureSerializer(serializers.ModelSerializer):
    """Serializer for PackageFeature model"""
    package_name = serializers.CharField(source='package.name', read_only=True)
    feature_name = serializers.CharField(source='feature.name', read_only=True)

    class Meta:
        model = PackageFeature
        fields = [
            'id', 'package', 'package_name', 'feature', 'feature_name',
            'is_included', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class QuestionOptionSerializer(serializers.ModelSerializer):
    """Serializer for QuestionOption model"""
    pricing_rules = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = QuestionOption
        fields = [
            'id', 'option_text', 'order', 'is_active', 'created_at', 'question',
            'allow_quantity', 'max_quantity', 'pricing_rules','image'
        ]
        extra_kwargs = {
            'question': {'required': False},
            'option_text': {'allow_blank': True, 'required': False}  # Allow blank for measurement questions
        }
        read_only_fields = ['id', 'created_at']

    def get_pricing_rules(self, obj):
        return OptionPricingSerializer(obj.pricing_rules, many=True).data
    
class SubQuestionPricingSerializer(serializers.ModelSerializer):
    """Serializer for SubQuestionPricing model"""
    package_name = serializers.CharField(source='package.name', read_only=True)
    sub_question_text = serializers.CharField(source='sub_question.sub_question_text', read_only=True)

    class Meta:
        model = SubQuestionPricing
        fields = [
            'id', 'sub_question', 'sub_question_text', 'package', 'package_name',
            'yes_pricing_type', 'yes_value', 'created_at', 'updated_at','value_type'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class SubQuestionSerializer(serializers.ModelSerializer):
    """Serializer for SubQuestion model"""
    pricing_rules = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = SubQuestion
        fields = [
            'id', 'parent_question', 'sub_question_text', 'order', 
            'is_active', 'created_at', 'pricing_rules','image'
        ]
        extra_kwargs = {
            'parent_question': {'required': False}
        }
        read_only_fields = ['id', 'created_at']

    def get_pricing_rules(self, obj):
        return SubQuestionPricingSerializer(obj.pricing_rules, many=True).data



class OptionPricingSerializer(serializers.ModelSerializer):
    """Serializer for OptionPricing model"""
    package_name = serializers.CharField(source='package.name', read_only=True)
    option_text = serializers.CharField(source='option.option_text', read_only=True)

    class Meta:
        model = OptionPricing
        fields = [
            'id', 'option', 'option_text', 'package', 'package_name',
            'pricing_type', 'value', 'created_at', 'updated_at','value_type'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']



class QuestionPricingSerializer(serializers.ModelSerializer):
    """Serializer for QuestionPricing model"""
    package_name = serializers.CharField(source='package.name', read_only=True)
    question_text = serializers.CharField(source='question.question_text', read_only=True)

    class Meta:
        model = QuestionPricing
        fields = [
            'id', 'question', 'question_text', 'package', 'package_name',
            'yes_pricing_type', 'yes_value', 'created_at', 'updated_at','value_type'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class QuestionSerializer(serializers.ModelSerializer):
    """Serializer for Question model"""
    service_name = serializers.CharField(source='service.name', read_only=True)
    parent_question_text = serializers.CharField(source='parent_question.question_text', read_only=True)
    condition_option_text = serializers.CharField(source='condition_option.option_text', read_only=True)
    
    options = QuestionOptionSerializer(many=True, read_only=True)
    sub_questions = SubQuestionSerializer(many=True, read_only=True)
    child_questions = serializers.SerializerMethodField(read_only=True)
    pricing_rules = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Question
        fields = [
            'id', 'service', 'service_name', 'parent_question', 'parent_question_text',
            'condition_answer', 'condition_option', 'condition_option_text',
            'question_text', 'question_type', 'order', 'is_active','image',
            'created_at', 'updated_at', 'options', 'sub_questions', 
            'child_questions', 'pricing_rules', 'is_conditional', 'is_parent',
            'measurement_unit', 'allow_quantity', 'max_measurements'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'is_conditional', 'is_parent']

    def get_child_questions(self, obj):
        """Get child questions recursively"""
        child_questions = obj.child_questions.all().order_by('order')
        return QuestionSerializer(child_questions, many=True, context=self.context).data

    def get_pricing_rules(self, obj):
        if obj.question_type in ['yes_no', 'conditional', 'measurement']:
            return QuestionPricingSerializer(obj.pricing_rules, many=True).data
        elif obj.question_type in ['describe', 'quantity']:
            all_option_pricing = OptionPricing.objects.filter(option__in=obj.options.all())
            return OptionPricingSerializer(all_option_pricing, many=True).data
        elif obj.question_type == 'multiple_yes_no':
            all_sub_question_pricing = SubQuestionPricing.objects.filter(sub_question__in=obj.sub_questions.all())
            return SubQuestionPricingSerializer(all_sub_question_pricing, many=True).data
        return []


class ServiceSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceSettings
        fields = [
            'id',
            'general_disclaimer',
            'bid_in_person_disclaimer',
            'apply_area_minimum',
            'apply_house_size_minimum',
            'apply_trip_charge_to_bid',
            'enable_dollar_minimum',
        ]



class ServiceSerializer(serializers.ModelSerializer):
    """Serializer for Service model"""
    packages = PackageSerializer(many=True, read_only=True)  # Assuming you have this
    features = FeatureSerializer(many=True, read_only=True)  # Assuming you have this
    questions = serializers.SerializerMethodField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    settings = ServiceSettingsSerializer(read_only=True)

    class Meta:
        model = Service
        fields = [
            'id', 'name', 'description', 'is_active', 'order',
            'created_at', 'updated_at', 'created_by', 'created_by_name','image',
            'questions' ,'packages', 'features','settings','is_commercial','is_residential','is_enable_dollar_minimum'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']

    def get_questions(self, obj):
        """Get only root questions (non-conditional ones)"""
        root_questions = obj.questions.filter(
            parent_question__isnull=True
        ).order_by('order')
        return QuestionSerializer(root_questions, many=True, context=self.context).data

    def create(self, validated_data):
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['created_by'] = request.user
        return super().create(validated_data)



class ServiceListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for Service list view"""
    # packages_count = serializers.IntegerField(source='packages.count', read_only=True)
    # features_count = serializers.IntegerField(source='features.count', read_only=True)
    questions_count = serializers.IntegerField(source='questions.count', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Service
        fields = "__all__" 


# Nested serializers for complex operations
class QuestionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating questions with nested data"""
    options = QuestionOptionSerializer(many=True, required=False)
    sub_questions = SubQuestionSerializer(many=True, required=False)
    # image = serializers.ImageField(required=False, allow_null=True)
    
    class Meta:
        model = Question
        fields = [
            'service', 'parent_question', 'condition_answer', 'condition_option',
            'question_text', 'question_type', 'order', 'is_active', 
            'options', 'sub_questions',"id",'image',
            'measurement_unit', 'allow_quantity', 'max_measurements'
        ]


    # def to_internal_value(self, data):
    #     # handle options & sub_questions if they come as JSON strings
    #     import json
    #     data = data.copy()
    #     if isinstance(data.get('options'), str):
    #         try:
    #             data['options'] = json.loads(data['options'])
    #         except Exception:
    #             raise serializers.ValidationError({"options": "Invalid JSON format"})
    #     if isinstance(data.get('sub_questions'), str):
    #         try:
    #             data['sub_questions'] = json.loads(data['sub_questions'])
    #         except Exception:
    #             raise serializers.ValidationError({"sub_questions": "Invalid JSON format"})
    #     return super().to_internal_value(data)

    def validate(self, data):
        question_type = data.get('question_type') or getattr(self.instance, "question_type", None)
        options = data.get('options', None)
        sub_questions = data.get('sub_questions', None)
        parent_question = data.get('parent_question') or getattr(self.instance, "parent_question", None)
        condition_answer = data.get('condition_answer') or getattr(self.instance, "condition_answer", None)

        # Conditional questions
        if parent_question and not condition_answer:
            raise serializers.ValidationError(
                "Conditional questions must have a condition_answer"
            )

        # Validate question type requirements
        if question_type in ['describe', 'quantity', 'measurement']:
            # Check both incoming data and existing DB options
            existing_options = self.instance.options.exists() if self.instance else False
            if options is None and not existing_options:  # only fail if neither exists
                raise serializers.ValidationError(
                    f"{question_type} questions must have options"
                )
            
            # Additional validation for measurement questions
            if question_type == 'measurement':
                measurement_unit = data.get('measurement_unit') or getattr(self.instance, "measurement_unit", None)
                if not measurement_unit:
                    raise serializers.ValidationError(
                        "Measurement questions must have a measurement_unit specified"
                    )

        if question_type == 'multiple_yes_no':
            existing_subs = self.instance.sub_questions.exists() if self.instance else False
            if sub_questions is None and not existing_subs:
                raise serializers.ValidationError(
                    "multiple_yes_no questions must have sub_questions"
                )

        return data

    def create(self, validated_data):
        print("validated_data: ",validated_data)
        options_data = validated_data.pop('options', [])
        sub_questions_data = validated_data.pop('sub_questions', [])
        
        question_type = validated_data.get('question_type')
        question = Question.objects.create(**validated_data)
        
        # Create options if provided
        # For measurement questions, skip options with blank option_text
        for option_data in options_data:
            # Skip options with blank option_text for measurement questions
            if question_type == 'measurement' and not option_data.get('option_text', '').strip():
                continue
            QuestionOption.objects.create(question=question, **option_data)
        
        # Create sub-questions if provided
        for sub_question_data in sub_questions_data:
            SubQuestion.objects.create(parent_question=question, **sub_question_data)
            
        return question

    def update(self, instance, validated_data):
        options_data = validated_data.pop('options', [])
        sub_questions_data = validated_data.pop('sub_questions', [])
        
        # Update question fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Handle options update (simple approach - recreate all)
        if options_data:
            instance.options.all().delete()
            question_type = instance.question_type
            for option_data in options_data:
                # Remove 'question' from option_data if present to avoid duplicate argument
                option_data.pop('question', None)
                # Remove 'pricing_rules' if present (it's read-only)
                option_data.pop('pricing_rules', None)
                # Skip options with blank option_text for measurement questions
                if question_type == 'measurement' and not option_data.get('option_text', '').strip():
                    continue
                QuestionOption.objects.create(question=instance, **option_data)
        
        # Handle sub-questions update (simple approach - recreate all)
        if sub_questions_data:
            instance.sub_questions.all().delete()
            for sub_question_data in sub_questions_data:
                # Remove 'parent_question' if present to avoid duplicate argument
                sub_question_data.pop('parent_question', None)
                SubQuestion.objects.create(parent_question=instance, **sub_question_data)
        
        return instance



class PackageWithFeaturesSerializer(serializers.ModelSerializer):
    """Serializer for Package with included features"""
    features = serializers.SerializerMethodField()

    class Meta:
        model = Package
        fields = [
            'id', 'service', 'name', 'base_price', 'order', 
            'is_active', 'created_at', 'updated_at', 'features'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_features(self, obj):
        package_features = PackageFeature.objects.filter(package=obj, is_included=True)
        return [
            {
                'id': pf.feature.id,
                'name': pf.feature.name,
                'description': pf.feature.description,
                'is_included': pf.is_included
            }
            for pf in package_features
        ]


# Future serializers for user side
class OrderQuestionAnswerSerializer(serializers.ModelSerializer):
    """Serializer for OrderQuestionAnswer model"""
    question_text = serializers.CharField(source='question.question_text', read_only=True)
    question_type = serializers.CharField(source='question.question_type', read_only=True)
    selected_option_text = serializers.CharField(source='selected_option.option_text', read_only=True)

    class Meta:
        model = OrderQuestionAnswer
        fields = [
            'id', 'question', 'question_text', 'question_type',
            'yes_no_answer', 'selected_option', 'selected_option_text',
            'price_adjustment', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class OrderSerializer(serializers.ModelSerializer):
    """Serializer for Order model"""
    service_name = serializers.CharField(source='service.name', read_only=True)
    package_name = serializers.CharField(source='package.name', read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)
    question_answers = OrderQuestionAnswerSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'service', 'service_name', 'package', 'package_name',
            'location', 'location_name', 'base_price', 'trip_surcharge',
            'question_adjustments', 'total_price', 'status',
            'created_at', 'updated_at', 'question_answers'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# Utility serializers for complex operations
class BulkPricingUpdateSerializer(serializers.Serializer):
    """Serializer for bulk updating pricing rules"""
    question_id = serializers.UUIDField()
    pricing_rules = serializers.ListField(
        child=serializers.DictField(), 
        allow_empty=False
    )

    def validate_pricing_rules(self, value):
        """Validate pricing rules structure"""
        for rule in value:
            required_fields = ['package_id', 'pricing_type', 'value']
            for field in required_fields:
                if field not in rule:
                    raise serializers.ValidationError(f"Each pricing rule must have a {field}")
        return value

class ServiceAnalyticsSerializer(serializers.Serializer):
    """Serializer for service analytics data"""
    service_id = serializers.UUIDField()
    service_name = serializers.CharField()
    total_packages = serializers.IntegerField()
    total_features = serializers.IntegerField()
    total_questions = serializers.IntegerField()
    average_package_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    created_at = serializers.DateTimeField()




from .models import GlobalPackageTemplate, GlobalSizePackage, ServicePackageSizeMapping

from rest_framework import serializers
from .models import (
    PropertyType, GlobalSizePackage, GlobalPackageTemplate, 
    ServicePackageSizeMapping, Service, Package
)

class PropertyTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyType
        fields = ['id', 'name', 'description', 'is_active', 'order']


class GlobalPackageTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlobalPackageTemplate
        fields = ['id', 'label', 'price', 'order']


class GlobalSizePackageSerializer(serializers.ModelSerializer):
    template_prices = GlobalPackageTemplateSerializer(many=True)
    property_type_name = serializers.CharField(source='property_type.name', read_only=True)

    class Meta:
        model = GlobalSizePackage
        fields = [
            'id', 'property_type', 'property_type_name', 'min_sqft', 
            'max_sqft', 'order', 'template_prices'
        ]

    def create(self, validated_data):
        templates = validated_data.pop('template_prices', [])
        global_size = GlobalSizePackage.objects.create(**validated_data)

        # Create template prices
        for template in templates:
            GlobalPackageTemplate.objects.create(global_size=global_size, **template)

        # Auto-map to all services' packages by order
        all_services = Service.objects.prefetch_related('packages').filter(is_active=True)

        for service in all_services:
            service_packages = list(service.packages.filter(is_active=True).order_by('order'))
            sorted_templates = sorted(global_size.template_prices.all(), key=lambda t: t.order)

            for idx, template in enumerate(sorted_templates):
                if idx < len(service_packages):
                    service_package = service_packages[idx]
                    # Avoid duplicates
                    ServicePackageSizeMapping.objects.get_or_create(
                        service_package=service_package,
                        global_size=global_size,
                        defaults={'price': template.price}
                    )

        return global_size
    
    def update(self, instance, validated_data):
        templates_data = validated_data.pop('template_prices', [])
        
        # Update basic fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update template_prices
        existing_templates = {t.order: t for t in instance.template_prices.all()}
        for template_data in templates_data:
            order = template_data.get('order')
            if order in existing_templates:
                # Update existing
                template_obj = existing_templates[order]
                for attr, value in template_data.items():
                    setattr(template_obj, attr, value)
                template_obj.save()
            else:
                # Create new
                GlobalPackageTemplate.objects.create(global_size=instance, **template_data)

        return instance

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation['template_prices'] = GlobalPackageTemplateSerializer(
            instance.template_prices.all().order_by('order'), many=True
        ).data
        return representation

    


class ServicePackageSizeMappingSerializer(serializers.ModelSerializer):
    service_package_name = serializers.CharField(source='service_package.name', read_only=True)
    global_size_range = serializers.SerializerMethodField()
    property_type_name = serializers.CharField(source='global_size.property_type.name', read_only=True)

    class Meta:
        model = ServicePackageSizeMapping
        fields = [
            'id', 'service_package', 'service_package_name', 'global_size', 
            'global_size_range', 'property_type_name', 'price','pricing_type'
        ]

    def get_global_size_range(self, obj):
        return f"{obj.global_size.min_sqft} - {obj.global_size.max_sqft} sqft"
    


class ServicePackageSizeMappingNewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePackageSizeMapping
        fields = ['id', 'service_package', 'global_size', 'pricing_type', 'price', 'created_at']

    def validate(self, data):
        # Enforce rule: bid_in_person must always have price 0
        if data.get('pricing_type') == 'bid_in_person':
            data['price'] = 0
        return data
    




class AddOnServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddOnService
        fields = ["id", "name", "description", "base_price", "created_at", "updated_at"]


class QuantityDiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuantityDiscount
        fields = [
            'id', 'question', 'option', 'scope',
            'discount_type', 'value', 'min_quantity', 'created_at'
        ]


class ServicePackagePriceSerializer(serializers.ModelSerializer):
    service_package_name = serializers.CharField(source='service_package.name', read_only=True)

    class Meta:
        model = ServicePackageSizeMapping
        fields = ['id', 'service_package', 'service_package_name', 'price', 'pricing_type']


class ServiceSizePackageSerializer(serializers.ModelSerializer):
    property_type_name = serializers.CharField(source='property_type.name', read_only=True)
    service_prices = serializers.SerializerMethodField()

    class Meta:
        model = GlobalSizePackage
        fields = [
            'id',
            'property_type',
            'property_type_name',
            'min_sqft',
            'max_sqft',
            'order',
            'service_prices'
        ]

    def get_service_prices(self, obj):
        service_id = self.context.get('service_id')
        mappings = ServicePackageSizeMapping.objects.filter(
            service_package__service_id=service_id,
            global_size=obj
        ).select_related('service_package')

        return ServicePackagePriceSerializer(mappings, many=True).data
    



from rest_framework import serializers
from .models import Coupon

class CouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = [
            "id",
            "code",
            "percentage_discount",
            "fixed_discount",
            "expiration_date",
            "used_count",
            "is_active",
            "is_global",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "used_count", "created_at", "updated_at"]






class CustomerSubmissionListSerializer(serializers.ModelSerializer):
    """Serializer for listing customer submissions"""
    customer_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    property_type_display = serializers.CharField(source='get_property_type_display', read_only=True)
    
    class Meta:
        model = CustomerSubmission
        fields = [
            'id', 'customer_name', 'first_name', 'last_name', 
            'customer_email', 'customer_phone', 'company_name',
            'status', 'status_display', 'property_type', 'property_type_display',
            'final_total', 'total_base_price', 'total_addons_price',
            'discounted_amount', 'is_coupon_applied',
            'created_at', 'updated_at', 'expires_at'
        ]
    
    def get_customer_name(self, obj):
        full_name = f"{obj.first_name or ''} {obj.last_name or ''}".strip()
        return full_name if full_name else 'N/A'