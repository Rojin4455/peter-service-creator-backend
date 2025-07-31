# utils.py
from decimal import Decimal
from geopy.distance import geodesic
from service_app.models import Location, QuestionPricing, OptionPricing
from accounts.models import GHLAuthCredentials
import requests
from django.conf import settings


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
    Apply pricing logic based on type and value - FIXED AMOUNTS ONLY
    Returns Decimal adjustment amount
    """
    if pricing_type == 'upcharge_percent':  # Now treats as fixed upcharge
        return value
    elif pricing_type == 'discount_percent':  # Now treats as fixed discount
        return -value
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






import requests

def create_ghl_contact_and_note(contact, quote):
    try:
        # Get token from the database
        credentials = GHLAuthCredentials.objects.first()
        token = credentials.access_token
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Version": "2021-07-28"
        }

        location_id = credentials.location_id
        search_query = contact.email or contact.phone_number
        if not search_query:
            print("No identifier to search GHL contact.")
            return

        # Step 1: Search for existing contact
        search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={search_query}"
        search_response = requests.get(search_url, headers=headers)

        if search_response.status_code != 200:
            print("Failed to search GHL contact:", search_response.text)
            return

        results = search_response.json().get("contacts", [])
        if results:
            # Contact exists, get the ID
            ghl_contact_id = results[0]["id"]
        else:
            # Create a new contact
            contact_payload = {
                "firstName": contact.first_name,
                "email": contact.email,
                "phone": contact.phone_number,
                "address1": contact.address,
                "locationId": location_id
            }

            contact_response = requests.post(
                "https://services.leadconnectorhq.com/contacts/",
                data=contact_payload,
                headers=headers
            )

            if contact_response.status_code not in [200, 201]:
                print("Failed to create contact in GHL:", contact_response.text)
                return

            ghl_contact_id = contact_response.json().get("contact", {}).get("id")

        # Step 2: Create comprehensive note for the contact
        note_sections = []
        
        # Header
        note_sections.append("🎯 NEW QUOTE GENERATED")
        note_sections.append("=" * 50)
        
        # Contact Information
        note_sections.append("\n📋 CONTACT INFORMATION:")
        note_sections.append(f"• Name: {contact.first_name}")
        note_sections.append(f"• Phone: {contact.phone_number}")
        note_sections.append(f"• Email: {contact.email}")
        note_sections.append(f"• Address: {contact.address}")

        
        # Service & Package Details
        note_sections.append(f"\n🔧 SERVICE DETAILS:")
        note_sections.append(f"• Service: {quote.service.name}")
        note_sections.append(f"• Service Description: {quote.service.description}")
        note_sections.append(f"• Package: {quote.package.name}")
        
        # # Package Features
        # try:
        #     package_features = quote.package.package_features.select_related('feature').filter(feature__is_active=True)
        #     if package_features.exists():
        #         note_sections.append(f"\n✅ PACKAGE FEATURES:")
        #         for pf in package_features:
        #             status_icon = "✓" if pf.is_included else "✗"
        #             feature_name = pf.feature.name if pf.feature else "Unknown Feature"
        #             note_sections.append(f"  {status_icon} {feature_name}")
        #             if pf.feature and pf.feature.description:
        #                 note_sections.append(f"    └ {pf.feature.description}")
        #     else:
        #         # Fallback: try to get features directly from the service
        #         service_features = quote.service.features.filter(is_active=True)
        #         if service_features.exists():
        #             note_sections.append(f"\n✅ SERVICE FEATURES:")
        #             for feature in service_features:
        #                 note_sections.append(f"  • {feature.name}")
        #                 if feature.description:
        #                     note_sections.append(f"    └ {feature.description}")
        # except Exception as e:
        #     print(f"Error loading package features: {e}")
        #     # Simple fallback
        #     note_sections.append(f"\n✅ PACKAGE: {quote.package.name}")
            # note_sections.append(f"  Base Price: ${quote.package.base_price}")
        
        # Question Answers
        question_answers = quote.question_answers.all()
        if question_answers.exists():
            note_sections.append(f"\n❓ CUSTOMER ANSWERS:")
            for qa in question_answers:
                note_sections.append(f"• Q: {qa.question.question_text}")
                
                if qa.question.question_type == 'yes_no':
                    answer = "Yes" if qa.yes_no_answer else "No"
                    note_sections.append(f"  A: {answer}")
                elif qa.question.question_type == 'options' and qa.selected_option:
                    note_sections.append(f"  A: {qa.selected_option.option_text}")
                
                # Show price impact if any
                if qa.price_adjustment and qa.price_adjustment != 0:
                    adjustment_sign = "+" if qa.price_adjustment > 0 else ""
                    note_sections.append(f"  💰 Price Impact: {adjustment_sign}${qa.price_adjustment}")
        
        # # Location & Distance Info
        # if quote.nearest_location:
        #     note_sections.append(f"\n📍 LOCATION DETAILS:")
        #     note_sections.append(f"• Nearest Service Location: {quote.nearest_location.name}")
        #     note_sections.append(f"• Location Address: {quote.nearest_location.address}")
        #     if quote.distance_to_location:
        #         note_sections.append(f"• Distance: {quote.distance_to_location} km")
        
        # Pricing Breakdown
        note_sections.append(f"\n💰 PRICING BREAKDOWN:")
        # note_sections.append(f"• Base Price: ${quote.base_price}")
        
        if quote.trip_surcharge and quote.trip_surcharge > 0:
            note_sections.append(f"• Trip Surcharge: +${quote.trip_surcharge}")
        
        if quote.question_adjustments and quote.question_adjustments != 0:
            adjustment_sign = "+" if quote.question_adjustments > 0 else ""
            note_sections.append(f"• Question Adjustments: {adjustment_sign}${quote.question_adjustments}")
        
        note_sections.append(f"• TOTAL PRICE: ${quote.total_price}")
        
        # Quote Meta Information
        note_sections.append(f"\n📊 QUOTE DETAILS:")
        # note_sections.append(f"• Quote ID: {quote.id}")
        note_sections.append(f"• Status: {quote.get_status_display()}")
        note_sections.append(f"• Created: {quote.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # if quote.expires_at:
        #     note_sections.append(f"• Expires: {quote.expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # # Call to Action
        # note_sections.append(f"\n🚀 NEXT STEPS:")
        # note_sections.append("• Follow up with customer within 24 hours")
        # note_sections.append("• Confirm service details and schedule")
        # note_sections.append("• Send formal quote if needed")
        
        # # Footer
        # note_sections.append(f"\n" + "=" * 50)
        # note_sections.append("Generated automatically by Quote System")
        
        # Join all sections
        note_body = "\n".join(note_sections)

        note_payload = {
            "body": note_body
        }

        note_response = requests.post(
            f"https://services.leadconnectorhq.com/contacts/{ghl_contact_id}/notes",
            json=note_payload,
            headers=headers
        )

        if note_response.status_code not in [200, 201]:
            print("Failed to create note in GHL:", note_response.text)
        else:
            print(f"Successfully created comprehensive note for contact {ghl_contact_id}")

    except Exception as e:
        print("Exception while syncing contact with GHL:", str(e))