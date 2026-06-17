
from typing import List, Dict
from serviceNode import *
from content import Content

def content_availability(PSk: List[PathEntry], TBk: float):
    availability = sum(1 / len(pe.path) for pe in PSk)
    return availability if availability < TBk else 0.0

def normalized_lifetime(content: Content, current_time: float, TTk: float):
    age_ratio = (current_time - content.generation_time) / content.lifespan
    return age_ratio if age_ratio >= TTk else 0.0

def caching_weight(content: Content, PSk: List[PathEntry],
                current_time: float, TBk: float, TTk: float):
    b = content_availability(PSk, TBk)
    f = normalized_lifetime(content, current_time, TTk)
    return b * f

def select_caching_node(
    EN_position,
    service_nodes,
    thresholds: Dict[str, float]
):
    best_score = -1
    best_node = None

    for sn in service_nodes:
        w = sn.node_weight()
        if w == 0:
            continue

        d = sn.coord.distance_to(EN_position)
        score = w * d

        if score > best_score:
            best_score = score
            best_node = sn

    return best_node

def caching_decision(
    loop,
    EN_position,
    content: Content,
    PSk: List[PathEntry],
    service_nodes,
    thresholds = 0 ,
    TBk = 0,
    TTk = 0
):
    now = loop.time
    c = caching_weight(content, PSk, now, TBk, TTk)
    if c == 0:
        return None  # clD_k = empty
    caching_node = select_caching_node(
        EN_position, service_nodes, thresholds
    )
    return caching_node.id if caching_node else None




# from typing import List, Dict
# from serviceNode import *
# from content import Content
# from serviceNode import Router

# def content_availability(PSk: List[PathEntry], TBk: float):
#     availability = sum(1 / len(pe.path) for pe in PSk)
#     return availability if availability < TBk else 0.0

# def normalized_lifetime(content: Content, current_time: float, TTk: float):
#     age_ratio = (current_time - content.generation_time) / content.lifespan
#     return age_ratio if age_ratio >= TTk else 0.0

# def caching_weight(content: Content, PSk: List[PathEntry],
#                 current_time: float, TBk: float, TTk: float):
#     b = content_availability(PSk, TBk)
#     f = normalized_lifetime(content, current_time, TTk)
#     return b * f

# def select_caching_node(
#     EN_position,
#     service_nodes: List[Router],
#     thresholds: Dict[str, float]
# ):
#     best_score = -1
#     best_node = None

#     for sn in service_nodes:
#         w = sn.node_weight()
#         if w == 0:
#             continue

#         d = sn.coord.distance_to(EN_position)
#         score = w * d

#         if score > best_score:
#             best_score = score
#             best_node = sn

#     return best_node

# def caching_decision(
#     EN_position,
#     content: Content,
#     PSk: List[PathEntry],
#     service_nodes: List[Router],
#     thresholds = 0 ,
#     TBk = 0,
#     TTk = 0
# ):
#     now = time.time()
#     c = caching_weight(content, PSk, now, TBk, TTk)
#     if c == 0:
#         return None  # clD_k = empty
#     caching_node = select_caching_node(
#         EN_position, service_nodes, thresholds
#     )
#     return caching_node.id if caching_node else None
