"""Pydantic schemas for request payload validation and response serialization."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Auth Requests


class RegisterRequest(BaseModel):
    """Payload for registering a new user account."""

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Unique account username (3-50 characters).",
    )
    password: str = Field(
        ...,
        min_length=8,
        description="Account password (minimum 8 characters).",
    )


class LoginRequest(BaseModel):
    """Payload for authenticating an existing user."""

    username: str = Field(
        ...,
        description="Account username.",
    )
    password: str = Field(
        ...,
        description="Account password.",
    )


class RefreshRequest(BaseModel):
    """Payload for requesting a fresh authentication token pair."""

    refresh_token: str = Field(
        ...,
        description="Active raw refresh token.",
    )


class LogoutRequest(BaseModel):
    """Payload for invalidating active authentication sessions."""

    refresh_token: str = Field(
        ...,
        description="Raw refresh token to invalidate.",
    )


# Friendship Requests


class SendFriendRequest(BaseModel):
    """Payload for sending a new friend request."""

    addressee_id: UUID = Field(
        ...,
        description="Target user UUID receiving the request.",
    )


# Group Requests


class CreateGroupRequest(BaseModel):
    """Payload required to create a new group chat."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Display name for the new group (1-100 characters).",
    )


class AddGroupMemberRequest(BaseModel):
    """Payload containing the target user ID to add to a group."""

    user_id: UUID = Field(
        ...,
        description="UUID of the user to be added to the group.",
    )


# Message Requests


class SendDirectMessageRequest(BaseModel):
    """Payload for dispatching a direct message to another user."""

    recipient_id: UUID = Field(
        ...,
        description="UUID of the user receiving the direct message.",
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Text content of the direct message (1-4096 characters).",
    )


class SendGroupMessageRequest(BaseModel):
    """Payload for dispatching a message to a group chat."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Text content of the group message (1-4096 characters).",
    )


# Base Response


class BaseResponse(BaseModel):
    """Base response schema configured for ORM attribute mapping."""

    model_config = ConfigDict(from_attributes=True)


# Group Responses


class GroupResponse(BaseResponse):
    """Schema representing group details returned to clients."""

    group_id: UUID = Field(
        ...,
        description="Unique identifier of the group.",
    )
    name: str = Field(
        ...,
        description="Display name of the group.",
    )
    created_by: UUID | None = Field(
        None,
        description="UUID of the user who created the group, or None if system-owned.",
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp when the group was created.",
    )


class MembershipResponse(BaseResponse):
    """Schema representing group membership state."""

    group_id: UUID = Field(
        ...,
        description="Unique identifier of the group.",
    )
    user_id: UUID = Field(
        ...,
        description="Unique identifier of the group member.",
    )
    joined_at: datetime = Field(
        ...,
        description="UTC timestamp when the user joined the group.",
    )


# User Responses


class UserResponse(BaseResponse):
    """Public user profile schema."""

    user_id: UUID = Field(
        ...,
        description="Unique user identifier.",
    )
    username: str = Field(
        ...,
        description="Account handle.",
    )
    deactivated: bool = Field(
        ...,
        description="Account active state flag.",
    )
    created_at: datetime = Field(
        ...,
        description="Account creation timestamp in UTC.",
    )


# Token Responses


class TokenPairResponse(BaseResponse):
    """Issued bearer access token and refresh token details."""

    access_token: str = Field(
        ...,
        description="Bearer access token.",
    )
    refresh_token: str = Field(
        ...,
        description="Opaque refresh token.",
    )
    access_token_expires_at: datetime = Field(
        ...,
        description="Access token expiration timestamp in UTC.",
    )
    refresh_token_expires_at: datetime = Field(
        ...,
        description="Refresh token expiration timestamp in UTC.",
    )


# Auth Responses


class AuthResponse(BaseResponse):
    """Response payload returned upon successful authentication or registration."""

    user: UserResponse = Field(
        ...,
        description="Authenticated user profile.",
    )
    tokens: TokenPairResponse = Field(
        ...,
        description="Issued authentication token pair.",
    )


# Friendship Responses


class FriendshipResponse(BaseResponse):
    """Schema representing a friendship or friend request relationship."""

    requester_id: UUID = Field(
        ...,
        description="User UUID who initiated the friend request.",
    )
    addressee_id: UUID = Field(
        ...,
        description="User UUID who received the friend request.",
    )
    accepted: bool = Field(
        ...,
        description="Boolean status indicating whether the friend request has been accepted.",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when the request was sent.",
    )
    updated_at: datetime = Field(
        ...,
        description="Timestamp when the relationship status was last changed.",
    )


# Message Responses


class DirectMessageResponse(BaseResponse):
    """Schema representing a direct message sent between two users."""

    message_id: UUID = Field(
        ...,
        description="Unique identifier of the direct message.",
    )
    sender_id: UUID = Field(
        ...,
        description="UUID of the user who sent the message.",
    )
    recipient_id: UUID = Field(
        ...,
        description="UUID of the user receiving the message.",
    )
    content: str = Field(
        ...,
        description="Text content of the direct message.",
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp when the message was sent.",
    )


class GroupMessageResponse(BaseResponse):
    """Schema representing a message sent within a group chat."""

    message_id: UUID = Field(
        ...,
        description="Unique identifier of the group message.",
    )
    group_id: UUID = Field(
        ...,
        description="UUID of the destination group.",
    )
    sender_id: UUID = Field(
        ...,
        description="UUID of the user who sent the message.",
    )
    content: str = Field(
        ...,
        description="Text content of the group message.",
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp when the message was sent.",
    )
