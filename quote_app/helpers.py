from accounts.models import GHLAuthCredentials

import requests
from decouple import config

def add_quote_drafted_tag_to_ghl(submission):
    """Add 'quote drafted' tag to GHL contact when submission is created"""
    try:
        credentials = GHLAuthCredentials.objects.first()
        if not credentials:
            print("No GHL credentials found")
            return
        
        token = credentials.access_token
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Version": "2021-07-28",
            "Content-Type": "application/json"
        }

        location_id = credentials.location_id
        results = []

        # Search for existing contact
        if submission.ghl_contact_id:
            # If we have a GHL contact ID, fetch directly
            search_url = f"https://services.leadconnectorhq.com/contacts/{submission.ghl_contact_id}"
            search_response = requests.get(search_url, headers=headers)
            if search_response.status_code == 200:
                search_data = search_response.json()
                if "contact" in search_data and isinstance(search_data["contact"], dict):
                    results = [search_data["contact"]]
        else:
            # Search by email first (if available)
            if submission.customer_email:
                search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={submission.customer_email}"
                search_response = requests.get(search_url, headers=headers)
                if search_response.status_code == 200:
                    search_data = search_response.json()
                    if "contacts" in search_data and isinstance(search_data["contacts"], list):
                        results = search_data["contacts"]
                    elif "contact" in search_data and isinstance(search_data["contact"], dict):
                        results = [search_data["contact"]]
            
            # If no results from email search, search by phone (if available)
            if not results and submission.customer_phone:
                search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={submission.customer_phone}"
                search_response = requests.get(search_url, headers=headers)
                if search_response.status_code == 200:
                    search_data = search_response.json()
                    if "contacts" in search_data and isinstance(search_data["contacts"], list):
                        results = search_data["contacts"]
                    elif "contact" in search_data and isinstance(search_data["contact"], dict):
                        results = [search_data["contact"]]

        # Update or create contact with "quote drafted" tag
        if results:
            ghl_contact_id = results[0]["id"]
            existing_tags = results[0].get("tags", [])
            if isinstance(existing_tags, str):
                existing_tags = [existing_tags]
            
            # Add "quote drafted" tag if not already present
            if "quote drafted" not in existing_tags:
                updated_tags = list(set(existing_tags + ["quote drafted"]))
                
                contact_payload = {
                    "tags": updated_tags
                }
                
                contact_response = requests.put(
                    f"https://services.leadconnectorhq.com/contacts/{ghl_contact_id}",
                    json=contact_payload,
                    headers=headers
                )
                
                if contact_response.status_code in [200, 201]:
                    submission.ghl_contact_id = ghl_contact_id
                    submission.save()
                    print(f"Added 'quote drafted' tag to contact: {ghl_contact_id}")
        else:
            # No existing contact found, create new one with "quote drafted" tag
            contact_payload = {
                "firstName": submission.first_name,
                "lastName": submission.last_name,
                "email": submission.customer_email,
                "phone": submission.customer_phone,
                "address1": submission.street_address,
                "locationId": location_id,
                "tags": ["quote drafted"]
            }
            
            contact_response = requests.post(
                "https://services.leadconnectorhq.com/contacts/",
                json=contact_payload,
                headers=headers
            )
            
            if contact_response.status_code in [200, 201]:
                ghl_contact_id = contact_response.json().get("contact", {}).get("id")
                if ghl_contact_id:
                    submission.ghl_contact_id = ghl_contact_id
                    submission.save()
                    print(f"Created new contact with 'quote drafted' tag: {ghl_contact_id}")
            elif contact_response.status_code == 400:
                # Handle duplicate contact error
                error_data = contact_response.json()
                if "duplicated contacts" in error_data.get("message", "").lower():
                    contact_id_from_error = error_data.get("meta", {}).get("contactId")
                    if contact_id_from_error:
                        # Fetch and update existing contact
                        fetch_url = f"https://services.leadconnectorhq.com/contacts/{contact_id_from_error}"
                        fetch_response = requests.get(fetch_url, headers=headers)
                        if fetch_response.status_code == 200:
                            existing_tags = fetch_response.json().get("contact", {}).get("tags", [])
                            if isinstance(existing_tags, str):
                                existing_tags = [existing_tags]
                            
                            if "quote drafted" not in existing_tags:
                                updated_tags = list(set(existing_tags + ["quote drafted"]))
                                update_payload = {"tags": updated_tags}
                                
                                update_response = requests.put(
                                    f"https://services.leadconnectorhq.com/contacts/{contact_id_from_error}",
                                    json=update_payload,
                                    headers=headers
                                )
                                
                                if update_response.status_code in [200, 201]:
                                    submission.ghl_contact_id = contact_id_from_error
                                    submission.save()
                                    print(f"Added 'quote drafted' tag to existing contact: {contact_id_from_error}")

    except Exception as e:
        print(f"Error adding 'quote drafted' tag to GHL: {e}")

