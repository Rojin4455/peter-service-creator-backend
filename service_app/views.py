# views.py
from rest_framework import generics, status, permissions,viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework.views import APIView
from django.contrib.auth import authenticate
from django.db.models import Count, Avg, Prefetch
from django.db import transaction
from django.shortcuts import get_object_or_404
from decimal import Decimal
import requests
from rest_framework.decorators import action
import os
from django.db import models
from .models import Service, ServiceSettings
from .serializers import ServiceSettingsSerializer

from rest_framework.permissions import IsAuthenticated

from .models import (
    User, Location, Service, Package, Feature, PackageFeature,
    Question, QuestionOption, QuestionPricing, OptionPricing,
    Order, OrderQuestionAnswer,SubQuestionPricing,SubQuestion,QuestionResponse,AddOnService,QuantityDiscount,
    GlobalSizePackage, ServicePackageSizeMapping,PropertyType, Coupon
)
from .serializers import (
    UserSerializer, LoginSerializer, LocationSerializer, ServiceSerializer,
    ServiceListSerializer, PackageSerializer, FeatureSerializer,
    PackageFeatureSerializer, QuestionSerializer, QuestionCreateSerializer,
    QuestionOptionSerializer, QuestionPricingSerializer, OptionPricingSerializer,
    PackageWithFeaturesSerializer, BulkPricingUpdateSerializer,
    ServiceAnalyticsSerializer, SubQuestionPricingSerializer,BulkSubQuestionPricingSerializer,QuestionResponseSerializer,
    PricingCalculationSerializer, SubQuestionSerializer,AddOnServiceSerializer,QuantityDiscountSerializer,ServicePackageSizeMappingNewSerializer,
    GlobalSizePackageSerializer,ServicePackageSizeMappingSerializer,PropertyTypeSerializer, CouponSerializer,
    AdminUserListSerializer, AdminUserCreateSerializer, AdminUserUpdateSerializer
)



from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAdminUser, AllowAny



from rest_framework.generics import ListAPIView



class IsAdminPermission(permissions.BasePermission):
    """Custom permission to only allow admins to access views"""
    
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_admin


class IsSuperAdminPermission(permissions.BasePermission):
    """Custom permission to only allow super admins to access views"""
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.is_super_admin
        )


class IsAdminOrSuperAdminPermission(permissions.BasePermission):
    """Custom permission to allow both admins and super admins to access views"""
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            (request.user.is_admin or request.user.is_super_admin)
        )
    


