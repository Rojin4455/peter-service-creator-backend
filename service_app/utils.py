from decimal import Decimal
from typing import Dict, List, Any
from .models import Package, Question, QuestionOption, QuestionPricing, OptionPricing, Location

class PricingCalculator:
    """Utility class for calculating pricing based on answers"""
    
    @staticmethod
    def calculate_price(package_id: str, location_id: str = None, answers: List[Dict] = None) -> Dict[str, Any]:
        """
        Calculate total price for a package with given answers
        
        Args:
            package_id: UUID of the package
            location_id: UUID of the location (optional)
            answers: List of answers in format:
                [
                    {'question_id': 'uuid', 'answer': True},  # For yes/no
                    {'question_id': 'uuid', 'option_id': 'uuid'}  # For options
                ]
        
        Returns:
            Dict with price breakdown
        """
        try:
            package = Package.objects.get(id=package_id)
            location = None
            if location_id:
                location = Location.objects.get(id=location_id)
            
            base_price = package.base_price
            trip_surcharge = location.trip_surcharge if location else Decimal('0.00')
            question_adjustments = Decimal('0.00')
            adjustment_details = []
            
            if answers:
                for answer in answers:
                    question_id = answer.get('question_id')
                    question = Question.objects.get(id=question_id)
                    
                    if question.question_type == 'yes_no':
                        yes_answer = answer.get('answer', False)
                        if yes_answer:
                            try:
                                pricing = QuestionPricing.objects.get(
                                    question=question, package=package
                                )
                                adjustment = PricingCalculator._calculate_adjustment(
                                    base_price, pricing.yes_pricing_type, pricing.yes_value
                                )
                                question_adjustments += adjustment
                                adjustment_details.append({
                                    'question': question.question_text,
                                    'answer': 'Yes',
                                    'adjustment': adjustment,
                                    'type': pricing.yes_pricing_type
                                })
                            except QuestionPricing.DoesNotExist:
                                pass
                    
                    elif question.question_type == 'options':
                        option_id = answer.get('option_id')
                        if option_id:
                            try:
                                option = QuestionOption.objects.get(id=option_id)
                                pricing = OptionPricing.objects.get(
                                    option=option, package=package
                                )
                                adjustment = PricingCalculator._calculate_adjustment(
                                    base_price, pricing.pricing_type, pricing.value
                                )
                                question_adjustments += adjustment
                                adjustment_details.append({
                                    'question': question.question_text,
                                    'answer': option.option_text,
                                    'adjustment': adjustment,
                                    'type': pricing.pricing_type
                                })
                            except (QuestionOption.DoesNotExist, OptionPricing.DoesNotExist):
                                pass
            
            total_price = base_price + trip_surcharge + question_adjustments
            
            return {
                'base_price': base_price,
                'trip_surcharge': trip_surcharge,
                'question_adjustments': question_adjustments,
                'total_price': total_price,
                'adjustment_details': adjustment_details,
                'package_name': package.name,
                'location_name': location.name if location else None
            }
            
        except Exception as e:
            raise ValueError(f"Error calculating price: {str(e)}")
    
    @staticmethod
    def _calculate_adjustment(base_price: Decimal, pricing_type: str, value: Decimal) -> Decimal:
        """Calculate price adjustment based on pricing type"""
        if pricing_type == 'upcharge_percent':
            return base_price * (value / Decimal('100'))
        elif pricing_type == 'discount_percent':
            return -(base_price * (value / Decimal('100')))
        elif pricing_type == 'fixed_price':
            return value
        else:  # ignore
            return Decimal('0.00')


class DataValidator:
    """Utility class for data validation"""
    
    @staticmethod
    def validate_package_data(data: Dict) -> List[str]:
        """Validate package data"""
        errors = []
        
        if not data.get('name'):
            errors.append("Package name is required")
        
        if not data.get('base_price'):
            errors.append("Base price is required")
        else:
            try:
                price = Decimal(str(data['base_price']))
                if price < 0:
                    errors.append("Base price cannot be negative")
            except:
                errors.append("Invalid base price format")
        
        return errors
    
    @staticmethod
    def validate_question_data(data: Dict) -> List[str]:
        """Validate question data"""
        errors = []
        
        if not data.get('question_text'):
            errors.append("Question text is required")
        
        if not data.get('question_type'):
            errors.append("Question type is required")
        elif data.get('question_type') not in ['yes_no', 'options']:
            errors.append("Invalid question type")
        
        if data.get('question_type') == 'options':
            options = data.get('options', [])
            if len(options) < 2:
                errors.append("Options questions must have at least 2 options")
        
        return errors


# Custom exceptions
class PricingCalculationError(Exception):
    """Raised when there's an error in pricing calculation"""
    pass

class ValidationError(Exception):
    """Raised when data validation fails"""
    pass