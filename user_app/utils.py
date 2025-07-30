# utils.py
from decimal import Decimal
from geopy.distance import geodesic
from service_app.models import Location, QuestionPricing, OptionPricing


def find_nearest_location(latitude, longitude, max_distance_km=3):
    """
    Find the nearest location within max_distance_km
    Returns (location, distance) or (None, None)
    """
    user_coords = (float(latitude), float(longitude))
    nearest_location = None
    nearest_distance = float('inf')
    
    for location in Location.objects.filter(is_active=True):
        location_coords = (float(location.latitude), float(location.longitude))
        distance = geodesic(user_coords, location_coords).kilometers
        
        if distance <= max_distance_km and distance < nearest_distance:
            nearest_location = location
            nearest_distance = distance
    
    if nearest_location:
        return nearest_location, Decimal(str(round(nearest_distance, 2)))
    
    return None, None


def calculate_question_price_adjustment(question, answer_value, package):
    """
    Calculate price adjustment for a question answer
    Returns Decimal adjustment amount
    """
    try:
        pricing_rule = QuestionPricing.objects.get(question=question, package=package)
    except QuestionPricing.DoesNotExist:
        return Decimal('0.00')
    
    if question.question_type == 'yes_no':
        # Only apply pricing if answer is True (Yes) and pricing type is not 'ignore'
        if answer_value and pricing_rule.yes_pricing_type != 'ignore':
            return apply_pricing_logic(
                pricing_rule.yes_pricing_type,
                pricing_rule.yes_value,
                package.base_price
            )
    
    return Decimal('0.00')


def calculate_option_price_adjustment(option, package):
    """
    Calculate price adjustment for a selected option
    Returns Decimal adjustment amount
    """
    try:
        pricing_rule = OptionPricing.objects.get(option=option, package=package)
    except OptionPricing.DoesNotExist:
        return Decimal('0.00')
    
    if pricing_rule.pricing_type != 'ignore':
        return apply_pricing_logic(
            pricing_rule.pricing_type,
            pricing_rule.value,
            package.base_price
        )
    
    return Decimal('0.00')


def apply_pricing_logic(pricing_type, value, base_price):
    """
    Apply pricing logic based on type and value
    Returns Decimal adjustment amount
    """
    if pricing_type == 'upcharge_percent':
        return (base_price * value) / Decimal('100')
    elif pricing_type == 'discount_percent':
        return -((base_price * value) / Decimal('100'))
    elif pricing_type == 'fixed_price':
        return value
    else:  # ignore
        return Decimal('0.00')


def calculate_total_quote_price(contact, package, answers_data):
    """
    Calculate total price for a quote including all adjustments
    Returns dict with price breakdown
    """
    base_price = package.base_price
    trip_surcharge = Decimal('0.00')
    question_adjustments = Decimal('0.00')
    
    # Find nearest location and apply trip surcharge
    nearest_location, distance = find_nearest_location(
        contact.latitude, 
        contact.longitude
    )
    
    if nearest_location:
        trip_surcharge = nearest_location.trip_surcharge
    
    # Calculate question adjustments
    for answer_data in answers_data:
        question_id = answer_data['question_id']
        
        try:
            question = package.service.questions.get(id=question_id, is_active=True)
        except:
            continue
        
        if question.question_type == 'yes_no':
            yes_no_answer = answer_data.get('yes_no_answer', False)
            adjustment = calculate_question_price_adjustment(
                question, yes_no_answer, package
            )
            question_adjustments += adjustment
            
        elif question.question_type == 'options':
            option_id = answer_data.get('selected_option_id')
            if option_id:
                try:
                    option = question.options.get(id=option_id, is_active=True)
                    adjustment = calculate_option_price_adjustment(option, package)
                    question_adjustments += adjustment
                except:
                    continue
    
    total_price = base_price + trip_surcharge + question_adjustments
    
    return {
        'base_price': base_price,
        'trip_surcharge': trip_surcharge,
        'question_adjustments': question_adjustments,
        'total_price': total_price,
        'nearest_location': nearest_location,
        'distance_to_location': distance
    }