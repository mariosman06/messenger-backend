"""WebSocket endpoint router handling connection handshakes and user sessions."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from src.api.dependencies import get_current_user_ws, get_ws_manager_ws
from src.database.models import User
from src.services.websocket import WebSocketManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSockets"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    current_user: Annotated[User, Depends(get_current_user_ws)],
    ws_manager: Annotated[WebSocketManager, Depends(get_ws_manager_ws)],
) -> None:
    """WebSocket connection endpoint handling client authentication and session registration."""
    await websocket.accept()

    is_registered = False
    try:
        await ws_manager.register_connection(current_user.user_id, websocket)
        is_registered = True
        logger.info("WebSocket connection established for user %s", current_user.user_id)

        while True:
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for user %s", current_user.user_id)
    except Exception as e:
        logger.error(
            "Unexpected error in WebSocket session for user %s: %s",
            current_user.user_id,
            e,
            exc_info=True,
        )
    finally:
        if is_registered:
            try:
                await ws_manager.unregister_connection(current_user.user_id, websocket)
            except Exception as e:
                logger.error(
                    "Failed to unregister WebSocket connection for user %s: %s",
                    current_user.user_id,
                    e,
                    exc_info=True,
                )
