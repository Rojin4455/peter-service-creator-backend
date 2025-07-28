# views.py
from rest_framework import generics, status, permissions
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
import os
from django.db import models

from rest_framework.permissions import IsAuthenticated

from .models import (
    User, Location, Service, Package, Feature, PackageFeature,
    Question, QuestionOption, QuestionPricing, OptionPricing,
    Order, OrderQuestionAnswer
)
from .serializers import (
    UserSerializer, LoginSerializer, LocationSerializer, ServiceSerializer,
    ServiceListSerializer, PackageSerializer, FeatureSerializer,
    PackageFeatureSerializer, QuestionSerializer, QuestionCreateSerializer,
    QuestionOptionSerializer, QuestionPricingSerializer, OptionPricingSerializer,
    PackageWithFeaturesSerializer, BulkPricingUpdateSerializer,
    ServiceAnalyticsSerializer
)



from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAdminUser, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class IsAdminPermission(permissions.BasePermission):
    """Custom permission to only allow admins to access views"""
    
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_admin
    


class AdminTokenObtainPairView(TokenObtainPairView):
    permission_classes = [AllowAny]
    print('here')
    # permission_classes = [IsAdminUser]

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


class GooglePlacesSearchView(APIView):
    """Search Google Places API for locations"""
    permission_classes = [IsAdminPermission]

    def get(self, request):
        query = request.query_params.get('query', '')
        if not query:
            return Response({'error': 'Query parameter is required'}, 
                          status=status.HTTP_400_BAD_REQUEST)

        # Note: You'll need to set GOOGLE_PLACES_API_KEY in your environment
        api_key = os.getenv('GOOGLE_PLACES_API_KEY')
        if not api_key:
            return Response({'error': 'Google Places API key not configured'}, 
                          status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            url = 'https://maps.googleapis.com/maps/api/place/textsearch/json'
            params = {
                'query': query,
                'key': api_key,
                'fields': 'place_id,name,formatted_address,geometry'
            }
            
            response = requests.get(url, params=params)
            data = response.json()
            
            if data.get('status') == 'OK':
                places = []
                for place in data.get('results', []):
                    places.append({
                        'place_id': place.get('place_id'),
                        'name': place.get('name'),
                        'address': place.get('formatted_address'),
                        'latitude': place.get('geometry', {}).get('location', {}).get('lat'),
                        'longitude': place.get('geometry', {}).get('location', {}).get('lng')
                    })
                return Response({'places': places})
            else:
                return Response({'error': 'Google Places API error', 'details': data}, 
                              status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Service Views
class ServiceListCreateView(generics.ListCreateAPIView):
    """List all services and create new ones"""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Service.objects.filter(is_active=True).prefetch_related(
            'packages', 'features', 'questions'
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
        'packages', 'features', 'questions__options', 'questions__pricing_rules'
    )
    serializer_class = ServiceSerializer
    permission_classes = [IsAdminPermission]

    def perform_destroy(self, instance):
        # Soft delete
        instance.is_active = False
        instance.save()


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


# Question Views
class QuestionListCreateView(generics.ListCreateAPIView):
    """List all questions and create new ones"""
    permission_classes = [IsAdminPermission]

    def get_queryset(self):
        queryset = Question.objects.filter(is_active=True).select_related('service').prefetch_related(
            'options', 'pricing_rules__package'
        )
        service_id = self.request.query_params.get('service', None)
        if service_id:
            queryset = queryset.filter(service_id=service_id)
        return queryset.order_by('service__name', 'order', 'created_at')

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return QuestionCreateSerializer
        return QuestionSerializer


class QuestionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a question"""
    queryset = Question.objects.prefetch_related('options', 'pricing_rules')
    serializer_class = QuestionSerializer
    permission_classes = [IsAdminPermission]

    # def perform_destroy(self, instance):
    #     # Soft delete
    #     instance.is_active = False
    #     instance.save()


# Question Option Views
class QuestionOptionListCreateView(generics.ListCreateAPIView):
    """List and create question options"""
    queryset = QuestionOption.objects.filter(is_active=True)
    serializer_class = QuestionOptionSerializer
    permission_classes = [IsAdminPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        question_id = self.request.query_params.get('question', None)
        if question_id:
            queryset = queryset.filter(question_id=question_id)
        return queryset.order_by('order', 'option_text')


class QuestionOptionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a question option"""
    queryset = QuestionOption.objects.all()
    serializer_class = QuestionOptionSerializer
    permission_classes = [IsAdminPermission]

    def perform_destroy(self, instance):
        # Soft delete
        instance.is_active = False
        instance.save()


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
                        value = Decimal(str(rule['value']))
                        
                        package = get_object_or_404(Package, id=package_id)
                        
                        pricing, created = QuestionPricing.objects.get_or_create(
                            question=question,
                            package=package,
                            defaults={
                                'yes_pricing_type': pricing_type,
                                'yes_value': value
                            }
                        )
                        
                        if not created:
                            pricing.yes_pricing_type = pricing_type
                            pricing.yes_value = value
                            pricing.save()

                return Response({'message': 'Pricing rules updated successfully'})
                
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
            return Response({'error': 'option_id and pricing_rules are required'}, 
                          status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                option = get_object_or_404(QuestionOption, id=option_id)
                
                for rule in pricing_rules:
                    package_id = rule['package_id']
                    pricing_type = rule['pricing_type']
                    value = Decimal(str(rule['value']))
                    
                    package = get_object_or_404(Package, id=package_id)
                    
                    pricing, created = OptionPricing.objects.get_or_create(
                        option=option,
                        package=package,
                        defaults={
                            'pricing_type': pricing_type,
                            'value': value
                        }
                    )
                    
                    if not created:
                        pricing.pricing_type = pricing_type
                        pricing.value = value
                        pricing.save()

            return Response({'message': 'Option pricing rules updated successfully'})
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)




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
    """Calculate pricing for a given package and answers"""
    permission_classes = [IsAdminPermission]

    def post(self, request):
        package_id = request.data.get('package_id')
        location_id = request.data.get('location_id')
        answers = request.data.get('answers', [])  # List of {question_id, answer} or {question_id, option_id}

        if not package_id:
            return Response({'error': 'package_id is required'}, 
                          status=status.HTTP_400_BAD_REQUEST)

        try:
            package = get_object_or_404(Package, id=package_id)
            location = None
            if location_id:
                location = get_object_or_404(Location, id=location_id)

            # Base calculations
            base_price = package.base_price
            trip_surcharge = location.trip_surcharge if location else Decimal('0.00')
            question_adjustments = Decimal('0.00')

            # Calculate question adjustments
            for answer in answers:
                question_id = answer.get('question_id')
                question = get_object_or_404(Question, id=question_id)

                if question.question_type == 'yes_no':
                    yes_answer = answer.get('answer', False)
                    if yes_answer:
                        try:
                            pricing = QuestionPricing.objects.get(question=question, package=package)
                            adjustment = self._calculate_adjustment(
                                base_price, pricing.yes_pricing_type, pricing.yes_value
                            )
                            question_adjustments += adjustment
                        except QuestionPricing.DoesNotExist:
                            pass

                elif question.question_type == 'options':
                    option_id = answer.get('option_id')
                    if option_id:
                        try:
                            option = get_object_or_404(QuestionOption, id=option_id)
                            pricing = OptionPricing.objects.get(option=option, package=package)
                            adjustment = self._calculate_adjustment(
                                base_price, pricing.pricing_type, pricing.value
                            )
                            question_adjustments += adjustment
                        except OptionPricing.DoesNotExist:
                            pass

            total_price = base_price + trip_surcharge + question_adjustments

            return Response({
                'base_price': base_price,
                'trip_surcharge': trip_surcharge,
                'question_adjustments': question_adjustments,
                'total_price': total_price,
                'package_name': package.name,
                'location_name': location.name if location else None
            })

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def _calculate_adjustment(self, base_price, pricing_type, value):
        """Calculate price adjustment based on pricing type"""
        if pricing_type == 'upcharge_percent':
            return base_price * (value / Decimal('100'))
        elif pricing_type == 'discount_percent':
            return -(base_price * (value / Decimal('100')))
        elif pricing_type == 'fixed_price':
            return value
        else:  # ignore
            return Decimal('0.00')