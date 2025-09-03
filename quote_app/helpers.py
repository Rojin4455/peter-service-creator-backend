from accounts.models import GHLAuthCredentials

import requests
from decouple import config

def create_or_update_ghl_contact(submission, is_submit=False):
    try:
        credentials = GHLAuthCredentials.objects.first()
        token = credentials.access_token
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Version": "2021-07-28",
            "Content-Type": "application/json"
        }

        location_id = credentials.location_id
        results = []

        # Step 1: Determine search URL
        if submission.ghl_contact_id:
            search_url = f"https://services.leadconnectorhq.com/contacts/{submission.ghl_contact_id}"
        else:
            search_query = submission.customer_email or submission.customer_phone
            if not search_query:
                print("No identifier to search GHL contact.")
                return
            search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={search_query}"

        # Step 2: Fetch existing contact
        search_response = requests.get(search_url, headers=headers)
        if search_response.status_code != 200:
            print("Failed to search GHL contact:", search_response.text)
            return

        search_data = search_response.json()

        # Handle both cases: list of contacts or single contact
        if "contacts" in search_data and isinstance(search_data["contacts"], list):
            results = search_data["contacts"]
        elif "contact" in search_data and isinstance(search_data["contact"], dict):
            results = [search_data["contact"]]

        # --- Build custom fields payload ---
        # Booking/Quote link
        custom_fields = [{
            "id": "vWNjYOQajJAPtx2Hkq2e",
            "field_value": (
                f"{config('BASE_FRONTEND_URI')}/booking?submission_id={submission.id}"
                if not is_submit else
                f"{config('BASE_FRONTEND_URI')}/quote/details/{submission.id}"
            )
        }]

        # Quoted Date (use submission.updated_at or created_at or explicit expires_at)
        quoted_date_value = submission.created_at.strftime("%Y-%m-%d") if submission.created_at else None
        if quoted_date_value:
            custom_fields.append({
                "id": "1MfidSbDFjvs1vJ6kpKN",  # Quoted Date field
                "field_value": quoted_date_value
            })

        GHL_SERVICE_OPTIONS = {
            "Service 1": "Service 1",
            "Service 2": "Service 2",
            "Service 3": "Service 3",
            "Service 4": "Service 4",
            "Service 5": "Service 5",
            "Service 6": "Service 6",
            "Service 7": "Service 7",
            "Service 8": "Service 8",
            "Service 9": "Service 9",
            "Service 10": "Service 10",
        }

        # Quoted Services (collect names of all selected services)
        quoted_services = list(submission.selected_services.values_list("name", flat=True))
        if quoted_services:
            # Only keep services that exist in GHL picklist
            mapped_services = [GHL_SERVICE_OPTIONS[s] for s in quoted_services if s in GHL_SERVICE_OPTIONS]
            if mapped_services:
                custom_fields.append({
                    "id": "KdMeqRIzPqspibt3aRIh",  # Quoted Services field
                    "field_value": mapped_services  # Pass as list of labels
                })

        if submission.size_range:
            min_sqft = submission.size_range.min_sqft
            max_sqft = submission.size_range.max_sqft
            house_size_value = f"{min_sqft} - {max_sqft}"
            custom_fields.append({
                "id": "MqkYwdgeT2Kk9EgFa5bn",  # House Size field
                "field_value": house_size_value
            })

        # Step 3: Update or create
        if results:
            ghl_contact_id = results[0]["id"]

            existing_tags = results[0].get("tags", [])
            if isinstance(existing_tags, str):
                existing_tags = [existing_tags]

            new_tag = "quote_requested" if not is_submit else "quote_accepted"
            updated_tags = list(set(existing_tags + [new_tag]))

            contact_payload = {
                "firstName": submission.first_name,
                "address1": submission.street_address,
                "customFields": custom_fields,
                "tags": updated_tags
            }

            contact_response = requests.put(
                f"https://services.leadconnectorhq.com/contacts/{ghl_contact_id}",
                json=contact_payload,
                headers=headers
            )

        else:
            contact_payload = {
                "firstName": submission.first_name,
                "email": submission.customer_email,
                "phone": submission.customer_phone,
                "address1": submission.street_address,
                "locationId": location_id,
                "customFields": custom_fields,
                "tags": ["quote_requested"]
            }
            contact_response = requests.post(
                "https://services.leadconnectorhq.com/contacts/",
                json=contact_payload,
                headers=headers
            )

        if contact_response.status_code not in [200, 201]:
            print("Failed to create/update contact in GHL:", contact_response.text)
            return

        ghl_contact_id = contact_response.json().get("contact", {}).get("id")
        if ghl_contact_id:
            submission.ghl_contact_id = ghl_contact_id
            submission.save()
            print(f"Contact synced successfully: {ghl_contact_id}")

    except Exception as e:
        print(f"Error syncing contact: {e}")


