from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from decimal import Decimal
from .models import (
    Service, Package, Feature, PackageFeature, Question, 
    QuestionOption, QuestionPricing, OptionPricing, Location
)
from .utils import PricingCalculator

User = get_user_model()


class ModelTestCase(TestCase):
    """Test case for model functionality"""
    
    def setUp(self):
        
        self.admin_user = User.objects.create_user(
            username='testadmin',
            email='admin@test.com',
            password='testpass123',
            is_admin=True
        )
        
        self.service = Service.objects.create(
            name='Test Service',
            description='Test service description',
            created_by=self.admin_user
        )
        
        self.package = Package.objects.create(
            service=self.service,
            name='Test Package',
            base_price=Decimal('100.00')
        )

    def test_service_creation(self):
        """Test service model creation"""
        self.assertEqual(self.service.name, 'Test Service')
        self.assertEqual(self.service.created_by, self.admin_user)
        self.assertTrue(self.service.is_active)

    def test_package_creation(self):
        """Test package model creation"""
        self.assertEqual(self.package.name, 'Test Package')
        self.assertEqual(self.package.service, self.service)
        self.assertEqual(self.package.base_price, Decimal('100.00'))

    def test_package_str_method(self):
        """Test package string representation"""
        expected = f"{self.service.name} - {self.package.name}"
        self.assertEqual(str(self.package), expected)

    def test_feature_creation(self):
        """Test feature model creation"""
        feature = Feature.objects.create(
            service=self.service,
            name='Test Feature',
            description='Test feature description'
        )
        self.assertEqual(feature.name, 'Test Feature')
        self.assertEqual(feature.service, self.service)

    def test_question_creation(self):
        """Test question model creation"""
        question = Question.objects.create(
            service=self.service,
            question_text='Test question?',
            question_type='yes_no'
        )
        self.assertEqual(question.question_text, 'Test question?')
        self.assertEqual(question.question_type, 'yes_no')
        self.assertEqual(question.service, self.service)


