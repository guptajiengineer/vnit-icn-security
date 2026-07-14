from __future__ import annotations

from statistics import fmean
from typing import Dict, Sequence


def  empty_summary() -> Dict[str, float]:
    return {
        "avg_hops": 0.0,
        "avg_delay": 0.0,
        "avg_success_rate": 0.0,
    }


def  make_user_record(hops: float, delay: float, success_rate: float) -> Dict[str, float]:
    return {
        "hops": float(hops),
        "delay": float(delay),
        "success_rate": float(success_rate),
    }


def  summarize_user_metrics(records: Sequence[Dict[str, float]]) -> Dict[str, float]:
    if not records:
        return  empty_summary()
    return {
        "avg_hops": fmean(record["hops"] for record in records),
        "avg_delay": fmean(record["delay"] for record in records),
        "avg_success_rate": fmean(record["success_rate"] for record in records),
    }


def  summarize_rounds(round_summaries: Sequence[Dict[str, float]]) -> Dict[str, float]:
    if not round_summaries:
        return  empty_summary()
    return {
        "avg_hops": fmean(round["avg_hops"] for round in round_summaries),
        "avg_delay": fmean(round["avg_delay"] for round in round_summaries),
        "avg_success_rate": fmean(round["avg_success_rate"] for round in round_summaries),
    }
