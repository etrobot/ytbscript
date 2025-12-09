"""
Cookie utilities for converting cookie strings to Netscape format
"""
import re
from pathlib import Path
from typing import Optional
import tempfile


def cookie_string_to_netscape(cookie_string: str) -> str:
    """
    Convert cookie string to Netscape format
    
    Args:
        cookie_string: Cookie string in various formats (JSON, header format, etc.)
        
    Returns:
        Cookie string in Netscape format
    """
    if not cookie_string.strip():
        return ""
    
    # If it's already in Netscape format, return as is
    if is_netscape_format(cookie_string):
        return cookie_string
    
    # Try to parse as JSON format (like from browser extensions)
    if cookie_string.strip().startswith('['):
        return json_cookies_to_netscape(cookie_string)
    
    # Try to parse as header format (name=value; name2=value2)
    if '=' in cookie_string and ';' in cookie_string:
        return header_cookies_to_netscape(cookie_string)
    
    # If we can't determine format, assume it's already Netscape or raw format
    return cookie_string


def is_netscape_format(cookie_string: str) -> bool:
    """
    Check if cookie string is already in Netscape format
    
    Netscape format has lines like:
    # Netscape HTTP Cookie File
    .domain.com	TRUE	/	FALSE	expiration	name	value
    """
    lines = cookie_string.strip().split('\n')
    
    # Check for Netscape header
    if lines and '# Netscape HTTP Cookie File' in lines[0]:
        return True
    
    # Check if lines follow Netscape tab-separated format
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            parts = line.split('\t')
            if len(parts) == 7:  # Netscape format has 7 tab-separated fields
                return True
    
    return False


def json_cookies_to_netscape(json_string: str) -> str:
    """
    Convert JSON cookie format to Netscape format
    
    JSON format is typically an array of cookie objects like:
    [{"name": "cookie_name", "value": "cookie_value", "domain": ".example.com", ...}]
    """
    import json
    
    try:
        cookies = json.loads(json_string)
        if not isinstance(cookies, list):
            return json_string  # Not the expected format
        
        netscape_lines = ["# Netscape HTTP Cookie File"]
        
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            
            name = cookie.get('name', '')
            value = cookie.get('value', '')
            domain = cookie.get('domain', '.youtube.com')  # Default to YouTube domain
            path = cookie.get('path', '/')
            secure = cookie.get('secure', False)
            http_only = cookie.get('httpOnly', False)
            expires = cookie.get('expirationDate', 0)
            
            # Convert to Netscape format:
            # domain, domain_specified, path, secure, expires, name, value
            domain_specified = 'TRUE' if domain.startswith('.') else 'FALSE'
            secure_flag = 'TRUE' if secure else 'FALSE'
            expires_timestamp = int(expires) if expires else 0
            
            netscape_line = f"{domain}\t{domain_specified}\t{path}\t{secure_flag}\t{expires_timestamp}\t{name}\t{value}"
            netscape_lines.append(netscape_line)
        
        return '\n'.join(netscape_lines)
        
    except json.JSONDecodeError:
        return json_string  # Return original if can't parse


def header_cookies_to_netscape(header_string: str) -> str:
    """
    Convert header-style cookies to Netscape format
    
    Header format: name=value; name2=value2; Domain=.example.com; Path=/
    """
    netscape_lines = ["# Netscape HTTP Cookie File"]
    
    # Parse header-style cookies
    parts = header_string.split(';')
    cookies = []
    domain = '.youtube.com'  # Default to YouTube domain for better compatibility
    path = '/'
    
    for part in parts:
        part = part.strip()
        if '=' in part:
            key, value = part.split('=', 1)
            key = key.strip()
            value = value.strip()
            
            if key.lower() == 'domain':
                domain = value
            elif key.lower() == 'path':
                path = value
            elif not key.lower() in ['secure', 'httponly', 'samesite']:
                cookies.append((key, value))
    
    # Convert to Netscape format
    for name, value in cookies:
        domain_specified = 'TRUE' if domain.startswith('.') else 'FALSE'
        secure_flag = 'FALSE'  # Default to false for header format
        expires_timestamp = 0  # Default to session cookie
        
        netscape_line = f"{domain}\t{domain_specified}\t{path}\t{secure_flag}\t{expires_timestamp}\t{name}\t{value}"
        netscape_lines.append(netscape_line)
    
    return '\n'.join(netscape_lines)


def save_cookie_string_as_netscape(cookie_string: str, file_path: Optional[Path] = None) -> Path:
    """
    Convert cookie string to Netscape format and save to file
    
    Args:
        cookie_string: Cookie string in any supported format
        file_path: Optional path to save the file. If None, creates a temporary file.
        
    Returns:
        Path to the saved cookie file
    """
    netscape_content = cookie_string_to_netscape(cookie_string)
    
    if file_path is None:
        # Create temporary file
        temp_fd, temp_path = tempfile.mkstemp(suffix=".txt", prefix="cookies_")
        file_path = Path(temp_path)
        # Close the file descriptor since we'll write with open()
        import os
        os.close(temp_fd)
    
    # Write Netscape format to file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(netscape_content)
    
    return file_path