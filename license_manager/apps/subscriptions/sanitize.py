import bleach


def sanitize_html(html_content):
    """
    Sanitize HTML content to allow only safe tags and attributes,
    while disallowing JavaScript and unsafe protocols.
    """
    # Define allowed tags and attributes
    allowed_tags = bleach.ALLOWED_TAGS  # Allow all standard HTML tags
    allowed_attrs = {"*": ["className", "class", "style", "id"]}

    # Clean the HTML content
    sanitized_content = bleach.clean(
        html_content,
        tags=allowed_tags,
        attributes=allowed_attrs,
        strip=True,  # Strip disallowed tags completely
        protocols=["http", "https"],  # Only allow http and https URLs
    )

    # Use bleach.linkify to ensure no javascript: links in <a> tags
    sanitized_content = bleach.linkify(
        sanitized_content,
        callbacks=[
            bleach.callbacks.nofollow
        ],  # Apply 'nofollow' to external links for safety
    )

    return sanitized_content
