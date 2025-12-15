# Admin Management API Documentation

## Overview
This document describes the Admin Management API endpoints that allow super admins to manage other admin users in the system. The system includes a permission-based access control system where super admins can control which sections of the admin panel each admin user can access.

## Setup Instructions

### 1. Run Migration
After implementing the changes, you need to create and run a migration:

```bash
# Activate virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Create migration
python manage.py makemigrations service_app

# Run migration
python manage.py migrate
```

### 2. Create Super Admin
To create the first super admin, you can use the management command:

```bash
python manage.py create_admin --username superadmin --email superadmin@example.com --password SuperAdmin123!
```

Then, manually set `is_super_admin=True` in the database or Django shell:

```python
from service_app.models import User
user = User.objects.get(username='superadmin')
user.is_super_admin = True
user.save()
```

Or use Django shell:
```bash
python manage.py shell
>>> from service_app.models import User
>>> user = User.objects.get(username='superadmin')
>>> user.is_super_admin = True
>>> user.save()
```

---

## API Endpoints

### Base URL
All endpoints are prefixed with: `/api/service/`

### Authentication
All endpoints require authentication using JWT tokens. Include the token in the Authorization header:
```
Authorization: Bearer <your_jwt_token>
```

**Note:** Only users with `is_super_admin=True` can access these endpoints.

---

## 1. List All Admins

**Endpoint:** `GET /api/service/admins/`

**Description:** Retrieve a list of all admin users (excluding super admins).

**Permissions:** Super Admin only

**Response:**
```json
[
  {
    "id": 2,
    "username": "admin1",
    "email": "admin1@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "is_admin": true,
    "is_super_admin": false,
    "is_active": true,
    "created_by_username": "superadmin",
    "created_at": "2024-01-15T10:30:00Z",
    "last_login": "2024-01-20T14:22:00Z",
    "can_access_dashboard": true,
    "can_access_reports": true,
    "can_access_service_management": true,
    "can_access_location": false,
    "can_access_house_size_management": false,
    "can_access_addon_service": true,
    "can_access_coupon": false,
    "can_access_on_the_go_calculator": false
  },
  {
    "id": 3,
    "username": "admin2",
    "email": "admin2@example.com",
    "first_name": "Jane",
    "last_name": "Smith",
    "is_admin": true,
    "is_super_admin": false,
    "is_active": false,
    "created_by_username": "superadmin",
    "created_at": "2024-01-16T09:15:00Z",
    "last_login": null,
    "can_access_dashboard": true,
    "can_access_reports": false,
    "can_access_service_management": false,
    "can_access_location": true,
    "can_access_house_size_management": true,
    "can_access_addon_service": false,
    "can_access_coupon": false,
    "can_access_on_the_go_calculator": false
  }
]
```

---

## 2. Create New Admin

**Endpoint:** `POST /api/service/admins/`

**Description:** Create a new admin user.

**Permissions:** Super Admin only

**Request Body:**
```json
{
  "username": "newadmin",
  "email": "newadmin@example.com",
  "password": "SecurePassword123!",
  "first_name": "New",
  "last_name": "Admin",
  "can_access_dashboard": true,
  "can_access_reports": true,
  "can_access_service_management": false,
  "can_access_location": false,
  "can_access_house_size_management": false,
  "can_access_addon_service": false,
  "can_access_coupon": false,
  "can_access_on_the_go_calculator": false
}
```

**Required Fields:**
- `username` (string): Unique username
- `email` (string): Valid email address (must be unique)
- `password` (string): Minimum 8 characters

**Optional Fields:**
- `first_name` (string)
- `last_name` (string)
- `can_access_dashboard` (boolean): Access to dashboard section (default: `true`)
- `can_access_reports` (boolean): Access to reports section (default: `false`)
- `can_access_service_management` (boolean): Access to service management section (default: `false`)
- `can_access_location` (boolean): Access to location management section (default: `false`)
- `can_access_house_size_management` (boolean): Access to house size management section (default: `false`)
- `can_access_addon_service` (boolean): Access to add-on service management section (default: `false`)
- `can_access_coupon` (boolean): Access to coupon section (default: `false`)
- `can_access_on_the_go_calculator` (boolean): Access to on-the-go calculator section (default: `false`)

**Response (201 Created):**
```json
{
  "id": 4,
  "username": "newadmin",
  "email": "newadmin@example.com",
  "first_name": "New",
  "last_name": "Admin",
  "is_admin": true,
  "is_super_admin": false,
  "is_active": true,
  "created_by": 1,
  "created_at": "2024-01-21T12:00:00Z",
  "can_access_dashboard": true,
  "can_access_reports": true,
  "can_access_service_management": false,
  "can_access_location": false,
  "can_access_house_size_management": false,
  "can_access_addon_service": false,
  "can_access_coupon": false,
  "can_access_on_the_go_calculator": false
}
```

