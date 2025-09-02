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

        # Common payload fields
        custom_fields = [{
            "id": "vWNjYOQajJAPtx2Hkq2e",
            "field_value": f"{config("BASE_FRONTEND_URI")}/booking?submission_id={submission.id}" if not is_submit else f"{config("BASE_FRONTEND_URI")}/quote/details/{submission.id}"
        }]

        # Step 3: Update or create
        if results:
            ghl_contact_id = results[0]["id"]

            # Normalize tags to always be a list
            existing_tags = results[0].get("tags", [])
            if isinstance(existing_tags, str):
                existing_tags = [existing_tags]

            # Add new tag without duplication
            if is_submit:
                new_tag = "quote_requested"
            else:
                new_tag = "quote_accepted"

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
                "tags":["quote_requested"]
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

