import logging
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

import src.services.websocket as websocket_service
from src.database.models import User

from ..dependencies import get_ws_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websockets"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    current_user: Annotated[User, Depends(get_ws_current_user)],
) -> None:
    """WebSocket connection endpoint handling client authentication and lifecycle."""
    await websocket.accept()
    await websocket_service.register_connection(current_user.user_id, websocket)
    logger.info("WebSocket connection established for user %s", current_user.user_id)

    try:
        while True:
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for user %s", current_user.user_id)
    except Exception as e:
        logger.error(
            "Unexpected error in WebSocket session for user %s: %s", current_user.user_id, e
        )
    finally:
        await websocket_service.unregister_connection(current_user.user_id)
