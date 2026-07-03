from __future__ import annotations

from typing import Any, cast

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType
from utils import logger
from utils.maa_types import is_hit
from utils.params import parse_params


@AgentServer.custom_recognition("ExampleRecognition")
class ExampleRecognition(CustomRecognition):
    """Demonstrates a minimal custom recognition flow.

    Examples:
        Reuse an existing recognition node::

            {
                "node": "ExistingRecognitionNode",
                "detail": {"source": "example"}
            }

        Return a static box::

            {
                "box": [0, 0, 100, 100],
                "detail": {"source": "static-box"}
            }
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | None:
        try:
            params = parse_params(argv.custom_recognition_param)
            node_name = params.get("node")
            if node_name is None:
                node_name = params.get("template_node")

            if node_name is not None and (not isinstance(node_name, str) or not node_name):
                raise ValueError("node must be a non-empty string.")

            box_value = params.get("box")
            if box_value is not None and not (
                isinstance(box_value, list)
                and len(box_value) == 4
                and all(isinstance(item, int) for item in box_value)
            ):
                raise ValueError("box must be [x, y, w, h].")
            box = cast(RectType | None, box_value)

            detail_value = params.get("detail", {})
            if detail_value is None:
                detail_value = {}
            if not isinstance(detail_value, dict):
                raise ValueError("detail must be an object.")
            detail = cast(dict[str, Any], detail_value)
        except ValueError as error:
            logger.error("ExampleRecognition: %s", error)
            return None

        if node_name:
            reco_detail = context.run_recognition(node_name, argv.image)
            if not is_hit(reco_detail):
                return None
            reco_box = getattr(reco_detail, "box", None)
            if reco_box is None:
                return None

            result_detail: dict[str, Any] = {
                "source": "run_recognition",
                "node": node_name,
                "detail": getattr(reco_detail, "detail", None),
            }
            result_detail.update(detail)
            return CustomRecognition.AnalyzeResult(
                box=cast(RectType, reco_box),
                detail=result_detail,
            )

        if box is not None:
            return CustomRecognition.AnalyzeResult(box=box, detail=detail)

        logger.info(
            "ExampleRecognition has no node or box configured; replace it with project logic."
        )
        return None
