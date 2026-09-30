def should_continue_fact_check(current_iteration: int, max_iterations: int) -> bool:
    """Return whether the fact-check loop should continue."""
    return current_iteration < max_iterations
