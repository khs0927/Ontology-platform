"""Endpoint adjacency only; intersections, regions and constraints are future work."""

from itertools import combinations
from math import dist

from god_cad.models import Drawing, Edge, Geometry


def endpoints(geometry: Geometry):
    if geometry.kind == "LINE":
        return geometry.points
    if geometry.kind == "LWPOLYLINE" and not geometry.closed:
        return [geometry.points[0], geometry.points[-1]]
    return []


def endpoint_edges(drawing: Drawing) -> list[Edge]:
    edges = []
    usable = [e for e in drawing.entities if e.analysis_supported and endpoints(e.geometry)]
    for left, right in combinations(usable, 2):
        if any(
            dist(a, b) <= drawing.topology_tolerance_mm
            for a in endpoints(left.geometry)
            for b in endpoints(right.geometry)
        ):
            edges.append(
                Edge(
                    source=left.id,
                    target=right.id,
                    graph="topology",
                    relation="touches_at_endpoint",
                    evidence=f"endpoint distance <= {drawing.topology_tolerance_mm} mm",
                )
            )
    return edges
