import re

ALIASES = {
    'fullname': 'full_name', 'name': 'full_name', 'first_name': 'first_name', 'last_name': 'last_name',
    'email_address': 'email', 'emailaddress': 'email',
    'phone_number': 'phone', 'phonenumber': 'phone', 'phone_no': 'phone',
    'mobile_number': 'mobile', 'mobile_phone': 'mobile',
    'company': 'company_name', 'companyname': 'company_name',
    'jobtitle': 'job_title', 'jobposition': 'job_title', 'job_position': 'job_title',
    'postal_code': 'zip', 'zipcode': 'zip', 'zip_code': 'zip',
    'street_address': 'street', 'address': 'street',
    'الاسم_بالكامل': 'full_name', 'الاسم_الكامل': 'full_name', 'الاسم': 'full_name',
    'رقم_الهاتف': 'phone', 'الهاتف': 'phone', 'رقم_الجوال': 'mobile', 'الجوال': 'mobile',
    'اسم_الشركة': 'company_name', 'الشركة': 'company_name',
    'المسمى_الوظيفي': 'job_title', 'المسمي_الوظيفي': 'job_title', 'الوظيفة': 'job_title',
    'المدينة': 'city', 'المدينه': 'city',
    'البريد_الإلكتروني': 'email', 'البريد_الالكتروني': 'email', 'ايميل': 'email',
}

DEFAULT_FIELDS = {
    'full_name': 'contact_name', 'email': 'email_from', 'phone': 'phone', 'mobile': 'mobile',
    'company_name': 'partner_name', 'job_title': 'function', 'street': 'street', 'city': 'city', 'zip': 'zip',
}

def normalize_key(key):
    key = str(key or '').strip().lower()
    key = re.sub(r'[\s\-./]+', '_', key)
    key = re.sub(r'[^\w]+', '', key, flags=re.UNICODE)
    key = re.sub(r'_+', '_', key).strip('_')
    return ALIASES.get(key, key)

def default_odoo_field(key):
    return DEFAULT_FIELDS.get(normalize_key(key))
