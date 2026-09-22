"""Sql statements for schema and index initialization and table operations."""

from .enums import Constraint, Index


class IterableStatements(type):
    def __iter__(cls):
        for name, value in cls.__dict__.items():
            if not name.startswith("_") and isinstance(value, str):
                yield value


CLEAR_TABLES = """
TRUNCATE
    users,
    refresh_tokens,
    access_tokens,
    friendships,
    groups,
    memberships CASCADE;
"""


class EnsureTableExists(metaclass=IterableStatements):
    """SQL DDL statements for initializing application database tables."""

    # User
    USER = f"""
    CREATE TABLE IF NOT EXISTS users (
        user_id UUID NOT NULL,
        username TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        deactivated BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT {Constraint.PK_USERS} PRIMARY KEY (user_id),
        CONSTRAINT {Constraint.UQ_USERS_USERNAME} UNIQUE (username)
    );
    """

    # Friendship
    FRIENDSHIPS = f"""
    CREATE TABLE IF NOT EXISTS friendships (
        requester_id UUID NOT NULL,
        addressee_id UUID NOT NULL,
        accepted BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT {Constraint.PK_FRIENDSHIPS} PRIMARY KEY (requester_id, addressee_id),
        CONSTRAINT {Constraint.FK_FRIENDSHIPS_REQUESTER_ID}
            FOREIGN KEY (requester_id)
            REFERENCES users(user_id) ON DELETE CASCADE,
        CONSTRAINT {Constraint.FK_FRIENDSHIPS_ADDRESSEE_ID}
            FOREIGN KEY (addressee_id)
            REFERENCES users(user_id) ON DELETE CASCADE
    );
    """

    # Token
    ACCESS_TOKENS = f"""
    CREATE TABLE IF NOT EXISTS access_tokens (
        token_hash TEXT NOT NULL,
        user_id UUID NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        is_revoked BOOLEAN NOT NULL DEFAULT FALSE,

        CONSTRAINT {Constraint.PK_ACCESS_TOKENS} PRIMARY KEY (token_hash),
        CONSTRAINT {Constraint.FK_ACCESS_TOKENS_USER_ID}
            FOREIGN KEY (user_id)
            REFERENCES users(user_id) ON DELETE CASCADE
    );
    """

    REFRESH_TOKENS = f"""
    CREATE TABLE IF NOT EXISTS refresh_tokens (
        token_hash TEXT NOT NULL,
        user_id UUID NOT NULL,
        is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
        expires_at TIMESTAMPTZ NOT NULL,

        CONSTRAINT {Constraint.PK_REFRESH_TOKENS} PRIMARY KEY (token_hash),
        CONSTRAINT {Constraint.FK_REFRESH_TOKENS_USER_ID}
            FOREIGN KEY (user_id)
            REFERENCES users(user_id) ON DELETE CASCADE
    );
    """

    # Group
    GROUPS = f"""
    CREATE TABLE IF NOT EXISTS groups (
        group_id UUID NOT NULL,
        name TEXT NOT NULL,
        created_by UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT {Constraint.PK_GROUPS} PRIMARY KEY (group_id),

        CONSTRAINT {Constraint.FK_GROUPS_CREATED_BY}
            FOREIGN KEY (created_by)
            REFERENCES users(user_id) ON DELETE SET NULL
    );
    """

    # Membership
    MEMBERSHIPS = f"""
    CREATE TABLE IF NOT EXISTS memberships (
        group_id UUID NOT NULL,
        user_id UUID NOT NULL,
        joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT {Constraint.PK_MEMBERSHIPS} PRIMARY KEY (group_id, user_id),
        CONSTRAINT {Constraint.FK_MEMBERSHIPS_GROUP_ID}
            FOREIGN KEY (group_id)
            REFERENCES groups(group_id) ON DELETE CASCADE,
        CONSTRAINT {Constraint.FK_MEMBERSHIPS_USER_ID}
            FOREIGN KEY (user_id)
            REFERENCES users(user_id) ON DELETE CASCADE
    );
    """

    # Messages
    DIRECT_MESSAGES = f"""
    CREATE TABLE IF NOT EXISTS direct_messages (
        message_id UUID NOT NULL,
        sender_id UUID NOT NULL,
        recipient_id UUID NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT {Constraint.PK_DIRECT_MESSAGES} PRIMARY KEY (message_id),
        CONSTRAINT {Constraint.FK_DM_SENDER_ID}
            FOREIGN KEY (sender_id)
            REFERENCES users(user_id) ON DELETE CASCADE,
        CONSTRAINT {Constraint.FK_DM_RECIPIENT_ID}
            FOREIGN KEY (recipient_id)
            REFERENCES users(user_id) ON DELETE CASCADE
    );
    """

    GROUP_MESSAGES = f"""
    CREATE TABLE IF NOT EXISTS group_messages (
        message_id UUID NOT NULL,
        group_id UUID NOT NULL,
        sender_id UUID NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT {Constraint.PK_GROUP_MESSAGES} PRIMARY KEY (message_id),
        CONSTRAINT {Constraint.FK_GROUP_MESSAGES_GROUP_ID}
            FOREIGN KEY (group_id)
            REFERENCES groups(group_id) ON DELETE CASCADE,
        CONSTRAINT {Constraint.FK_GROUP_MESSAGES_SENDER_ID}
            FOREIGN KEY (sender_id)
            REFERENCES users(user_id) ON DELETE CASCADE
    );
    """