class AdminTokenObtainPairView(TokenObtainPairView):
    permission_classes = [AllowAny]
    
    def post(self, request, *args, **kwargs):
        """Override post method to include user data in response"""
        serializer = self.get_serializer(data=request.data)
        
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            # Handle validation errors
            error_detail = str(e)
            if hasattr(e, 'detail'):
                error_detail = e.detail
            return Response({
                'error': 'Invalid credentials',
                'detail': error_detail
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get the user from serializer (available after validation)
        user = serializer.user
        
        # Check if user is an admin
        if not user.is_admin:
            return Response({
                'error': 'Only admins can access this interface.'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Check if user is active
        if not user.is_active:
            return Response({
                'error': 'User account is disabled.'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get tokens from serializer validated data
        tokens = serializer.validated_data
        
        # Serialize user data with all permission fields
        user_data = UserSerializer(user).data
        
        # Return tokens and user data
        return Response({
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'user': user_data,
            'message': 'Login successful'
        }, status=status.HTTP_200_OK)

class AdminTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]

class AdminLogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()  # Requires Blacklist app enabled
            return Response({"detail": "Successfully logged out."})
        except Exception as e:
            return Response({"detail": "Invalid token or already logged out."}, status=400)



# Authentication Views
class AdminLoginView(APIView):
    """Admin login view"""
    permission_classes = []

    def post(self, request):
        print("request: ", request.data)
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            token, created = Token.objects.get_or_create(user=user)
            return Response({
                'token': token.key,
                'user': UserSerializer(user).data,
                'message': 'Login successful'
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# class AdminLogoutView(APIView):
#     """Admin logout view"""
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         try:
#             request.user.auth_token.delete()
#             return Response({'message': 'Logout successful'})
#         except:
#             return Response({'message': 'Logout successful'})


# Location Views
class LocationListCreateView(generics.ListCreateAPIView):
    """List all locations and create new ones"""
    queryset = Location.objects.filter(is_active=True)
    serializer_class = LocationSerializer
    permission_classes = [IsAdminPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                models.Q(name__icontains=search) | 
                models.Q(address__icontains=search)
            )
        return queryset.order_by('name')


class LocationDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a location"""
    queryset = Location.objects.all()
    serializer_class = LocationSerializer
    permission_classes = [IsAdminPermission]

    def perform_destroy(self, instance):
        # Soft delete
        instance.is_active = False
        instance.save()





# Service Views
class ServiceListCreateView(generics.ListCreateAPIView):
    """List all services and create new ones"""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Service.objects.all().prefetch_related(
            'questions__options',
            'questions__sub_questions',
            'questions__child_questions'
        )
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset.order_by('order', 'name')

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return ServiceListSerializer
        return ServiceSerializer

class ServiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a service"""
    queryset = Service.objects.prefetch_related(
        'questions__options__pricing_rules',
        'questions__sub_questions__pricing_rules',
        'questions__pricing_rules',
        'questions__child_questions'
    )
    serializer_class = ServiceSerializer
    permission_classes = [IsAdminPermission]

    def perform_destroy(self, instance):
        # Soft delete
        instance.delete()




# Package Views
class PackageListCreateView(generics.ListCreateAPIView):
    """List all packages and create new ones"""
    queryset = Package.objects.filter(is_active=True).select_related('service')
    serializer_class = PackageSerializer
    permission_classes = [IsAdminPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        service_id = self.request.query_params.get('service', None)
        if service_id:
            queryset = queryset.filter(service_id=service_id)
        return queryset.order_by('service__name', 'order', 'name')


class PackageDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a package"""
    queryset = Package.objects.all()
    serializer_class = PackageSerializer
    permission_classes = [IsAdminPermission]

    # def perform_destroy(self, instance):
    #     # Soft delete
    #     # instance.is_active = True
    #     instance.delete()


class PackageWithFeaturesView(generics.RetrieveAPIView):
    """Get package with its features"""
    queryset = Package.objects.prefetch_related('package_features__feature')
    serializer_class = PackageWithFeaturesSerializer
    permission_classes = [IsAdminPermission]


# Feature Views
class FeatureListCreateView(generics.ListCreateAPIView):
    """List all features and create new ones"""
    queryset = Feature.objects.filter(is_active=True).select_related('service')
    serializer_class = FeatureSerializer
    permission_classes = [IsAdminPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        service_id = self.request.query_params.get('service', None)
        if service_id:
            queryset = queryset.filter(service_id=service_id)
        return queryset.order_by('service__name', 'name')


class FeatureDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a feature"""
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
    permission_classes = [IsAdminPermission]

    # def perform_destroy(self, instance):
    #     # Soft delete
    #     instance.is_active = False
    #     instance.save()


# Package-Feature Views
class PackageFeatureListCreateView(generics.ListCreateAPIView):
    """List and create package-feature relationships"""
    queryset = PackageFeature.objects.select_related('package', 'feature')
    serializer_class = PackageFeatureSerializer
    permission_classes = [IsAdminPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        package_id = self.request.query_params.get('package', None)
        if package_id:
            queryset = queryset.filter(package_id=package_id)
        return queryset


class PackageFeatureDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a package-feature relationship"""
    queryset = PackageFeature.objects.all()
    serializer_class = PackageFeatureSerializer
    permission_classes = [IsAdminPermission]


from rest_framework.parsers import MultiPartParser, FormParser


# Question Views
class QuestionListCreateView(generics.ListCreateAPIView):
    """List all questions and create new ones"""
    permission_classes = [IsAdminPermission]
    # parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):

        print("hererewerewrwerew")
        queryset = Question.objects.all().select_related(
            'service', 'parent_question', 'condition_option'
        ).prefetch_related(
            'options__pricing_rules',
            'sub_questions__pricing_rules',
            'pricing_rules__package',
            'child_questions'
        )
        
        # Filter parameters
        service_id = self.request.query_params.get('service', None)
        question_type = self.request.query_params.get('type', None)
        parent_only = self.request.query_params.get('parent_only', 'false').lower() == 'true'

        
        
        if service_id:
            queryset = queryset.filter(service_id=service_id)
        if question_type:
            queryset = queryset.filter(question_type=question_type)
        if parent_only:
            queryset = queryset.filter(parent_question__isnull=True)
            
        return queryset.order_by('service__name', 'order', 'created_at')

    def get_serializer_class(self):
        if self.request.method == 'POST':


            print("post request", self.request.data)
            print("post request", self.request.FILES)
            return QuestionCreateSerializer
        return QuestionSerializer

class QuestionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a question"""
    queryset = Question.objects.prefetch_related(
        'options__pricing_rules',
        'sub_questions__pricing_rules',
        'pricing_rules',
        'child_questions'
    )
    permission_classes = [IsAdminPermission]

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return QuestionCreateSerializer
        return QuestionSerializer

    def perform_destroy(self, instance):
        # Soft delete
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

# Question Option Views
class QuestionOptionListCreateView(generics.ListCreateAPIView):
    """List and create question options"""
    queryset = QuestionOption.objects.filter(is_active=True)
    serializer_class = QuestionOptionSerializer
    permission_classes = [IsAdminPermission]

    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related('pricing_rules')
        question_id = self.request.query_params.get('question', None)
        if question_id:
            queryset = queryset.filter(question_id=question_id)
        return queryset.order_by('order', 'option_text')


class QuestionOptionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a question option"""
    queryset = QuestionOption.objects.prefetch_related('pricing_rules')
    serializer_class = QuestionOptionSerializer
    permission_classes = [IsAdminPermission]

    # def perform_destroy(self, instance):
    #     # Soft delete
    #     instance.is_active = False
    #     instance.save()

# Pricing Views
class QuestionPricingListCreateView(generics.ListCreateAPIView):
    """List and create question pricing rules"""
    queryset = QuestionPricing.objects.select_related('question', 'package')
    serializer_class = QuestionPricingSerializer
    permission_classes = [IsAdminPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        question_id = self.request.query_params.get('question', None)
        package_id = self.request.query_params.get('package', None)
        
        if question_id:
            queryset = queryset.filter(question_id=question_id)
        if package_id:
            queryset = queryset.filter(package_id=package_id)
            
        return queryset


class QuestionPricingDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a question pricing rule"""
    queryset = QuestionPricing.objects.all()
    serializer_class = QuestionPricingSerializer
    permission_classes = [IsAdminPermission]



class SubQuestionPricingListCreateView(generics.ListCreateAPIView):
    """List and create sub-question pricing rules"""
    queryset = SubQuestionPricing.objects.select_related('sub_question', 'package')
    serializer_class = SubQuestionPricingSerializer
    permission_classes = [IsAdminPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        sub_question_id = self.request.query_params.get('sub_question', None)
        package_id = self.request.query_params.get('package', None)
        
        if sub_question_id:
            queryset = queryset.filter(sub_question_id=sub_question_id)
        if package_id:
            queryset = queryset.filter(package_id=package_id)
            
        return queryset


class SubQuestionPricingDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a sub-question pricing rule"""
    queryset = SubQuestionPricing.objects.all()
    serializer_class = SubQuestionPricingSerializer
    permission_classes = [IsAdminPermission]


class SubQuestionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a sub-question"""
    queryset = SubQuestion.objects.prefetch_related('pricing_rules')
    serializer_class = SubQuestionSerializer
    permission_classes = [IsAdminPermission]

    def perform_destroy(self, instance):
        # Soft delete
        instance.is_active = False
        instance.save()


class OptionPricingListCreateView(generics.ListCreateAPIView):
    """List and create option pricing rules"""
    queryset = OptionPricing.objects.select_related('option', 'package')
    serializer_class = OptionPricingSerializer
    permission_classes = [IsAdminPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        option_id = self.request.query_params.get('option', None)
        package_id = self.request.query_params.get('package', None)
        
        if option_id:
            queryset = queryset.filter(option_id=option_id)
        if package_id:
            queryset = queryset.filter(package_id=package_id)
            
        return queryset



class OptionPricingDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete an option pricing rule"""
    queryset = OptionPricing.objects.all()
    serializer_class = OptionPricingSerializer
    permission_classes = [IsAdminPermission]



class SubQuestionListCreateView(generics.ListCreateAPIView):
    """List and create sub-questions"""
    queryset = SubQuestion.objects.filter(is_active=True)
    serializer_class = SubQuestionSerializer
    permission_classes = [IsAdminPermission]

    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related('pricing_rules')
        parent_question_id = self.request.query_params.get('parent_question', None)
        if parent_question_id:
            queryset = queryset.filter(parent_question_id=parent_question_id)
        return queryset.order_by('order', 'sub_question_text')


# Bulk Operations Views
class BulkQuestionPricingView(APIView):
    """Bulk update question pricing rules for all packages"""
    permission_classes = [IsAdminPermission]

    def post(self, request):
        serializer = BulkPricingUpdateSerializer(data=request.data)
        if serializer.is_valid():
            question_id = serializer.validated_data['question_id']
            pricing_rules = serializer.validated_data['pricing_rules']

            try:
                with transaction.atomic():
                    question = get_object_or_404(Question, id=question_id)
                    
                    # Update or create pricing rules
                    for rule in pricing_rules:
                        package_id = rule['package_id']
                        pricing_type = rule['pricing_type']
                        value_type = rule['value_type']
                        value = Decimal(str(rule['value']))
                        
                        pricing, created = QuestionPricing.objects.get_or_create(
                            question=question,
                            package_id=package_id,
                            defaults={
                                'yes_pricing_type': pricing_type,
                                'yes_value': value,
                                'value_type': value_type
                            }
                        )
                        
                        if not created:
                            pricing.yes_pricing_type = pricing_type
                            pricing.yes_value = value
                            pricing.value_type = value_type  # ✅ added
                            pricing.save()

                return Response({'message': 'Question pricing rules updated successfully'})
                
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class BulkSubQuestionPricingView(APIView):
    """Bulk update sub-question pricing rules for all packages"""
    permission_classes = [IsAdminPermission]

    def post(self, request):
        serializer = BulkSubQuestionPricingSerializer(data=request.data)
        if serializer.is_valid():
            sub_question_id = serializer.validated_data['sub_question_id']
            pricing_rules = serializer.validated_data['pricing_rules']

            try:
                with transaction.atomic():
                    sub_question = get_object_or_404(SubQuestion, id=sub_question_id)
                    
                    for rule in pricing_rules:
                        package_id = rule['package_id']
                        pricing_type = rule['pricing_type']
                        value = Decimal(str(rule['value']))
                        value_type = rule['value_type']
                        
                        pricing, created = SubQuestionPricing.objects.get_or_create(
                            sub_question=sub_question,
                            package_id=package_id,
                            defaults={
                                'yes_pricing_type': pricing_type,
                                'yes_value': value,
                                'value_type': value_type
                            }
                        )
                        
                        if not created:
                            pricing.yes_pricing_type = pricing_type
                            pricing.yes_value = value
                            pricing.value_type = value_type   # ✅ added update for value_type
                            pricing.save()

                return Response({'message': 'Sub-question pricing rules updated successfully'})
                
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BulkOptionPricingView(APIView):
    """Bulk update option pricing rules for all packages"""
    permission_classes = [IsAdminPermission]

    def post(self, request):
        option_id = request.data.get('option_id')
        pricing_rules = request.data.get('pricing_rules', [])

        if not option_id or not pricing_rules:
            return Response(
                {'error': 'option_id and pricing_rules are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                option = get_object_or_404(QuestionOption, id=option_id)
                
                for rule in pricing_rules:
                    package_id = rule['package_id']
                    pricing_type = rule['pricing_type']
                    value = Decimal(str(rule['value']))
                    value_type = rule['value_type']
                    
                    pricing, created = OptionPricing.objects.get_or_create(
                        option=option,
                        package_id=package_id,
                        defaults={
                            'pricing_type': pricing_type,
                            'value': value,
                            'value_type': value_type
                        }
                    )
                    
                    if not created:
                        pricing.pricing_type = pricing_type
                        pricing.value = value
                        pricing.value_type = value_type  # ✅ added
                        pricing.save()

            return Response({'message': 'Option pricing rules updated successfully'})
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class QuestionTreeView(APIView):
    """Get the complete question tree for a service"""
    permission_classes = [IsAuthenticated]

    def get(self, request, service_id):
        try:
            service = get_object_or_404(Service, id=service_id, is_active=True)
            
            # Get root questions (no parent)
            root_questions = Question.objects.filter(
                service=service,
                is_active=True,
                parent_question__isnull=True
            ).prefetch_related(
                'options__pricing_rules',
                'sub_questions__pricing_rules',
                'pricing_rules',
                'child_questions__options',
                'child_questions__sub_questions',
                'child_questions__pricing_rules'
            ).order_by('order')
            
            serializer = QuestionSerializer(root_questions, many=True, context={'request': request})
            
            return Response({
                'service': {
                    'id': service.id,
                    'name': service.name,
                    'description': service.description
                },
                'questions': serializer.data
            })
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ConditionalQuestionsView(APIView):
    """Get conditional questions based on parent question and answer"""
    permission_classes = [IsAuthenticated]

    def get(self, request, parent_question_id):
        answer = request.query_params.get('answer')
        option_id = request.query_params.get('option_id')
        
        if not answer and not option_id:
            return Response({'error': 'Either answer or option_id is required'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        try:
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
                'options__pricing_rules',
                'sub_questions__pricing_rules',
                'pricing_rules'
            ).order_by('order')
            
            serializer = QuestionSerializer(conditional_questions, many=True, context={'request': request})
            
            return Response({
                'parent_question_id': parent_question_id,
                'condition': {
                    'answer': answer,
                    'option_id': option_id
                },
                'conditional_questions': serializer.data
            })
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        

class QuestionResponseListCreateView(generics.ListCreateAPIView):
    """List and create question responses"""
    queryset = QuestionResponse.objects.prefetch_related(
        'option_responses__option',
        'sub_question_responses__sub_question'
    )
    serializer_class = QuestionResponseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        question_id = self.request.query_params.get('question', None)
        if question_id:
            queryset = queryset.filter(question_id=question_id)
        return queryset.order_by('-created_at')




# Analytics Views
class ServiceAnalyticsView(APIView):
    """Get analytics data for services"""
    permission_classes = [IsAdminPermission]

    def get(self, request):
        services = Service.objects.filter(is_active=True).annotate(
            total_packages=Count('packages', filter=models.Q(packages__is_active=True)),
            total_features=Count('features', filter=models.Q(features__is_active=True)),
            total_questions=Count('questions', filter=models.Q(questions__is_active=True)),
            average_package_price=Avg('packages__base_price', filter=models.Q(packages__is_active=True))
        ).order_by('order', 'name')

        analytics_data = []
        for service in services:
            analytics_data.append({
                'service_id': service.id,
                'service_name': service.name,
                'total_packages': service.total_packages or 0,
                'total_features': service.total_features or 0,
                'total_questions': service.total_questions or 0,
                'average_package_price': service.average_package_price or Decimal('0.00'),
                'created_at': service.created_at
            })

        serializer = ServiceAnalyticsSerializer(analytics_data, many=True)
        return Response(serializer.data)


# Utility Views
class PricingCalculatorView(APIView):
    """Calculate pricing based on question responses"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PricingCalculationSerializer(data=request.data)
        if serializer.is_valid():
            service_id = serializer.validated_data['service_id']
            package_id = serializer.validated_data['package_id']
            responses = serializer.validated_data['responses']

            try:
                service = get_object_or_404(Service, id=service_id)
                # package = get_object_or_404(Package, id=package_id)
                
                total_adjustment = Decimal('0.00')
                breakdown = []

                for response in responses:
                    question_id = response['question_id']
                    question = get_object_or_404(Question, id=question_id)
                    
                    question_adjustment = Decimal('0.00')
                    question_breakdown = {
                        'question_id': question_id,
                        'question_text': question.question_text,
                        'question_type': question.question_type,
                        'adjustments': []
                    }

                    if question.question_type == 'yes_no':
                        if response.get('yes_no_answer') is True:
                            pricing = QuestionPricing.objects.filter(
                                question=question, package_id=package_id
                            ).first()
                            if pricing and pricing.yes_pricing_type != 'ignore':
                                question_adjustment += pricing.yes_value
                                question_breakdown['adjustments'].append({
                                    'type': 'yes_answer',
                                    'pricing_type': pricing.yes_pricing_type,
                                    'value': pricing.yes_value
                                })

                    elif question.question_type in ['describe', 'quantity']:
                        selected_options = response.get('selected_options', [])
                        for option_data in selected_options:
                            option_id = option_data['option_id']
                            quantity = option_data.get('quantity', 1)
                            
                            pricing = OptionPricing.objects.filter(
                                option_id=option_id, package_id=package_id
                            ).first()
                            
                            if pricing and pricing.pricing_type != 'ignore':
                                if pricing.pricing_type == 'per_quantity':
                                    adjustment = pricing.value * quantity
                                else:
                                    adjustment = pricing.value
                                    
                                question_adjustment += adjustment
                                question_breakdown['adjustments'].append({
                                    'type': 'option_selection',
                                    'option_id': option_id,
                                    'quantity': quantity,
                                    'pricing_type': pricing.pricing_type,
                                    'value': adjustment
                                })

                    elif question.question_type == 'multiple_yes_no':
                        sub_question_answers = response.get('sub_question_answers', [])
                        for sub_answer in sub_question_answers:
                            if sub_answer.get('answer') is True:
                                sub_question_id = sub_answer['sub_question_id']
                                pricing = SubQuestionPricing.objects.filter(
                                    sub_question_id=sub_question_id, package_id=package_id
                                ).first()
                                
                                if pricing and pricing.yes_pricing_type != 'ignore':
                                    question_adjustment += pricing.yes_value
                                    question_breakdown['adjustments'].append({
                                        'type': 'sub_question_yes',
                                        'sub_question_id': sub_question_id,
                                        'pricing_type': pricing.yes_pricing_type,
                                        'value': pricing.yes_value
                                    })

                    elif question.question_type == 'measurement':
                        measurements = response.get('measurements', [])
                        pricing = QuestionPricing.objects.filter(
                            question=question, package_id=package_id
                        ).first()
                        
                        if pricing and pricing.yes_pricing_type == 'upcharge_percent' and pricing.value_type == 'amount':
                            measurement_breakdown = []
                            for measurement_data in measurements:
                                option_id = measurement_data.get('option_id')
                                length = Decimal(str(measurement_data.get('length', 0)))
                                width = Decimal(str(measurement_data.get('width', 0)))
                                quantity = measurement_data.get('quantity', 1)
                                
                                if length > 0 and width > 0:
                                    area = length * width
                                    row_total = area * Decimal(str(quantity)) * pricing.yes_value
                                    question_adjustment += row_total
                                    
                                    # Get option text for breakdown
                                    option_text = "Unknown"
                                    if option_id:
                                        try:
                                            option = QuestionOption.objects.get(id=option_id)
                                            option_text = option.option_text
                                        except QuestionOption.DoesNotExist:
                                            pass
                                    
                                    measurement_breakdown.append({
                                        'option_id': option_id,
                                        'option_text': option_text,
                                        'length': float(length),
                                        'width': float(width),
                                        'quantity': quantity,
                                        'area': float(area),
                                        'row_total': float(row_total)
                                    })
                            
                            question_breakdown['adjustments'] = measurement_breakdown

                    total_adjustment += question_adjustment
                    question_breakdown['total_adjustment'] = question_adjustment
                    breakdown.append(question_breakdown)

                return Response({
                    'service_id': service_id,
                    'package_id': package_id,
                    'total_adjustment': total_adjustment,
                    'breakdown': breakdown
                })
                
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        


class ServiceSettingsView(APIView):
    def get(self, request, service_id):
        service = get_object_or_404(Service, id=service_id)
        try:
            settings = service.settings
            serializer = ServiceSettingsSerializer(settings)
            return Response(serializer.data)
        except ServiceSettings.DoesNotExist:
            return Response({"detail": "Settings not found."}, status=status.HTTP_404_NOT_FOUND)
    def post(self, request, service_id):
        service = get_object_or_404(Service, id=service_id)

        serializer = ServiceSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        settings, created = ServiceSettings.objects.update_or_create(
            service=service,
            defaults=serializer.validated_data
        )

        return Response(
            ServiceSettingsSerializer(settings).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    def put(self, request, service_id):
        service = get_object_or_404(Service, id=service_id)
        settings = get_object_or_404(ServiceSettings, service=service)

        serializer = ServiceSettingsSerializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    



from .serializers import GlobalSizePackageSerializer, ServicePackageSizeMappingSerializer
from .models import GlobalSizePackage, ServicePackageSizeMapping

class GlobalSizePackageListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/global-sizes/ → List all global size packages with templates
    POST /api/global-sizes/ → Create a global size package with template prices
    """
    serializer_class = GlobalSizePackageSerializer
    queryset = GlobalSizePackage.objects.all().prefetch_related('template_prices')

class AutoMapGlobalToServicePackages(APIView):
    """
    POST /api/services/{service_id}/auto-map-packages/
    Automatically map global pricing templates to service-level packages
    by order.
    """
    def post(self, request, service_id):
        try:
            service = Service.objects.prefetch_related('packages').get(id=service_id)
        except Service.DoesNotExist:
            return Response({'detail': 'Service not found'}, status=404)

        global_sizes = GlobalSizePackage.objects.prefetch_related('template_prices').order_by('order')
        service_packages = list(service.packages.filter(is_active=True).order_by('order'))

        if not service_packages:
            return Response({'detail': 'No service-level packages found.'}, status=400)

        created_mappings = []
        for global_size in global_sizes:
            templates = list(global_size.template_prices.order_by('order'))
            for idx, template in enumerate(templates):
                if idx < len(service_packages):
                    service_package = service_packages[idx]
                    mapping, created = ServicePackageSizeMapping.objects.get_or_create(
                        service_package=service_package,
                        global_size=global_size,
                        defaults={'price': template.price}
                    )
                    if created:
                        created_mappings.append(mapping)

        return Response(ServicePackageSizeMappingSerializer(created_mappings, many=True).data, status=201)
    

from rest_framework.generics import ListAPIView
from collections import defaultdict


class ServiceMappedSizesAPIView(ListAPIView):
    """
    GET /api/services/{service_id}/mapped-sizes/

    Retrieve all size mappings with prices for a given service,
    grouped by property type.
    """
    serializer_class = ServicePackageSizeMappingSerializer
    pagination_class = None  # disable pagination for grouped response

    def get_queryset(self):
        service_id = self.kwargs['service_id']
        return (
            ServicePackageSizeMapping.objects.filter(
                service_package__service_id=service_id
            )
            .select_related('global_size__property_type', 'service_package')
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        grouped = defaultdict(list)
        for item in serializer.data:
            property_type = item["property_type_name"]
            grouped[property_type].append(item)

        return Response(grouped)


class GlobalSizePackageDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = GlobalSizePackageSerializer
    queryset = GlobalSizePackage.objects.all().prefetch_related('template_prices')
    lookup_field = 'id'








class PropertyTypeListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/property-types/ → List all property types
    POST /api/property-types/ → Create a new property type
    """
    queryset = PropertyType.objects.filter(is_active=True)
    serializer_class = PropertyTypeSerializer


class PropertyTypeDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/property-types/{id}/ → Get property type details
    PUT    /api/property-types/{id}/ → Update property type
    DELETE /api/property-types/{id}/ → Delete property type
    """
    queryset = PropertyType.objects.all()
    serializer_class = PropertyTypeSerializer


class GlobalSizePackageListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/global-sizes/ → List all global size packages with templates (grouped by property type)
    POST /api/global-sizes/ → Create a global size package with template prices
    """
    serializer_class = GlobalSizePackageSerializer
    
    def get_queryset(self):
        queryset = GlobalSizePackage.objects.all().prefetch_related(
            'template_prices', 'property_type'
        )
        
        # Filter by property type if provided
        property_type_id = self.request.query_params.get('property_type')
        if property_type_id:
            queryset = queryset.filter(property_type_id=property_type_id)
            
        return queryset


class GlobalSizePackageDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/global-sizes/{id}/ → Get global size package details
    PUT    /api/global-sizes/{id}/ → Update global size package
    DELETE /api/global-sizes/{id}/ → Delete global size package
    """
    queryset = GlobalSizePackage.objects.all().prefetch_related('template_prices')
    serializer_class = GlobalSizePackageSerializer


class AutoMapGlobalToServicePackages(APIView):
    """
    POST /api/services/{service_id}/auto-map-packages/
    Automatically map global pricing templates to service-level packages by order.
    Optionally filter by property type.
    """
    def post(self, request, service_id):
        try:
            service = Service.objects.prefetch_related('packages').get(id=service_id)
        except Service.DoesNotExist:
            return Response({'detail': 'Service not found'}, status=404)

        property_type_id = request.data.get('property_type_id')
        
        # Filter global sizes by property type if provided
        global_sizes_query = GlobalSizePackage.objects.prefetch_related('template_prices').order_by(
            'property_type__order', 'order'
        )
        if property_type_id:
            global_sizes_query = global_sizes_query.filter(property_type_id=property_type_id)
        
        global_sizes = global_sizes_query
        service_packages = list(service.packages.filter(is_active=True).order_by('order'))

        if not service_packages:
            return Response({'detail': 'No service-level packages found.'}, status=400)

        created_mappings = []
        for global_size in global_sizes:
            templates = list(global_size.template_prices.order_by('order'))
            for idx, template in enumerate(templates):
                if idx < len(service_packages):
                    service_package = service_packages[idx]
                    mapping, created = ServicePackageSizeMapping.objects.get_or_create(
                        service_package=service_package,
                        global_size=global_size,
                        defaults={'price': template.price}
                    )
                    if created:
                        created_mappings.append(mapping)

        return Response(ServicePackageSizeMappingSerializer(created_mappings, many=True).data, status=201)


class ServiceMappedSizesAPIView(ListAPIView):
    """
    GET /api/services/{service_id}/mapped-sizes/ → Retrieve all size mappings for a service
    Query params: property_type - filter by property type
    """
    serializer_class = ServicePackageSizeMappingSerializer

    def get_queryset(self):
        service_id = self.kwargs['service_id']
        queryset = ServicePackageSizeMapping.objects.filter(
            service_package__service_id=service_id
        ).select_related('global_size__property_type', 'service_package')
        
        # Filter by property type if provided
        property_type_id = self.request.query_params.get('property_type')
        if property_type_id:
            queryset = queryset.filter(global_size__property_type_id=property_type_id)
            
        return queryset


class GlobalSizesByPropertyTypeView(APIView):
    """
    GET /api/global-sizes-by-property-type/ → Get sizes grouped by property type
    """
    def get(self, request):
        property_types = PropertyType.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                'size_packages',
                queryset=GlobalSizePackage.objects.prefetch_related('template_prices').order_by('order')
            )
        )
        
        result = []
        for prop_type in property_types:
            sizes_data = GlobalSizePackageSerializer(prop_type.size_packages.all(), many=True).data
            result.append({
                'property_type': PropertyTypeSerializer(prop_type).data,
                'size_packages': sizes_data
            })
        
        return Response(result)
    


@api_view(["GET", "POST"])
def addon_list_create(request):
    """
    GET: List all AddOns
    POST: Create a new AddOn
    """
    if request.method == "GET":
        addons = AddOnService.objects.all().order_by("-created_at")
        serializer = AddOnServiceSerializer(addons, many=True)
        return Response(serializer.data)

    elif request.method == "POST":
        serializer = AddOnServiceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
def addon_detail(request, pk):
    """
    GET: Retrieve AddOn
    PUT/PATCH: Update AddOn
    DELETE: Delete AddOn
    """
    addon = get_object_or_404(AddOnService, pk=pk)

    if request.method == "GET":
        serializer = AddOnServiceSerializer(addon)
        return Response(serializer.data)

    elif request.method in ["PUT", "PATCH"]:
        serializer = AddOnServiceSerializer(addon, data=request.data, partial=(request.method == "PATCH"))
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == "DELETE":
        addon.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
        

class QuantityDiscountViewSet(viewsets.ModelViewSet):
    """Admin CRUD for quantity-based discounts"""
    queryset = QuantityDiscount.objects.all()
    serializer_class = QuantityDiscountSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        queryset = super().get_queryset()
        question_id = self.request.query_params.get('question')
        option_id = self.request.query_params.get('option')
        if question_id:
            queryset = queryset.filter(question_id=question_id)
        if option_id:
            queryset = queryset.filter(option_id=option_id)
        return queryset
    


class ServicePackageSizeMappingUpdateView(generics.UpdateAPIView):
    queryset = ServicePackageSizeMapping.objects.all()
    serializer_class = ServicePackageSizeMappingNewSerializer
    lookup_field = "id"  # Assuming UUID or PK field


class ServicePackageSizeMappingBulkUpdateView(APIView):
    """
    PUT /api/service-package-size-mappings/bulk-update/

    Payload: [
        {"id": 1, "pricing_type": "upcharge", "price": "300.00"},
        {"id": 2, "pricing_type": "bid_in_person"}
    ]
    """
    def put(self, request, *args, **kwargs):
        data = request.data
        if not isinstance(data, list):
            return Response(
                {"detail": "Expected a list of objects for bulk update."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated_objects = []

        with transaction.atomic():
            for item in data:
                try:
                    instance = ServicePackageSizeMapping.objects.get(id=item.get("id"))
                except ServicePackageSizeMapping.DoesNotExist:
                    return Response(
                        {"detail": f"Object with id {item.get('id')} not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                serializer = ServicePackageSizeMappingNewSerializer(
                    instance, data=item, partial=True
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()
                updated_objects.append(serializer.data)

        return Response(updated_objects, status=status.HTTP_200_OK)


class ServicePackageSizeMappingByServiceView(generics.ListAPIView):
    serializer_class = ServicePackageSizeMappingNewSerializer

    def get_queryset(self):
        service_id = self.kwargs.get("service_id")
        return ServicePackageSizeMapping.objects.filter(service_package__service_id=service_id)


from service_app.serializers import ServiceSizePackageSerializer

class ServiceMappedSizesStructuredAPIView(generics.ListAPIView):
    """
    GET /api/service/services/{service_id}/mapped-sizes/

    Returns all global sizes with service-specific pricing per package.
    """
    serializer_class = ServiceSizePackageSerializer

    def get_queryset(self):
        service_id = self.kwargs['service_id']
        return GlobalSizePackage.objects.filter(
            servicepackagesizemapping__service_package__service_id=service_id
        ).distinct().select_related('property_type')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['service_id'] = self.kwargs['service_id']
        return context
    





from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from .models import Coupon
from .serializers import CouponSerializer
from decimal import Decimal

class CouponViewSet(viewsets.ModelViewSet):
    queryset = Coupon.objects.all().order_by("-created_at")
    serializer_class = CouponSerializer
    permission_classes = [permissions.IsAdminUser]

    def create(self, request, *args, **kwargs):
        """Create a new coupon"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """Update an existing coupon"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """Delete a coupon"""
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GlobalCouponListView(APIView):
    """View to fetch all global coupons - accessible by anyone"""
    permission_classes = [AllowAny]

    def get(self, request):
        """Get all active global coupons"""
        global_coupons = Coupon.objects.filter(
            is_global=True,
            is_active=True
        ).order_by("-created_at")
        
        serializer = CouponSerializer(global_coupons, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)



from rest_framework.pagination import PageNumberPagination
from django.db.models import Count, Sum, Q, F
from django.db.models.functions import TruncMonth, TruncDate
from decimal import Decimal
from datetime import datetime, timedelta
from .serializers import CustomerSubmissionListSerializer
from quote_app.models import CustomerSubmission

class SubmissionPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class DashboardAPIView(APIView):
    """
    Comprehensive dashboard endpoint that returns:
    - Overall statistics
    - Heard about us breakdown (pie chart data)
    - Monthly sales/order trends (bar chart data)
    - Status distribution
    - Paginated submissions list
    """

    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Get query parameters for filtering
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        # Base queryset
        queryset = CustomerSubmission.objects.filter(is_on_the_go=False)
        
        # Apply date filters if provided
        if start_date:
            try:
                start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                queryset = queryset.filter(created_at__gte=start_date_obj)
            except ValueError:
                pass
        
        if end_date:
            try:
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                queryset = queryset.filter(created_at__lte=end_date_obj)
            except ValueError:
                pass
        
        # 1. OVERALL STATISTICS
        total_submissions = queryset.count()
        
        # Total worth (sum of final_total for approved status)
        total_worth = queryset.filter(
            status='approved'
        ).aggregate(
            total=Sum('final_total')
        )['total'] or Decimal('0.00')
        
        # Average order value
        avg_order_value = queryset.filter(
            status='approved'
        ).aggregate(
            avg=Sum('final_total')
        )['avg'] or Decimal('0.00')
        
        if queryset.filter(status='approved').count() > 0:
            avg_order_value = avg_order_value / queryset.filter(status='approved').count()
        
        # Status counts
        status_counts = queryset.values('status').annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Conversion rate (approved / total)
        approved_count = queryset.filter(status='approved').count()
        conversion_rate = (approved_count / total_submissions * 100) if total_submissions > 0 else 0
        
        # 2. HEARD ABOUT US BREAKDOWN (Pie Chart Data)
        heard_about_data = queryset.exclude(
            Q(heard_about_us__isnull=True) | Q(heard_about_us='')
        ).values('heard_about_us').annotate(
            total_count=Count('id'),
            approved_count=Count('id', filter=Q(status='approved')),
            draft_count=Count('id', filter=Q(status='draft')),
            submitted_count=Count('id', filter=Q(status='submitted')),
            packages_selected_count=Count('id', filter=Q(status='packages_selected')),
            declined_count=Count('id', filter=Q(status='declined')),
            expired_count=Count('id', filter=Q(status='expired')),
            total_value=Sum('final_total', filter=Q(status='approved'))
        ).order_by('-total_count')
        
        # Format heard about us data
        heard_about_chart = []
        for item in heard_about_data:
            heard_about_chart.append({
                'source': item['heard_about_us'],
                'total': item['total_count'],
                'approved': item['approved_count'],
                'draft': item['draft_count'],
                'submitted': item['submitted_count'],
                'packages_selected': item['packages_selected_count'],
                'declined': item['declined_count'],
                'expired': item['expired_count'],
                'total_value': float(item['total_value'] or 0)
            })
        
        # 3. MONTHLY SALES/ORDER TRENDS (Bar Chart Data)
        # Get data for the last 12 months
        twelve_months_ago = datetime.now() - timedelta(days=365)
        
        monthly_data = queryset.filter(
            created_at__gte=twelve_months_ago
        ).annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(
            total_submissions=Count('id'),
            total_revenue=Sum('final_total', filter=Q(status='approved')),
            approved_orders=Count('id', filter=Q(status='approved')),
            draft_orders=Count('id', filter=Q(status='draft')),
            declined_orders=Count('id', filter=Q(status='declined'))
        ).order_by('month')
        
        # Format monthly data
        sales_trend_chart = []
        for item in monthly_data:
            sales_trend_chart.append({
                'month': item['month'].strftime('%Y-%m'),
                'month_name': item['month'].strftime('%B %Y'),
                'total_submissions': item['total_submissions'],
                'approved_orders': item['approved_orders'],
                'draft_orders': item['draft_orders'],
                'declined_orders': item['declined_orders'],
                'revenue': float(item['total_revenue'] or 0)
            })
        
        # 4. DAILY TRENDS (Last 30 days)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        daily_data = queryset.filter(
            created_at__gte=thirty_days_ago
        ).annotate(
            day=TruncDate('created_at')
        ).values('day').annotate(
            submissions=Count('id'),
            revenue=Sum('final_total', filter=Q(status='approved'))
        ).order_by('day')
        
        daily_trend = []
        for item in daily_data:
            daily_trend.append({
                'date': item['day'].strftime('%Y-%m-%d'),
                'submissions': item['submissions'],
                'revenue': float(item['revenue'] or 0)
            })
        
        # 5. PROPERTY TYPE BREAKDOWN
        property_type_data = queryset.exclude(
            property_type__isnull=True
        ).values('property_type').annotate(
            count=Count('id'),
            revenue=Sum('final_total', filter=Q(status='approved'))
        ).order_by('-count')
        
        property_type_breakdown = []
        for item in property_type_data:
            property_type_breakdown.append({
                'type': item['property_type'],
                'count': item['count'],
                'revenue': float(item['revenue'] or 0)
            })
        
        # 6. RECENT ACTIVITY (Last 5 submissions)
        recent_submissions = queryset.order_by('-created_at')[:5].values(
            'id', 'first_name', 'last_name', 'customer_email', 
            'status', 'final_total', 'created_at'
        )
        
        recent_activity = []
        for sub in recent_submissions:
            recent_activity.append({
                'id': str(sub['id']),
                'customer_name': f"{sub['first_name'] or ''} {sub['last_name'] or ''}".strip() or 'N/A',
                'email': sub['customer_email'],
                'status': sub['status'],
                'amount': float(sub['final_total']),
                'created_at': sub['created_at'].isoformat()
            })
        
        # # 7. PAGINATED SUBMISSIONS LIST
        # paginator = SubmissionPagination()
        # submissions_queryset = queryset.order_by('-created_at')
        # paginated_submissions = paginator.paginate_queryset(submissions_queryset, request)
        # serializer = CustomerSubmissionListSerializer(paginated_submissions, many=True)
        
        # Build response
        response_data = {
            'statistics': {
                'total_submissions': total_submissions,
                'total_worth': float(total_worth),
                'average_order_value': float(avg_order_value),
                'conversion_rate': round(conversion_rate, 2),
                'approved_count': approved_count,
                'status_breakdown': list(status_counts)
            },
            'charts': {
                'heard_about_us': heard_about_chart,
                'monthly_sales_trend': sales_trend_chart,
                'daily_trend': daily_trend,
                'property_type_breakdown': property_type_breakdown
            },
            'recent_activity': recent_activity
        }
        
        return Response(response_data, status=status.HTTP_200_OK)



class PaginatedSubmissionsList(APIView):
    """
    Returns a paginated list of submissions with filters.
    URL: /dashboard/submissions/
    Query Params:
        ?page=1
        ?page_size=20
        ?status=approved
        ?search=John
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = CustomerSubmission.objects.filter(is_on_the_go=False).order_by('-created_at')

        # Optional filters
        status_param = request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)

        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search) | Q(last_name__icontains=search)
            )
        # Pagination
        paginator = SubmissionPagination()
        paginated_qs = paginator.paginate_queryset(queryset, request)
        serializer = CustomerSubmissionListSerializer(paginated_qs, many=True)

        # Paginated response
        return paginator.get_paginated_response(serializer.data)





# New view for Lead Source Analytics
class LeadSourceAnalyticsAPIView(APIView):
    """
    Lead source analytics endpoint that returns:
    - Lead source breakdown
    - Number of leads per source
    - Percentage of leads
    - Close rate (conversion rate)
    - Average ticket value
    - Total amount booked
    """
    permission_classes=[IsAuthenticated]
    def get(self, request):
        # Get query parameters for filtering
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        status_filter = request.query_params.get('status')  # Optional: filter by specific status change
        
        # Base queryset
        queryset = CustomerSubmission.objects.filter(is_on_the_go=False)
        
        # Apply date filters if provided
        if start_date:
            try:
                start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                queryset = queryset.filter(created_at__gte=start_date_obj)
            except ValueError:
                pass
        
        if end_date:
            try:
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                queryset = queryset.filter(created_at__lte=end_date_obj)
            except ValueError:
                pass
        
        # Total number of submissions (for percentage calculation)
        total_leads = queryset.count()
        
        # Aggregate data by heard_about_us (lead source)
        lead_source_data = queryset.exclude(
            Q(heard_about_us__isnull=True) | Q(heard_about_us='')
        ).values('heard_about_us').annotate(
            num_of_leads=Count('id'),
            num_approved=Count('id', filter=Q(status='approved')),
            total_booked=Sum('final_total', filter=Q(status='approved')),
            avg_ticket=Sum('final_total', filter=Q(status='approved'))
        ).order_by('-num_of_leads')
        
        # Format the data
        analytics_data = []
        for item in lead_source_data:
            num_leads = item['num_of_leads']
            num_approved = item['num_approved'] or 0
            total_booked = item['total_booked'] or Decimal('0.00')
            
            # Calculate percentage of leads
            percentage_of_leads = (num_leads / total_leads * 100) if total_leads > 0 else 0
            
            # Calculate close rate (conversion rate)
            close_rate = (num_approved / num_leads * 100) if num_leads > 0 else 0
            
            # Calculate average ticket
            avg_ticket = (total_booked / num_approved) if num_approved > 0 else Decimal('0.00')
            
            analytics_data.append({
                'leadsource': item['heard_about_us'],
                'num_of_leads': num_leads,
                'percentage_of_leads': round(percentage_of_leads, 1),
                'close_rate': round(close_rate, 1),
                'avg_ticket': float(avg_ticket),
                'total_booked': float(total_booked)
            })
        
        # Calculate totals
        total_summary = {
            'total_leads': total_leads,
            'total_approved': queryset.filter(status='approved').count(),
            'overall_close_rate': round(
                (queryset.filter(status='approved').count() / total_leads * 100) if total_leads > 0 else 0,
                1
            ),
            'total_revenue': float(
                queryset.filter(status='approved').aggregate(
                    total=Sum('final_total')
                )['total'] or Decimal('0.00')
            ),
            'overall_avg_ticket': float(
                queryset.filter(status='approved').aggregate(
                    avg=Sum('final_total')
                )['avg'] or Decimal('0.00')
            )
        }
        
        # Calculate overall average ticket properly
        if total_summary['total_approved'] > 0:
            total_summary['overall_avg_ticket'] = round(
                total_summary['total_revenue'] / total_summary['total_approved'],
                2
            )
        
        response_data = {
            'date_range': {
                'start_date': start_date,
                'end_date': end_date
            },
            'summary': total_summary,
            'lead_sources': analytics_data
        }
        
        return Response(response_data, status=status.HTTP_200_OK)




# New view for Monthly Analytics by Year
class MonthlyAnalyticsAPIView(APIView):
    """
    Monthly analytics endpoint that returns:
    - Monthly breakdown by year
    - Number of bids per month
    - Closed bids (approved status)
    - Close rate
    - Total amount booked
    - Average ticket value
    """
    
    def get(self, request):
        # Get year parameter (required)
        year = request.query_params.get('year')
        
        if not year:
            return Response(
                {'error': 'Year parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            year = int(year)
        except ValueError:
            return Response(
                {'error': 'Invalid year format. Please provide a valid year (e.g., 2024)'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Filter queryset by year
        queryset = CustomerSubmission.objects.filter(
            created_at__year=year,
            is_on_the_go=False
        )
        
        # Aggregate data by month
        monthly_data = queryset.annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(
            num_of_bids=Count('id'),
            closed_bids=Count('id', filter=Q(status='approved')),
            total_booked=Sum('final_total', filter=Q(status='approved'))
        ).order_by('-month')
        
        # Format the data
        analytics_data = []
        for item in monthly_data:
            num_bids = item['num_of_bids']
            closed_bids = item['closed_bids'] or 0
            total_booked = item['total_booked'] or Decimal('0.00')
            
            # Calculate close rate
            close_rate = (closed_bids / num_bids * 100) if num_bids > 0 else 0
            
            # Calculate average ticket
            avg_ticket = (total_booked / closed_bids) if closed_bids > 0 else Decimal('0.00')
            
            analytics_data.append({
                'month': item['month'].strftime('%B'),  # Full month name
                'month_number': item['month'].month,
                'num_of_bids': num_bids,
                'closed_bids': closed_bids,
                'close_rate': round(close_rate, 0),  # Round to whole number like in image
                'total_booked': float(total_booked),
                'avg_ticket': float(avg_ticket)
            })
        
        # Calculate year totals
        year_totals = queryset.aggregate(
            total_bids=Count('id'),
            total_closed=Count('id', filter=Q(status='approved')),
            total_revenue=Sum('final_total', filter=Q(status='approved'))
        )
        
        total_closed = year_totals['total_closed'] or 0
        total_revenue = year_totals['total_revenue'] or Decimal('0.00')
        
        year_summary = {
            'year': year,
            'total_bids': year_totals['total_bids'],
            'total_closed_bids': total_closed,
            'overall_close_rate': round(
                (total_closed / year_totals['total_bids'] * 100) if year_totals['total_bids'] > 0 else 0,
                0
            ),
            'total_revenue': float(total_revenue),
            'overall_avg_ticket': float(
                (total_revenue / total_closed) if total_closed > 0 else Decimal('0.00')
            )
        }
        
        response_data = {
            'year': year,
            'summary': year_summary,
            'monthly_data': analytics_data
        }
        
        return Response(response_data, status=status.HTTP_200_OK)


# New view for All Years Analytics
class YearlyAnalyticsAPIView(APIView):
    """
    Returns analytics grouped by year with monthly breakdown
    """
    
    def get(self, request):
        # Get all unique years from submissions
        years = CustomerSubmission.objects.dates('created_at', 'year', order='DESC')
        
        all_years_data = []
        
        for year_date in years:
            year = year_date.year
            
            # Filter queryset by year
            queryset = CustomerSubmission.objects.filter(
                created_at__year=year,
                is_on_the_go=False
            )
            
            # Aggregate data by month
            monthly_data = queryset.annotate(
                month=TruncMonth('created_at')
            ).values('month').annotate(
                num_of_bids=Count('id'),
                closed_bids=Count('id', filter=Q(status='approved')),
                total_booked=Sum('final_total', filter=Q(status='approved'))
            ).order_by('-month')
            
            # Format monthly data
            months_list = []
            for item in monthly_data:
                num_bids = item['num_of_bids']
                closed_bids = item['closed_bids'] or 0
                total_booked = item['total_booked'] or Decimal('0.00')
                
                close_rate = (closed_bids / num_bids * 100) if num_bids > 0 else 0
                avg_ticket = (total_booked / closed_bids) if closed_bids > 0 else Decimal('0.00')
                
                months_list.append({
                    'month': item['month'].strftime('%B'),
                    'month_number': item['month'].month,
                    'num_of_bids': num_bids,
                    'closed_bids': closed_bids,
                    'close_rate': round(close_rate, 0),
                    'total_booked': float(total_booked),
                    'avg_ticket': float(avg_ticket)
                })
            
            # Year summary
            year_totals = queryset.aggregate(
                total_bids=Count('id'),
                total_closed=Count('id', filter=Q(status='approved')),
                total_revenue=Sum('final_total', filter=Q(status='approved'))
            )
            
            total_closed = year_totals['total_closed'] or 0
            total_revenue = year_totals['total_revenue'] or Decimal('0.00')
            
            all_years_data.append({
                'year': year,
                'summary': {
                    'total_bids': year_totals['total_bids'],
                    'total_closed_bids': total_closed,
                    'overall_close_rate': round(
                        (total_closed / year_totals['total_bids'] * 100) if year_totals['total_bids'] > 0 else 0,
                        0
                    ),
                    'total_revenue': float(total_revenue),
                    'overall_avg_ticket': float(
                        (total_revenue / total_closed) if total_closed > 0 else Decimal('0.00')
                    )
                },
                'monthly_data': months_list
            })
        
        response_data = {
            'years': all_years_data
        }
        
        return Response(response_data, status=status.HTTP_200_OK)


# ==================================================
# Admin Management Views (Super Admin Only)
# ==================================================

class AdminUserListCreateView(generics.ListCreateAPIView):
    """
    List all admin users or create a new admin user.
    Only accessible by super admins.
    
    GET /api/service/admins/
    - Returns list of all admin users
    
    POST /api/service/admins/
    - Creates a new admin user
    - Required fields: username, email, password
    - Optional fields: first_name, last_name
    """
    permission_classes = [IsSuperAdminPermission]
    queryset = User.objects.filter(is_admin=True).order_by('-created_at')
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return AdminUserCreateSerializer
        return AdminUserListSerializer
    
    def get_queryset(self):
        """Exclude super admins from the list (only show regular admins)"""
        return User.objects.filter(is_admin=True, is_super_admin=False).order_by('-created_at')
    
    def perform_create(self, serializer):
        """Create admin user with the current super admin as creator"""
        serializer.save()


class AdminUserDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete an admin user.
    Only accessible by super admins.
    
    GET /api/service/admins/<id>/
    - Get admin user details
    
    PUT /api/service/admins/<id>/
    - Update admin user (username, email, first_name, last_name, is_active)
    
    PATCH /api/service/admins/<id>/
    - Partial update admin user
    
    DELETE /api/service/admins/<id>/
    - Delete admin user (cannot delete yourself)
    """
    permission_classes = [IsSuperAdminPermission]
    queryset = User.objects.filter(is_admin=True)
    serializer_class = AdminUserUpdateSerializer
    
    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return AdminUserUpdateSerializer
        return AdminUserListSerializer
    
    def get_queryset(self):
        """Exclude super admins from being modified"""
        return User.objects.filter(is_admin=True, is_super_admin=False)
    
    def destroy(self, request, *args, **kwargs):
        """Prevent super admin from deleting themselves"""
        instance = self.get_object()
        if instance.id == request.user.id:
            return Response(
                {"error": "You cannot delete your own account."},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)


class AdminUserBlockView(APIView):
    """
    Block an admin user.
    Only accessible by super admins.
    
    POST /api/service/admins/<id>/block/
    - Block an admin user (set is_active=False)
    """
    permission_classes = [IsSuperAdminPermission]
    
    def post(self, request, admin_id):
        """Block an admin user"""
        try:
            admin_user = User.objects.get(id=admin_id, is_admin=True, is_super_admin=False)
            if admin_user.id == request.user.id:
                return Response(
                    {"error": "You cannot block your own account."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            admin_user.is_active = False
            admin_user.save()
            return Response({
                "message": f"Admin user '{admin_user.username}' has been blocked.",
                "user": AdminUserListSerializer(admin_user).data
            }, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response(
                {"error": "Admin user not found."},
                status=status.HTTP_404_NOT_FOUND
            )


class AdminUserUnblockView(APIView):
    """
    Unblock an admin user.
    Only accessible by super admins.
    """
    permission_classes = [IsSuperAdminPermission]
    
    def post(self, request, admin_id):
        """Unblock an admin user"""
        try:
            admin_user = User.objects.get(id=admin_id, is_admin=True, is_super_admin=False)
            admin_user.is_active = True
            admin_user.save()
            return Response({
                "message": f"Admin user '{admin_user.username}' has been unblocked.",
                "user": AdminUserListSerializer(admin_user).data
            }, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response(
                {"error": "Admin user not found."},
                status=status.HTTP_404_NOT_FOUND
            )


class AdminUserChangePasswordView(APIView):
    """
    Change password for an admin user.
    Only accessible by super admins.
    
    POST /api/service/admins/<id>/change-password/
    - Change admin user's password
    - Required field: password (min 8 characters)
    """
    permission_classes = [IsSuperAdminPermission]
    
    def post(self, request, admin_id):
        """Change admin user's password"""
        try:
            admin_user = User.objects.get(id=admin_id, is_admin=True, is_super_admin=False)
            password = request.data.get('password')
            
            if not password:
                return Response(
                    {"error": "Password is required."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if len(password) < 8:
                return Response(
                    {"error": "Password must be at least 8 characters long."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            admin_user.set_password(password)
            admin_user.save()
            
            return Response({
                "message": f"Password for admin user '{admin_user.username}' has been changed successfully."
            }, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response(
                {"error": "Admin user not found."},
                status=status.HTTP_404_NOT_FOUND
            )