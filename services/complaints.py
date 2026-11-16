"""Issue #2: Complaint schema and validation."""
MAX_TITLE = 120
MAX_DESCRIPTION = 2000
SEVERITIES = ("Low", "Medium", "High", "Critical")
MAX_IMAGES = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_SIGNATURES = {b"\xff\xd8\xff": ".jpg", b"\x89PNG\r\n\x1a\n": ".png"}


def image_extension(head: bytes):
    for sig, ext in IMAGE_SIGNATURES.items():
        if head.startswith(sig):
            return ext
    return None


def validate(form, images, categories):
    """Return (cleaned_fields, errors). `images` is a list of (filename, bytes)."""
    errors = {}
    raw_title, raw_description = form.get("title", ""), form.get("description", "")
    raw_severity, raw_category = form.get("severity", ""), form.get("category", "")
    for key, value in (("title", raw_title), ("description", raw_description),
                       ("severity", raw_severity), ("category", raw_category)):
        if value is not None and not isinstance(value, str):
            errors[key] = "Must be text"
    title = raw_title.strip() if isinstance(raw_title, str) else ""
    description = raw_description.strip() if isinstance(raw_description, str) else ""
    severity = raw_severity.strip().title() if isinstance(raw_severity, str) else ""
    category = (raw_category.strip() or None) if isinstance(raw_category, str) else None

    if not title:
        errors["title"] = "Title is required"
    elif len(title) > MAX_TITLE:
        errors["title"] = f"Title must be at most {MAX_TITLE} characters"
    if not description:
        errors["description"] = "Description is required"
    elif len(description) > MAX_DESCRIPTION:
        errors["description"] = f"Description must be at most {MAX_DESCRIPTION} characters"
    if severity not in SEVERITIES:
        errors["severity"] = f"Severity must be one of {', '.join(SEVERITIES)}"
    if category and category not in categories:
        errors["category"] = "Invalid category"

    location = None
    lat, lng = form.get("latitude"), form.get("longitude")
    if lat not in (None, "") or lng not in (None, ""):
        try:
            lat, lng = float(lat), float(lng)
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError
            location = {"latitude": lat, "longitude": lng}
        except (TypeError, ValueError):
            errors["location"] = "GPS coordinates are invalid"

    if len(images) > MAX_IMAGES:
        errors["images"] = f"At most {MAX_IMAGES} images are allowed"
    else:
        for name, data in images:
            if len(data) > MAX_IMAGE_BYTES:
                errors["images"] = f"{name} exceeds the 5 MB limit"
                break
            if not image_extension(data[:8]):
                errors["images"] = f"{name} is not a JPEG or PNG image"
                break

    cleaned = {"title": title, "description": description, "severity": severity,
               "category": category, "location": location, "zone": (form.get("zone") or "").strip() or None}
    return cleaned, errors