**Error Responses:**

**400 Bad Request - Email already exists:**
```json
{
  "email": ["A user with this email already exists."]
}
```

**400 Bad Request - Username already exists:**
```json
{
  "username": ["A user with this username already exists."]
}
```

**400 Bad Request - Password too short:**
```json
{
  "password": ["Ensure this field has at least 8 characters."]
}
```

**403 Forbidden - Not a super admin:**
```json
{
  "detail": "You do not have permission to perform this action."
}
```

---

## 3. Get Admin Details

**Endpoint:** `GET /api/service/admins/<id>/`

**Description:** Retrieve details of a specific admin user.

**Permissions:** Super Admin only

**Response (200 OK):**
```json
{
  "id": 2,
  "username": "admin1",
  "email": "admin1@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "is_admin": true,
  "is_super_admin": false,
  "is_active": true,
  "created_by_username": "superadmin",
  "created_at": "2024-01-15T10:30:00Z",
  "last_login": "2024-01-20T14:22:00Z",
  "can_access_dashboard": true,
  "can_access_reports": true,
  "can_access_service_management": true,
  "can_access_location": false,
  "can_access_house_size_management": false,
  "can_access_addon_service": true,
  "can_access_coupon": false,
  "can_access_on_the_go_calculator": false
}
```

**Error Response:**

**404 Not Found:**
```json
{
  "detail": "Not found."
}
```

---

## 4. Update Admin

**Endpoint:** `PUT /api/service/admins/<id>/` or `PATCH /api/service/admins/<id>/`

**Description:** Update an admin user's information including username, email, first_name, last_name, is_active, and permission fields.

**Permissions:** Super Admin only

**Request Body (PUT - all fields required, PATCH - partial update):**
```json
{
  "username": "updatedadmin",
  "email": "updatedadmin@example.com",
  "first_name": "Updated",
  "last_name": "Admin",
  "is_active": true,
  "can_access_dashboard": true,
  "can_access_reports": true,
  "can_access_service_management": true,
  "can_access_location": true,
  "can_access_house_size_management": false,
  "can_access_addon_service": true,
  "can_access_coupon": false,
  "can_access_on_the_go_calculator": false
}
```

**Updatable Fields:**
- `username` (string): Unique username
- `email` (string): Valid email address (must be unique)
- `first_name` (string)
- `last_name` (string)
- `is_active` (boolean): Whether the user account is active
- `password` (string): New password (minimum 8 characters) - optional
- `can_access_dashboard` (boolean): Access to dashboard section
- `can_access_reports` (boolean): Access to reports section
- `can_access_service_management` (boolean): Access to service management section
- `can_access_location` (boolean): Access to location management section
- `can_access_house_size_management` (boolean): Access to house size management section
- `can_access_addon_service` (boolean): Access to add-on service management section
- `can_access_coupon` (boolean): Access to coupon section
- `can_access_on_the_go_calculator` (boolean): Access to on-the-go calculator section

**Response (200 OK):**
```json
{
  "id": 2,
  "username": "updatedadmin",
  "email": "updatedadmin@example.com",
  "first_name": "Updated",
  "last_name": "Admin",
  "is_admin": true,
  "is_super_admin": false,
  "is_active": true,
  "created_by_username": "superadmin",
  "created_at": "2024-01-15T10:30:00Z",
  "last_login": "2024-01-20T14:22:00Z",
  "can_access_dashboard": true,
  "can_access_reports": true,
  "can_access_service_management": true,
  "can_access_location": true,
  "can_access_house_size_management": false,
  "can_access_addon_service": true,
  "can_access_coupon": false,
  "can_access_on_the_go_calculator": false
}
```

---

## 5. Block Admin

**Endpoint:** `POST /api/service/admins/<id>/block/`

**Description:** Block an admin user (set `is_active=False`). Blocked admins cannot log in.

**Permissions:** Super Admin only

**Request Body:** Empty body or `{}`

**Response (200 OK):**
```json
{
  "message": "Admin user 'admin1' has been blocked.",
  "user": {
    "id": 2,
    "username": "admin1",
    "email": "admin1@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "is_admin": true,
    "is_super_admin": false,
    "is_active": false,
    "created_by_username": "superadmin",
    "created_at": "2024-01-15T10:30:00Z",
    "last_login": "2024-01-20T14:22:00Z",
    "can_access_dashboard": true,
    "can_access_reports": true,
    "can_access_service_management": true,
    "can_access_location": false,
    "can_access_house_size_management": false,
    "can_access_addon_service": true,
    "can_access_coupon": false,
    "can_access_on_the_go_calculator": false
  }
}
```