class EnsureIndexExists(metaclass=IterableStatements):
    """SQL DDL statements for creating indexes across database tables."""

    # Friendship
    IDX_FRIENDSHIPS_ADDRESSEE_ID = f"""
    CREATE INDEX IF NOT EXISTS {Index.IDX_FRIENDSHIPS_ADDRESSEE_ID}
    ON friendships(addressee_id, accepted);
    """
    IDX_FRIENDSHIPS_REQUESTER_ID = """
    CREATE INDEX IF NOT EXISTS idx_friendships_requester_id
    ON friendships(requester_id, accepted);
    """

    # Token
    IDX_ACCESS_TOKENS_USER_ID = f"""
    CREATE INDEX IF NOT EXISTS {Index.IDX_ACCESS_TOKENS_USER_ID}
    ON access_tokens(user_id);
    """
    IDX_REFRESH_TOKENS_USER_ID = f"""
    CREATE INDEX IF NOT EXISTS {Index.IDX_REFRESH_TOKENS_USER_ID}
    ON refresh_tokens(user_id);
    """
    IDX_ACCESS_TOKENS_EXPIRES_AT = f"""
    CREATE INDEX IF NOT EXISTS {Index.IDX_ACCESS_TOKENS_EXPIRES_AT}
    ON access_tokens(expires_at);
    """
    IDX_REFRESH_TOKENS_EXPIRES_AT = f"""
    CREATE INDEX IF NOT EXISTS {Index.IDX_REFRESH_TOKENS_EXPIRES_AT}
    ON refresh_tokens(expires_at);
    """

    # Group
    IDX_GROUPS_CREATED_BY = f"""
    CREATE INDEX IF NOT EXISTS {Index.IDX_GROUPS_CREATED_BY}
    ON groups(created_by);
    """

    # Membership
    IDX_MEMBERSHIPS_USER_ID = f"""
    CREATE INDEX IF NOT EXISTS {Index.IDX_MEMBERSHIPS_USER_ID}
    ON memberships(user_id, group_id);
    """

    # Messages
    IDX_DM_SENDER_RECIPIENT = f"""
    CREATE INDEX IF NOT EXISTS {Index.IDX_DM_SENDER_RECIPIENT}
    ON direct_messages(sender_id, recipient_id, created_at DESC);
    """
    IDX_DM_RECIPIENT_SENDER = f"""
    CREATE INDEX IF NOT EXISTS {Index.IDX_DM_RECIPIENT_SENDER}
    ON direct_messages(recipient_id, sender_id, created_at DESC);
    """
    IDX_GROUP_MESSAGES_TIMELINE = f"""
    CREATE INDEX IF NOT EXISTS {Index.IDX_GROUP_MESSAGES_TIMELINE}
    ON group_messages(group_id, created_at DESC);
    """
    IDX_GROUP_MESSAGES_SENDER_ID = f"""
    CREATE INDEX IF NOT EXISTS {Index.IDX_GROUP_MESSAGES_SENDER_ID}
    ON group_messages(sender_id);
    """


