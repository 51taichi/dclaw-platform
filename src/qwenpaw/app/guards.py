# -*- coding: utf-8 -*-
"""FastAPI dependencies for route guarding based on user roles."""
from fastapi import Request, HTTPException, Depends

def get_current_user_id(request: Request) -> str:
    """Get the authenticated user ID. Raises 401 if missing."""
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        # Fallback for single-user mode when auth is disabled
        from .auth import is_auth_enabled
        if not is_auth_enabled():
            return 0
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id

def require_admin(request: Request) -> str:
    """Dependency that requires the caller to have the 'admin' role.
    
    Returns the user_id if successful. Raises 403 if the user is not an admin.
    """
    user_id = get_current_user_id(request)
    role = getattr(request.state, "role", None)
    if role != "admin":
        from .auth import is_auth_enabled
        if not is_auth_enabled():
            return user_id
        raise HTTPException(
            status_code=403, 
            detail="Admin privileges required for this action"
        )
    return user_id

def require_user(request: Request) -> str:
    """Dependency that requires the caller to be at least a normal user.
    
    Currently all authenticated users (including admins) pass this guard.
    Returns the user_id if successful.
    """
    return get_current_user_id(request)