class APITestCase(APITestCase):
    """Test case for API endpoints"""
    
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='testadmin',
            email='admin@test.com',
            password='testpass123',
            is_admin=True
        )
        self.token = Token.objects.create(user=self.admin_user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        
        self.service = Service.objects.create(
            name='Test Service',
            description='Test service description',
            created_by=self.admin_user
        )

    def test_admin_login(self):
        """Test admin login endpoint"""
        self.client.credentials()  # Clear credentials
        url = '/api/service/auth/login/'
        data = {
            'username': 'testadmin',
            'password': 'testpass123'
        }
        response = self.client.post(url, data, format='json')
        print("test_admin_login",response.status_code)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)
        self.assertIn('user', response.data)

    def test_non_admin_login_rejected(self):
        """Test that non-admin users cannot login"""
        regular_user = User.objects.create_user(
            username='regular',
            email='regular@test.com',
            password='testpass123',
            is_admin=False
        )
        
        self.client.credentials()  # Clear credentials
        url = '/api/service/auth/login/'
        data = {
            'username': 'regular',
            'password': 'testpass123'
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_service_list(self):
        """Test service list endpoint"""
        url = '/api/service/services/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

    def test_service_creation(self):
        """Test service creation endpoint"""
        url = '/api/service/services/'
        data = {
            'name': 'New Service',
            'description': 'New service description'
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'New Service')

    def test_package_creation(self):
        """Test package creation endpoint"""
        url = '/api/service/packages/'
        data = {
            'service': str(self.service.id),
            'name': 'Test Package',
            'base_price': '150.00'
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Test Package')

    def test_question_creation(self):
        """Test question creation endpoint"""
        url = '/api/service/questions/'
        data = {
            'service': str(self.service.id),
            'question_text': 'Do you need extra cleaning?',
            'question_type': 'yes_no'
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['question_text'], 'Do you need extra cleaning?')

    def test_unauthorized_access(self):
        """Test that unauthorized users cannot access admin endpoints"""
        self.client.credentials()  # Clear credentials
        url = '/api/service/services/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PricingCalculatorTestCase(TestCase):
    """Test case for pricing calculator utility"""
    
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='testadmin',
            is_admin=True
        )
        
        self.service = Service.objects.create(
            name='Test Service',
            description='Test service',
            created_by=self.admin_user
        )
        
        self.package = Package.objects.create(
            service=self.service,
            name='Test Package',
            base_price=Decimal('100.00')
        )
        
        self.location = Location.objects.create(
            name='Test Location',
            address='123 Test St',
            latitude=Decimal('40.7128'),
            longitude=Decimal('-74.0060'),
            trip_surcharge=Decimal('15.00')
        )
        
        # Create a yes/no question
        self.yes_no_question = Question.objects.create(
            service=self.service,
            question_text='Need extra service?',
            question_type='yes_no'
        )
        
        # Create pricing rule for yes/no question
        QuestionPricing.objects.create(
            question=self.yes_no_question,
            package=self.package,
            yes_pricing_type='upcharge_percent',
            yes_value=Decimal('20.00')
        )

    def test_basic_pricing_calculation(self):
        """Test basic pricing calculation without questions"""
        result = PricingCalculator.calculate_price(
            package_id=str(self.package.id),
            location_id=str(self.location.id)
        )
        
        expected_total = Decimal('115.00')  # 100 + 15 surcharge
        self.assertEqual(result['total_price'], expected_total)
        self.assertEqual(result['base_price'], Decimal('100.00'))
        self.assertEqual(result['trip_surcharge'], Decimal('15.00'))
        self.assertEqual(result['question_adjustments'], Decimal('0.00'))

    def test_pricing_with_yes_answer(self):
        """Test pricing calculation with yes answer"""
        answers = [
            {'question_id': str(self.yes_no_question.id), 'answer': True}
        ]
        
        result = PricingCalculator.calculate_price(
            package_id=str(self.package.id),
            location_id=str(self.location.id),
            answers=answers
        )
        
        # Base: 100, Surcharge: 15, Question adjustment: 20% of 100 = 20
        expected_total = Decimal('135.00')
        self.assertEqual(result['total_price'], expected_total)
        self.assertEqual(result['question_adjustments'], Decimal('20.00'))

    def test_pricing_with_no_answer(self):
        """Test pricing calculation with no answer"""
        answers = [
            {'question_id': str(self.yes_no_question.id), 'answer': False}
        ]
        
        result = PricingCalculator.calculate_price(
            package_id=str(self.package.id),
            location_id=str(self.location.id),
            answers=answers
        )
        
        # Base: 100, Surcharge: 15, No question adjustment for 'No' answer
        expected_total = Decimal('115.00')
        self.assertEqual(result['total_price'], expected_total)
        self.assertEqual(result['question_adjustments'], Decimal('0.00'))


class IntegrationTestCase(APITestCase):
    """Integration test case for complete workflows"""
    
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='admin123',
            is_admin=True
        )
        self.token = Token.objects.create(user=self.admin_user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_complete_service_setup_workflow(self):
        """Test complete workflow from service creation to pricing calculation"""
        
        # 1. Create Service
        service_data = {
            'name': 'Window Cleaning',
            'description': 'Professional window cleaning'
        }
        service_response = self.client.post('/api/service/services/', service_data)
        self.assertEqual(service_response.status_code, status.HTTP_201_CREATED)
        service_id = service_response.data['id']
        
        # 2. Create Package
        package_data = {
            'service': service_id,
            'name': 'Basic Package',
            'base_price': '75.00'
        }
        package_response = self.client.post('/api/service/packages/', package_data)
        self.assertEqual(package_response.status_code, status.HTTP_201_CREATED)
        package_id = package_response.data['id']
        
        # 3. Create Location
        location_data = {
            'name': 'Downtown Office',
            'address': '123 Main St, New York, NY',
            'latitude': '40.7128',
            'longitude': '-74.0060',
            'trip_surcharge': '10.00'
        }
        location_response = self.client.post('/api/service/locations/', location_data)
        self.assertEqual(location_response.status_code, status.HTTP_201_CREATED)
        location_id = location_response.data['id']
        
        # 4. Create Question
        question_data = {
            'service': service_id,
            'question_text': 'Do windows have stickers?',
            'question_type': 'yes_no'
        }
        question_response = self.client.post('/api/service/questions/', question_data)
        self.assertEqual(question_response.status_code, status.HTTP_201_CREATED)
        question_id = question_response.data['id']
        
        # 5. Create Pricing Rule
        pricing_data = {
            'question': question_id,
            'package': package_id,
            'yes_pricing_type': 'upcharge_percent',
            'yes_value': '15.00'
        }
        pricing_response = self.client.post('/api/service/question-pricing/', pricing_data)
        self.assertEqual(pricing_response.status_code, status.HTTP_201_CREATED)
        
        # 6. Calculate Pricing
        calculation_data = {
            'package_id': package_id,
            'location_id': location_id,
            'answers': [
                {'question_id': question_id, 'answer': True}
            ]
        }
        calc_response = self.client.post('/api/service/pricing/calculate/', calculation_data)
        self.assertEqual(calc_response.status_code, status.HTTP_200_OK)
        
        # Verify calculation: Base 75 + Surcharge 10 + 15% upcharge (11.25) = 96.25
        self.assertEqual(calc_response.data['base_price'], '75.00')
        self.assertEqual(calc_response.data['trip_surcharge'], '10.00')
        self.assertEqual(calc_response.data['question_adjustments'], '11.25')  # 15% of 75
        self.assertEqual(calc_response.data['total_price'], '96.25')

    def test_option_question_workflow(self):
        """Test workflow with multiple choice questions"""
        
        # Create service and package first
        service = Service.objects.create(
            name='House Cleaning',
            created_by=self.admin_user
        )
        package = Package.objects.create(
            service=service,
            name='Standard',
            base_price=Decimal('100.00')
        )
        
        # Create multiple choice question with options
        question_data = {
            'service': str(service.id),
            'question_text': 'How many rooms?',
            'question_type': 'options',
            'options': [
                {'option_text': '1-2 rooms', 'order': 1},
                {'option_text': '3-4 rooms', 'order': 2},
                {'option_text': '5+ rooms', 'order': 3}
            ]
        }
        
        question_response = self.client.post('/api/service/questions/', question_data)
        self.assertEqual(question_response.status_code, status.HTTP_201_CREATED)
        
        # Get the created question and its options
        question = Question.objects.get(id=question_response.data['id'])
        option = question.options.first()
        
        # Create option pricing
        option_pricing_data = {
            'option': str(option.id),
            'package': str(package.id),
            'pricing_type': 'upcharge_percent',
            'value': '25.00'
        }
        
        pricing_response = self.client.post('/api/service/option-pricing/', option_pricing_data)
        self.assertEqual(pricing_response.status_code, status.HTTP_201_CREATED)
        
        # Test pricing calculation with option selection
        calculation_data = {
            'package_id': str(package.id),
            'answers': [
                {'question_id': str(question.id), 'option_id': str(option.id)}
            ]
        }
        
        calc_response = self.client.post('/api/service/pricing/calculate/', calculation_data)
        self.assertEqual(calc_response.status_code, status.HTTP_200_OK)
        
        # Base 100 + 25% upcharge = 125
        self.assertEqual(calc_response.data['total_price'], '125.00')


# ==================================================
# SETUP INSTRUCTIONS
"""
# Django DRF Service Platform - Setup Instructions

## Prerequisites
- Python 3.8+
- PostgreSQL 12+
- Redis (optional, for caching and background tasks)
- Git

## Quick Setup

1. **Clone and Setup Environment**
   ```bash
   git clone <your-repo-url>
   cd service-platform
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Environment Configuration**
   ```bash
   cp .env.example .env
   # Edit .env file with your configurations
   ```

3. **Database Setup**
   ```bash
   # Create PostgreSQL database
   createdb service_platform
   
   # Run migrations
   python manage.py makemigrations
   python manage.py migrate
   ```

4. **Create Admin User and Seed Data**
   ```bash
   python manage.py create_admin --username admin --email admin@example.com --password admin123
   python manage.py seed_data
   ```

5. **Run the Server**
   ```bash
   python manage.py runserver
   ```

## Docker Setup (Alternative)

1. **Using Docker Compose**
   ```bash
   docker-compose up --build
   ```

2. **Run migrations in Docker**
   ```bash
   docker-compose exec web python manage.py migrate
   docker-compose exec web python manage.py create_admin --username admin --email admin@example.com --password admin123
   docker-compose exec web python manage.py seed_data
   ```

## Testing

```bash
# Run all tests
python manage.py test

# Run with coverage
coverage run --source='.' manage.py test
coverage report
coverage html

# Run with pytest (alternative)
pytest
```

## API Usage Examples

### 1. Admin Login
```bash
curl -X POST http://localhost:8000/api/service/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

### 2. Get Services
```bash
curl -X GET http://localhost:8000/api/service/services/ \
  -H "Authorization: Token YOUR_TOKEN_HERE"
```

### 3. Create a Service
```bash
curl -X POST http://localhost:8000/api/service/services/ \
  -H "Authorization: Token YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "House Cleaning",
    "description": "Professional house cleaning services"
  }'
```

### 4. Create a Package
```bash
curl -X POST http://localhost:8000/api/service/packages/ \
  -H "Authorization: Token YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "service": "SERVICE_UUID_HERE",
    "name": "Basic Package",
    "base_price": "75.00"
  }'
```

### 5. Calculate Pricing
```bash
curl -X POST http://localhost:8000/api/service/pricing/calculate/ \
  -H "Authorization: Token YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "package_id": "PACKAGE_UUID_HERE",
    "location_id": "LOCATION_UUID_HERE",
    "answers": [
      {"question_id": "QUESTION_UUID_HERE", "answer": true}
    ]
  }'
```

## Production Deployment

### Environment Variables for Production
```bash
SECRET_KEY=your-production-secret-key
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
DB_NAME=service_platform_prod
DB_USER=your_db_user
DB_PASSWORD=your_secure_password
DB_HOST=your_db_host
GOOGLE_PLACES_API_KEY=your_google_api_key
```

### Using Gunicorn
```bash
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```

### Static Files
```bash
python manage.py collectstatic --noinput
```

## Key Features Implemented

✅ **Authentication & Admin Setup**
- Token-based authentication for admins
- Custom user model with admin permissions
- Secure login/logout endpoints

✅ **Location Management**
- Google Places API integration
- Location storage with coordinates
- Trip surcharge calculation

✅ **Service Management**
- Service CRUD operations
- Package management with pricing
- Feature assignment to packages

✅ **Dynamic Question Builder**
- Yes/No questions with custom pricing
- Multiple choice questions with options
- Flexible pricing rules per package
- Percentage-based and fixed pricing

✅ **Scalable Architecture**
- UUID primary keys for better scalability
- Modular design for easy extension
- Comprehensive serializers and views
- Built-in pricing calculator utility

✅ **Additional Features**
- Bulk pricing operations
- Service analytics
- Comprehensive test suite
- Docker support
- Production-ready configuration

## Next Steps for User Side
When you're ready to build the user side, you can:
1. Create user registration/authentication
2. Build booking/order creation endpoints
3. Implement payment processing
4. Add order tracking and notifications
5. Create customer dashboard

The current admin infrastructure will support all user-side operations seamlessly!
"""