def create_or_update_ghl_contact(submission, is_submit=False, is_declined=False):
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
            # If we have a GHL contact ID, fetch directly
            search_url = f"https://services.leadconnectorhq.com/contacts/{submission.ghl_contact_id}"
            search_response = requests.get(search_url, headers=headers)
            if search_response.status_code == 200:
                search_data = search_response.json()
                if "contact" in search_data and isinstance(search_data["contact"], dict):
                    results = [search_data["contact"]]
        else:
            # Step 2: Search by email first (if available)
            if submission.customer_email:
                search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={submission.customer_email}"
                search_response = requests.get(search_url, headers=headers)
                if search_response.status_code == 200:
                    search_data = search_response.json()
                    # Handle both cases: list of contacts or single contact
                    if "contacts" in search_data and isinstance(search_data["contacts"], list):
                        results = search_data["contacts"]
                    elif "contact" in search_data and isinstance(search_data["contact"], dict):
                        results = [search_data["contact"]]
            
            # Step 3: If no results from email search, search by phone (if available)
            if not results and submission.customer_phone:
                search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={submission.customer_phone}"
                search_response = requests.get(search_url, headers=headers)
                if search_response.status_code == 200:
                    search_data = search_response.json()
                    # Handle both cases: list of contacts or single contact
                    if "contacts" in search_data and isinstance(search_data["contacts"], list):
                        results = search_data["contacts"]
                    elif "contact" in search_data and isinstance(search_data["contact"], dict):
                        results = [search_data["contact"]]
            
            # If still no results and no identifiers, return early
            if not results and not submission.customer_email and not submission.customer_phone:
                print("No identifier (email or phone) to search GHL contact.")
                return
            
            # Log search results
            if results:
                print(f"Found existing GHL contact by {'email' if submission.customer_email and not submission.customer_phone else 'phone' if submission.customer_phone else 'identifier'}: {results[0].get('id')}")
            else:
                print("No existing GHL contact found, will create new one.")

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

        url = f"{config('BASE_FRONTEND_URI')}/booking?submission_id={submission.id}" if not is_submit else f"{config('BASE_FRONTEND_URI')}/quote/details/{submission.id}"

        submission.quote_url=url
        submission.save()


        # Quoted Date (use submission.updated_at or created_at or explicit expires_at)
        quoted_date_value = submission.created_at.strftime("%Y-%m-%d") if submission.created_at else None
        if quoted_date_value:
            custom_fields.append({
                "id": "1MfidSbDFjvs1vJ6kpKN",  # Quote Declined Date
                "field_value": quoted_date_value
            })

        custom_fields.append({
            "id":"7l7boV5mtUDWnhIocfae",
            "field_value":str(submission.final_total)
        })

        

        if is_declined:
            quoted_date_value = submission.declined_at.strftime("%Y-%m-%d") if submission.declined_at else None
            custom_fields.append({
                "id": "v2wQQet3CDiIRQVA0h40",  # Quoted Date field
                "field_value": quoted_date_value
            })


        # Quoted Services (collect names of all selected services)
        quoted_services = list(submission.selected_services.values_list("name", flat=True))
        if quoted_services:
            services_string = ", ".join(quoted_services)  # e.g. "Service 1, Service 3, Service 7"
            custom_fields.append({
                "id": "rRNtL51RsGoGDCAq3YrN",  # Selected Services custom field (TEXT)
                "field_value": services_string
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

            # Remove "quote drafted" tag if it exists
            existing_tags = [tag for tag in existing_tags if tag != "quote drafted"]

            # Determine new tags based on status
            new_tags = ["quote_requested" if not is_submit else "quote_accepted"]

            if is_declined:
                new_tags.append("quote_declined")  # keep naming consistent

            updated_tags = list(set(existing_tags + new_tags))

            contact_payload = {
                "firstName": submission.first_name,
                "lastName": submission.last_name,
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
            # No existing contact found, create new one
            # Remove "quote drafted" if it exists (shouldn't happen for new contact, but just in case)
            new_tags = ["quote_requested" if not is_submit else "quote_accepted"]
            if is_declined:
                new_tags.append("quote_declined")
            
            contact_payload = {
                "firstName": submission.first_name,
                "lastName": submission.last_name,
                "email": submission.customer_email,
                "phone": submission.customer_phone,
                "address1": submission.street_address,
                "locationId": location_id,
                "customFields": custom_fields,
                "tags": new_tags
            }
            contact_response = requests.post(
                "https://services.leadconnectorhq.com/contacts/",
                json=contact_payload,
                headers=headers
            )
            
            # Handle duplicate contact error - try to find and update existing contact
            if contact_response.status_code == 400:
                error_data = contact_response.json()
                if "duplicated contacts" in error_data.get("message", "").lower():
                    # Extract contact ID from error if available
                    contact_id_from_error = error_data.get("meta", {}).get("contactId")
                    if contact_id_from_error:
                        print(f"Duplicate contact detected. Updating existing contact: {contact_id_from_error}")
                        # Fetch the existing contact
                        fetch_url = f"https://services.leadconnectorhq.com/contacts/{contact_id_from_error}"
                        fetch_response = requests.get(fetch_url, headers=headers)
                        if fetch_response.status_code == 200:
                            # Update the existing contact instead
                            existing_tags = fetch_response.json().get("contact", {}).get("tags", [])
                            if isinstance(existing_tags, str):
                                existing_tags = [existing_tags]
                            
                            # Remove "quote drafted" tag if it exists
                            existing_tags = [tag for tag in existing_tags if tag != "quote drafted"]
                            
                            new_tags = ["quote_requested" if not is_submit else "quote_accepted"]
                            if is_declined:
                                new_tags.append("quote_declined")
                            
                            updated_tags = list(set(existing_tags + new_tags))
                            
                            update_payload = {
                                "firstName": submission.first_name,
                                "lastName": submission.last_name,
                                "address1": submission.street_address,
                                "customFields": custom_fields,
                                "tags": updated_tags
                            }
                            
                            # Update email/phone if they're different
                            existing_contact = fetch_response.json().get("contact", {})
                            if submission.customer_email and existing_contact.get("email") != submission.customer_email:
                                update_payload["email"] = submission.customer_email
                            if submission.customer_phone and existing_contact.get("phone") != submission.customer_phone:
                                update_payload["phone"] = submission.customer_phone
                            
                            contact_response = requests.put(
                                f"https://services.leadconnectorhq.com/contacts/{contact_id_from_error}",
                                json=update_payload,
                                headers=headers
                            )
                            
                            if contact_response.status_code in [200, 201]:
                                submission.ghl_contact_id = contact_id_from_error
                                submission.save()
                                print(f"Contact updated successfully after duplicate detection: {contact_id_from_error}")
                                return
                    else:
                        print("Duplicate contact error but no contact ID provided in error response")
                        return

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