class Fetch:
    """SQL read queries for fetching complete domain entities for model mapping."""

    # User
    USER_BY_ID = """
    SELECT *
    FROM users
    WHERE user_id = $1;
    """
    USER_BY_USERNAME = """
    SELECT *
    FROM users
    WHERE username = $1;
    """
    USER_FOR_SHARE = """
    SELECT *
    FROM users
    WHERE user_id = $1;
    """

    # Friendship
    FRIENDSHIP_STATUS = """
    SELECT *
    FROM friendships
    WHERE (requester_id = $1 AND addressee_id = $2)
       OR (requester_id = $2 AND addressee_id = $1)
    LIMIT 1;
    """
    FRIENDSHIP_FOR_SHARE = """
    SELECT *
    FROM friendships
    WHERE ((requester_id = $1 AND addressee_id = $2) OR (requester_id = $2 AND addressee_id = $1))
      AND accepted = TRUE;
    """
    LIST_ACCEPTED_FRIENDS = """
    SELECT *
    FROM friendships
    WHERE requester_id = $1 AND accepted = TRUE
    UNION ALL
    SELECT *
    FROM friendships
    WHERE addressee_id = $1 AND accepted = TRUE;
    """
    LIST_PENDING_REQUESTS = """
    SELECT *
    FROM friendships
    WHERE addressee_id = $1 AND accepted = FALSE;
    """

    # Token
    ACCESS_TOKEN = """
    SELECT *
    FROM access_tokens
    WHERE token_hash = $1;
    """
    REFRESH_TOKEN = """
    SELECT *
    FROM refresh_tokens
    WHERE token_hash = $1;
    """

    # Group
    GROUP_BY_ID = """
    SELECT *
    FROM groups
    WHERE group_id = $1;
    """
    LIST_USER_GROUPS = """
    SELECT g.*
    FROM groups g
    JOIN memberships m ON g.group_id = m.group_id
    WHERE m.user_id = $1;
    """

    LIST_GROUP_MEMBERSHIPS = """
    SELECT *
    FROM memberships
    WHERE group_id = $1;
    """

    # Membership
    MEMBERSHIP_BY_IDS = """
    SELECT *
    FROM memberships
    WHERE group_id = $1 AND user_id = $2;
    """
    MEMBERSHIP_FOR_SHARE = """
    SELECT *
    FROM memberships
    WHERE group_id = $1 AND user_id = $2;
    """

    # Messages
    DM_CONVERSATION_HISTORY = """
    (SELECT *
     FROM direct_messages
     WHERE sender_id = $1 AND recipient_id = $2 AND created_at < $3
     ORDER BY created_at DESC
     LIMIT $4)
    UNION ALL
    (SELECT *
     FROM direct_messages
     WHERE sender_id = $2 AND recipient_id = $1 AND created_at < $3
     ORDER BY created_at DESC
     LIMIT $4)
    ORDER BY created_at DESC
    LIMIT $4;
    """
    GROUP_MESSAGES_TIMELINE = """
    SELECT *
    FROM group_messages
    WHERE group_id = $1 AND created_at < $2
    ORDER BY created_at DESC
    LIMIT $3;
    """