**Error Responses:**

**400 Bad Request - Cannot block yourself:**
```json
{
  "error": "You cannot block your own account."
}
```

**404 Not Found:**
```json
{
  "error": "Admin user not found."
}
```

---

## 6. Unblock Admin

**Endpoint:** `POST /api/service/admins/<id>/unblock/`

**Description:** Unblock an admin user (set `is_active=True`). Unblocked admins can log in again.

**Permissions:** Super Admin only

**Request Body:** Empty body or `{}`

**Response (200 OK):**
```json
{
  "message": "Admin user 'admin1' has been unblocked.",
  "user": {
    "id": 2,
    "username": "admin1",
    "email": "admin1@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "is_admin": true,
    "is_super_admin": false,
    "is_active": true,
    "created_by_username": "superadmin",
    "created_at": "2024-01-15T10:30:00Z",
    "last_login": "2024-01-20T14:22:00Z",
    "can_access_dashboard": true,
    "can_access_reports": true,
    "can_access_service_management": true,
    "can_access_location": false,
    "can_access_house_size_management": false,
    "can_access_addon_service": true,
    "can_access_coupon": false,
    "can_access_on_the_go_calculator": false
  }
}
```

**Error Response:**

**404 Not Found:**
```json
{
  "error": "Admin user not found."
}
```

---

## 7. Change Admin Password

**Endpoint:** `POST /api/service/admins/<id>/change-password/`

**Description:** Change an admin user's password.

**Permissions:** Super Admin only

**Request Body:**
```json
{
  "password": "NewSecurePassword123!"
}
```

**Required Fields:**
- `password` (string): New password (minimum 8 characters)

**Response (200 OK):**
```json
{
  "message": "Password for admin user 'admin1' has been changed successfully."
}
```

**Error Responses:**

**400 Bad Request - Password required:**
```json
{
  "error": "Password is required."
}
```

**400 Bad Request - Password too short:**
```json
{
  "error": "Password must be at least 8 characters long."
}
```

**404 Not Found:**
```json
{
  "error": "Admin user not found."
}
```

---

## 8. Delete Admin

**Endpoint:** `DELETE /api/service/admins/<id>/`

**Description:** Delete an admin user permanently.

**Permissions:** Super Admin only

**Response (204 No Content):** Empty response body

**Error Response:**

**400 Bad Request - Cannot delete yourself:**
```json
{
  "error": "You cannot delete your own account."
}
```

---

## Permission System

The admin panel uses a permission-based access control system where super admins can control which sections each admin user can access. The following permission fields are available:

### Available Permissions

1. **`can_access_dashboard`** (default: `true`)
   - Controls access to the dashboard section
   - All admins have dashboard access by default

2. **`can_access_reports`** (default: `false`)
   - Controls access to the reports/analytics section

3. **`can_access_service_management`** (default: `false`)
   - Controls access to service management section
   - Includes creating, editing, and managing services, packages, questions, and features

4. **`can_access_location`** (default: `false`)
   - Controls access to location management section
   - Includes creating, editing, and managing locations

5. **`can_access_house_size_management`** (default: `false`)
   - Controls access to house size management section
   - Includes managing global size packages and size ranges

6. **`can_access_addon_service`** (default: `false`)
   - Controls access to add-on service management section
   - Includes creating, editing, and managing add-on services

7. **`can_access_coupon`** (default: `false`)
   - Controls access to coupon management section
   - Includes creating, editing, and managing coupons

8. **`can_access_on_the_go_calculator`** (default: `false`)
   - Controls access to on-the-go calculator section

### Setting Permissions

Permissions can be set when:
- **Creating a new admin**: Include permission fields in the POST request body
- **Updating an admin**: Include permission fields in the PATCH/PUT request body

**Example - Creating admin with specific permissions:**
```json
{
  "username": "limitedadmin",
  "email": "limited@example.com",
  "password": "SecurePassword123!",
  "can_access_dashboard": true,
  "can_access_reports": true,
  "can_access_service_management": false,
  "can_access_location": true,
  "can_access_house_size_management": false,
  "can_access_addon_service": false,
  "can_access_coupon": false,
  "can_access_on_the_go_calculator": false
}
```

**Example - Updating permissions only:**
```json
{
  "can_access_reports": true,
  "can_access_service_management": true
}
```

