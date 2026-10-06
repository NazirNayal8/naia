"""Configuration-independent hierarchy and tensor dependency evidence."""
from ._semantics import supports_semantic, validate_semantic


def validate_graph(graph):
    if not isinstance(graph, dict) or graph.get("schema_version") != 1:
        raise ValueError("Expected architecture schema_version=1")
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("Architecture requires nodes")
    by_id = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"] or node["id"] in by_id:
            raise ValueError("Node identities must be nonempty and unique")
        if node.get("parent") is not None and not isinstance(node["parent"], str):
            raise ValueError("Node parent must be an identity or null")
        if "semantic" in node:
            if not supports_semantic(node):
                raise ValueError("Semantic annotations require a module, input, or output node")
            validate_semantic(node["semantic"])
        by_id[node["id"]] = node
    for node in nodes:
        seen = {node["id"]}
        parent = node.get("parent")
        while parent is not None:
            if parent not in by_id or parent in seen:
                raise ValueError("Invalid or cyclic node hierarchy")
            seen.add(parent)
            parent = by_id[parent].get("parent")
    if not isinstance(graph.get("edges", []), list) or not isinstance(graph.get("events", []), list):
        raise ValueError("Architecture edges and events must be lists")
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict) or not isinstance(edge.get("source"), str) or not isinstance(edge.get("target"), str):
            raise ValueError("Edge endpoints must be identities")
        if edge["source"] not in by_id or edge["target"] not in by_id:
            raise ValueError("Edge references unknown node")
        if edge.get("evidence") not in ("observed", "traced", "declared"):
            raise ValueError("Data-flow edges require observed, traced or declared evidence")
    for event in graph.get("events", []):
        if not isinstance(event, dict) or not isinstance(event.get("node"), str) or event["node"] not in by_id:
            raise ValueError("Observed call references unknown module")
    if not isinstance(graph.get("warnings", []), list) or any(not isinstance(warning, str) for warning in graph.get("warnings", [])):
        raise ValueError("Architecture warnings must be strings")
    flow = graph.get("dataflow")
    if flow is not None:
        if not isinstance(flow, dict) or not isinstance(flow.get("engine"), str):
            raise ValueError("Data-flow metadata requires an engine")
        identities = flow.get("nodes")
        if (not isinstance(identities, list)
                or any(not isinstance(identity, str) or identity not in by_id for identity in identities)
                or len(set(identities)) != len(identities)):
            raise ValueError("Data-flow metadata references invalid nodes")
        if not isinstance(flow.get("complete"), bool):
            raise ValueError("Data-flow metadata requires a completeness flag")
    return graph