class Write:
    """SQL mutation queries for creating and modifying application records."""

    # User
    INSERT_USER = """
    INSERT INTO users (user_id, username, password_hash, deactivated, created_at)
    VALUES ($1, $2, $3, $4, $5)
    RETURNING *;
    """
    DEACTIVATE_USER = """
    UPDATE users
    SET deactivated = TRUE
    WHERE user_id = $1;
    """
    REACTIVATE_USER = """
    UPDATE users
    SET deactivated = FALSE
    WHERE user_id = $1;
    """
    CHANGE_PASSWORD = """
    UPDATE users
    SET password_hash = $1
    WHERE user_id = $2 AND password_hash = $3 AND deactivated = FALSE;
    """

    # Friendship
    SEND_FRIEND_REQUEST = """
    INSERT INTO friendships (requester_id, addressee_id, accepted)
    VALUES ($1, $2, FALSE);
    """
    ACCEPT_FRIEND_REQUEST = """
    UPDATE friendships
    SET accepted = TRUE, updated_at = NOW()
    WHERE requester_id = $1 AND addressee_id = $2;
    """

    # Token
    INSERT_ACCESS_TOKEN = """
    INSERT INTO access_tokens (token_hash, user_id, is_revoked, expires_at)
    VALUES ($1, $2, $3, $4);
    """
    INSERT_REFRESH_TOKEN = """
    INSERT INTO refresh_tokens (token_hash, user_id, is_revoked, expires_at)
    VALUES ($1, $2, $3, $4);
    """
    REVOKE_ACCESS_TOKEN = """
    UPDATE access_tokens
    SET is_revoked = TRUE
    WHERE token_hash = $1;
    """
    REVOKE_REFRESH_TOKEN = """
    UPDATE refresh_tokens
    SET is_revoked = TRUE
    WHERE token_hash = $1;
    """
    REVOKE_ALL_USER_ACCESS_TOKENS = """
    UPDATE access_tokens
    SET is_revoked = TRUE
    WHERE user_id = $1;
    """
    REVOKE_ALL_USER_REFRESH_TOKENS = """
    UPDATE refresh_tokens
    SET is_revoked = TRUE
    WHERE user_id = $1;
    """

    # Group
    CREATE_GROUP = """
    INSERT INTO groups (group_id, name, created_by, created_at)
    VALUES ($1, $2, $3, $4)
    RETURNING *;
    """

    # Membership
    ADD_GROUP_MEMBER = """
    INSERT INTO memberships (group_id, user_id, joined_at)
    VALUES ($1, $2, $3)
    RETURNING *;
    """

    # Messages
    SEND_DM = """
    INSERT INTO direct_messages (message_id, sender_id, recipient_id, content, created_at)
    VALUES ($1, $2, $3, $4, $5)
    RETURNING *;
    """
    SEND_GROUP_MESSAGE = """
    INSERT INTO group_messages (message_id, group_id, sender_id, content, created_at)
    VALUES ($1, $2, $3, $4, $5)
    RETURNING *;
    """


class Delete:
    """SQL deletion queries for purging database records."""

    # User
    USER_BY_ID = """
    DELETE FROM users
    WHERE user_id = $1;
    """

    # Friendship
    REMOVE_FRIENDSHIP = """
    DELETE FROM friendships
    WHERE (requester_id = $1 AND addressee_id = $2)
       OR (requester_id = $2 AND addressee_id = $1);
    """

    # Token
    EXPIRED_ACCESS_TOKENS = """
    DELETE FROM access_tokens
    WHERE expires_at < NOW() OR is_revoked = TRUE;
    """
    EXPIRED_REFRESH_TOKENS = """
    DELETE FROM refresh_tokens
    WHERE expires_at < NOW() OR is_revoked = TRUE;
    """

    # Group
    DELETE_GROUP = """
    DELETE FROM groups
    WHERE group_id = $1 AND created_by = $2;
    """

    # Membership
    REMOVE_GROUP_MEMBER = """
    DELETE FROM memberships
    WHERE group_id = $1 AND user_id = $2;
    """