### Frontend Implementation

The frontend should:
1. Check user permissions from the user profile/response
2. Conditionally show/hide admin panel sections based on permission fields
3. Hide navigation items and routes for sections the user doesn't have access to
4. Show appropriate error messages if user tries to access restricted sections

**Example Frontend Check:**
```javascript
// Check if user can access reports section
if (user.can_access_reports) {
  // Show reports navigation item and allow access
} else {
  // Hide reports navigation item
}
```

---

## Security Features

1. **Super Admin Only Access:** All endpoints are protected by `IsSuperAdminPermission`
2. **Self-Protection:** Super admins cannot block or delete themselves
3. **Password Validation:** Minimum 8 characters required
4. **Unique Constraints:** Username and email must be unique
5. **Audit Trail:** `created_by` field tracks who created each admin

---

## Example cURL Requests

### 1. List All Admins
```bash
curl -X GET http://localhost:8000/api/service/admins/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### 2. Create New Admin
```bash
curl -X POST http://localhost:8000/api/service/admins/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "newadmin",
    "email": "newadmin@example.com",
    "password": "SecurePassword123!",
    "first_name": "New",
    "last_name": "Admin",
    "can_access_dashboard": true,
    "can_access_reports": true,
    "can_access_service_management": false,
    "can_access_location": false,
    "can_access_house_size_management": false,
    "can_access_addon_service": false,
    "can_access_coupon": false,
    "can_access_on_the_go_calculator": false
  }'
```

### 3. Block Admin
```bash
curl -X POST http://localhost:8000/api/service/admins/2/block/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json"
```

### 4. Unblock Admin
```bash
curl -X POST http://localhost:8000/api/service/admins/2/unblock/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json"
```

### 5. Change Password
```bash
curl -X POST http://localhost:8000/api/service/admins/2/change-password/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "password": "NewSecurePassword123!"
  }'
```

### 6. Update Admin
```bash
curl -X PATCH http://localhost:8000/api/service/admins/2/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "Updated",
    "is_active": true,
    "can_access_reports": true,
    "can_access_service_management": true
  }'
```

### 8. Update Admin Permissions Only
```bash
curl -X PATCH http://localhost:8000/api/service/admins/2/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "can_access_dashboard": true,
    "can_access_reports": true,
    "can_access_service_management": true,
    "can_access_location": false,
    "can_access_house_size_management": false,
    "can_access_addon_service": true,
    "can_access_coupon": false,
    "can_access_on_the_go_calculator": false
  }'
```

### 9. Delete Admin
```bash
curl -X DELETE http://localhost:8000/api/service/admins/2/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

---

## Frontend Integration Notes

1. **Permission Check:** Before showing admin management UI, verify the logged-in user has `is_super_admin: true`
2. **Password Field:** Use password input type with minimum length validation
3. **Email Validation:** Validate email format on frontend before submission
4. **Confirmation Dialogs:** Show confirmation before blocking/deleting admins
5. **Success/Error Messages:** Display appropriate messages after each operation
6. **Permission-Based UI:** 
   - Check user permission fields to conditionally show/hide admin panel sections
   - Hide navigation items for sections the user doesn't have access to
   - Implement route guards to prevent access to restricted sections
   - Example: `if (user.can_access_reports) { showReportsSection(); }`
7. **Permission Management UI:**
   - When creating/editing admins, provide checkboxes or toggles for each permission field
   - Show current permissions when viewing admin details
   - Allow super admins to update permissions independently of other user fields

---

## Database Schema Changes

The following fields were added to the `User` model:

### Core Admin Fields
- `is_super_admin` (BooleanField): Indicates if user is a super admin
- `created_by` (ForeignKey): Reference to the admin who created this user

### Permission Fields (All BooleanField, default values shown)
- `can_access_dashboard` (default: `true`): Access to dashboard section
- `can_access_reports` (default: `false`): Access to reports section
- `can_access_service_management` (default: `false`): Access to service management section
- `can_access_location` (default: `false`): Access to location management section
- `can_access_house_size_management` (default: `false`): Access to house size management section
- `can_access_addon_service` (default: `false`): Access to add-on service management section
- `can_access_coupon` (default: `false`): Access to coupon section
- `can_access_on_the_go_calculator` (default: `false`): Access to on-the-go calculator section

**Note:** Super admins have full access to all sections regardless of permission field values. Permission fields only apply to regular admin users.

Make sure to run migrations after implementing these changes:

```bash
python manage.py makemigrations service_app --name add_user_permission_fields
python manage.py migrate
```

