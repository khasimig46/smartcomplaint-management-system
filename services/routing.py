"""Issue #5: Route complaints to the right department and the least-loaded agent.

Rules:
1. Category -> department via DEPARTMENTS.
2. Candidate agents = active agents in that department.
   If the complaint has a zone and some agents cover that zone, prefer them.
3. Pick the candidate with the fewest open complaints (ties -> earliest-created agent).
4. No available agent -> leave unassigned and flag it for the supervisor queue.
"""
DEPARTMENTS = {
    "Water Supply": "Water Department",
    "Electricity": "Electricity Department",
    "Roads": "Roads & Infrastructure",
    "Sanitation": "Sanitation Department",
    "Noise Pollution": "Environment Department",
    "Public Safety": "Public Safety Department",
}
DEFAULT_DEPARTMENT = "General Administration"
CLOSED_STATES = {"Resolved", "Closed"}


def department_for(category: str) -> str:
    return DEPARTMENTS.get(category, DEFAULT_DEPARTMENT)


def open_load(agent_id, complaints):
    return sum(1 for c in complaints if c.get("assigned_to") == agent_id and c.get("status") not in CLOSED_STATES)


def route(category, users, complaints, zone=None):
    """Return {"department", "assigned_to", "needs_supervisor"}."""
    dept = department_for(category)
    agents = [u for u in users if u["role"] == "agent" and u.get("active", True) and u.get("department") == dept]
    if zone:
        local = [a for a in agents if a.get("zone") == zone]
        agents = local or agents
    if not agents:
        return {"department": dept, "assigned_to": None, "needs_supervisor": True}
    best = min(agents, key=lambda a: (open_load(a["id"], complaints), a["created_at"]))
    return {"department": dept, "assigned_to": best["id"], "needs_supervisor": False}
