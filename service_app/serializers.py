# serializers.py
from rest_framework import serializers
from django.contrib.auth import authenticate
from decimal import Decimal
from .models import (
    User, Location, Service, Package, Feature, PackageFeature,
    Question, QuestionOption, QuestionPricing, OptionPricing,
    Order, OrderQuestionAnswer
)


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

    class Meta:
        model = Package
        fields = [
            'id', 'service', 'service_name', 'name', 'base_price', 
            'order', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


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
    class Meta:
        model = QuestionOption
        fields = ['id', 'option_text', 'order', 'is_active', 'created_at','question']
        read_only_fields = ['id', 'created_at']




class OptionPricingSerializer(serializers.ModelSerializer):
    """Serializer for OptionPricing model"""
    package_name = serializers.CharField(source='package.name', read_only=True)
    option_text = serializers.CharField(source='option.option_text', read_only=True)

    class Meta:
        model = OptionPricing
        fields = [
            'id', 'option', 'option_text', 'package', 'package_name',
            'pricing_type', 'value', 'created_at', 'updated_at'
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
            'yes_pricing_type', 'yes_value', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class QuestionSerializer(serializers.ModelSerializer):
    """Serializer for Question model"""
    service_name = serializers.CharField(source='service.name', read_only=True)
    options = QuestionOptionSerializer(many=True, read_only=True)
    pricing_rules = QuestionPricingSerializer(many=True, read_only=True)

    class Meta:
        model = Question
        fields = [
            'id', 'service', 'service_name', 'question_text', 'question_type',
            'order', 'is_active', 'created_at', 'updated_at', 'options', 'pricing_rules'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ServiceSerializer(serializers.ModelSerializer):
    """Serializer for Service model"""
    packages = PackageSerializer(many=True, read_only=True)
    features = FeatureSerializer(many=True, read_only=True)
    questions = QuestionSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Service
        fields = [
            'id', 'name', 'description', 'is_active', 'order',
            'created_at', 'updated_at', 'created_by', 'created_by_name',
            'packages', 'features', 'questions'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']

    def create(self, validated_data):
        # Set created_by from request user
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['created_by'] = request.user
        return super().create(validated_data)


class ServiceListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for Service list view"""
    packages_count = serializers.IntegerField(source='packages.count', read_only=True)
    features_count = serializers.IntegerField(source='features.count', read_only=True)
    questions_count = serializers.IntegerField(source='questions.count', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Service
        fields = [
            'id', 'name', 'description', 'is_active', 'order',
            'created_at', 'updated_at', 'created_by_name',
            'packages_count', 'features_count', 'questions_count'
        ]


# Nested serializers for complex operations
class QuestionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating questions with options and pricing"""
    options = QuestionOptionSerializer(many=True, required=False)
    
    class Meta:
        model = Question
        fields = [
            'service', 'question_text', 'question_type', 'order', 'is_active', 'options'
        ]

    def create(self, validated_data):
        options_data = validated_data.pop('options', [])
        question = Question.objects.create(**validated_data)
        
        # Create options if provided
        for option_data in options_data:
            QuestionOption.objects.create(question=question, **option_data)
            
        return question


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
            if 'package_id' not in rule:
                raise serializers.ValidationError("Each pricing rule must have a package_id")
            if 'pricing_type' not in rule:
                raise serializers.ValidationError("Each pricing rule must have a pricing_type")
            if 'value' not in rule:
                raise serializers.ValidationError("Each pricing rule must have a value")
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