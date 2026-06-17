from __future__ import annotations

from typing import Dict, Sequence, Tuple
import config
from models import PathRecord


def  learning_key(
    access_node_id: str,
    content_id: str,
    path: Sequence[str],
) -> Tuple[str, str, Tuple[str, ...]]:
    return access_node_id, content_id, tuple(path)


def  apply_learning_scores(
    path_records: Sequence[PathRecord],
    access_node_id: str,
    content_id: str,
    learning_scores: Dict[Tuple[str, str, Tuple[str, ...]], float],
) :
    for record in path_records:
        key =  learning_key(access_node_id, content_id, record.path)
        learned_weight = learning_scores.get(key, record.instant_weight)
        record.learned_weight = learned_weight
        record.weight = max(
            0.01,
            ((1.0 - config.LEARNED_WEIGHT_BLEND) * record.instant_weight)
            + (config.LEARNED_WEIGHT_BLEND * learned_weight),
        )
