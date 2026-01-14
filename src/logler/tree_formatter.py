"""
Tree Formatter - Beautiful CLI visualization for hierarchical data

Renders thread hierarchies and nested structures as ASCII trees with:
- Unicode box-drawing characters
- Color support (via Rich when available)
- Error highlighting
- Duration annotations
- Compact and detailed modes
"""

from typing import Dict, Any, List, Optional
from datetime import datetime


try:
    from rich.console import Console  # noqa: F401
    from rich.text import Text  # noqa: F401
    from rich.tree import Tree as RichTree  # noqa: F401

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Text = None  # Placeholder when Rich is not available


def format_tree(
    hierarchy: Dict[str, Any],
    mode: str = "compact",
    show_duration: bool = True,
    show_errors: bool = True,
    show_confidence: bool = False,
    max_depth: Optional[int] = None,
    use_colors: bool = True,
) -> str:
    """
    Format a hierarchy as an ASCII tree.

    Args:
        hierarchy: Hierarchy dictionary from follow_thread_hierarchy()
        mode: Display mode - "compact", "detailed", or "full"
        show_duration: Show duration annotations
        show_errors: Highlight errors
        show_confidence: Show confidence scores
        max_depth: Maximum depth to display (None = unlimited)
        use_colors: Use ANSI colors (requires Rich)

    Returns:
        Formatted tree string

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        tree = format_tree(hierarchy, mode="compact", show_duration=True)
        print(tree)
    """
    if use_colors and RICH_AVAILABLE:
        return _format_rich_tree(
            hierarchy, mode, show_duration, show_errors, show_confidence, max_depth
        )
    else:
        return _format_ascii_tree(
            hierarchy, mode, show_duration, show_errors, show_confidence, max_depth
        )


def _format_ascii_tree(
    hierarchy: Dict[str, Any],
    mode: str,
    show_duration: bool,
    show_errors: bool,
    show_confidence: bool,
    max_depth: Optional[int],
) -> str:
    """Format tree using plain ASCII (no colors)"""
    lines = []

    # Header
    lines.append("=" * 70)
    lines.append("THREAD HIERARCHY")
    lines.append("=" * 70)
    lines.append(f"Total nodes: {hierarchy.get('total_nodes', 0)}")
    lines.append(f"Max depth: {hierarchy.get('max_depth', 0)}")
    lines.append(f"Detection: {hierarchy.get('detection_method', 'Unknown')}")

    total_duration = hierarchy.get("total_duration_ms")
    if total_duration and show_duration:
        lines.append(f"Total duration: {_format_duration(total_duration)}")

    # Bottleneck
    bottleneck = hierarchy.get("bottleneck")
    if bottleneck:
        lines.append("")
        lines.append(
            f"⚠️  BOTTLENECK: {bottleneck.get('node_id')} ({_format_duration(bottleneck.get('duration_ms', 0))}, {bottleneck.get('percentage', 0):.1f}%)"
        )

    # Errors
    error_nodes = hierarchy.get("error_nodes", [])
    if error_nodes and show_errors:
        lines.append("")
        lines.append(f"❌ {len(error_nodes)} node(s) with errors")

    lines.append("")
    lines.append("-" * 70)
    lines.append("")

    # Tree
    roots = hierarchy.get("roots", [])
    for i, root in enumerate(roots):
        is_last_root = i == len(roots) - 1
        _append_node_ascii(
            root,
            lines,
            "",
            is_last_root,
            mode,
            show_duration,
            show_errors,
            show_confidence,
            max_depth,
            0,
        )

    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


def _append_node_ascii(
    node: Dict[str, Any],
    lines: List[str],
    prefix: str,
    is_last: bool,
    mode: str,
    show_duration: bool,
    show_errors: bool,
    show_confidence: bool,
    max_depth: Optional[int],
    current_depth: int,
):
    """Recursively append node to ASCII tree"""
    if max_depth is not None and current_depth >= max_depth:
        return

    # Node connector
    connector = "└── " if is_last else "├── "

    # Node ID and type - prefer 'name' over 'id' for display
    node_id = node.get("name") or node.get("id", "unknown")
    node_type = node.get("node_type", "Unknown")

    # Error marker
    error_marker = ""
    if show_errors and node.get("error_count", 0) > 0:
        error_marker = f"❌ [{node.get('error_count')} errors] "

    # Build node line
    node_line = f"{prefix}{connector}{error_marker}{node_id}"

    # Add metadata based on mode
    metadata = []

    if mode == "detailed" or mode == "full":
        metadata.append(f"type={node_type}")
        metadata.append(f"entries={node.get('entry_count', 0)}")

        if show_duration:
            duration_ms = node.get("duration_ms")
            if duration_ms is not None:
                metadata.append(f"duration={_format_duration(duration_ms)}")

        if show_confidence:
            confidence = node.get("confidence", 0.0)
            metadata.append(f"confidence={confidence:.2f}")

    elif mode == "compact":
        # Compact mode: just entry count and duration
        metadata.append(f"{node.get('entry_count', 0)} entries")
        if show_duration:
            duration_ms = node.get("duration_ms")
            if duration_ms is not None:
                metadata.append(_format_duration(duration_ms))

    if metadata:
        node_line += f" ({', '.join(metadata)})"

    lines.append(node_line)

    # Full mode: show additional details
    if mode == "full":
        child_prefix = prefix + ("    " if is_last else "│   ")
        level_counts = node.get("level_counts", {})
        if level_counts:
            level_str = ", ".join([f"{level}: {count}" for level, count in level_counts.items()])
            lines.append(f"{child_prefix}  Levels: {level_str}")

        evidence = node.get("relationship_evidence", [])
        if evidence and show_confidence:
            for ev in evidence[:2]:  # Show first 2
                lines.append(f"{child_prefix}  📋 {ev}")

    # Process children
    children = node.get("children", [])
    if children:
        # Sort children by start time if available
        sorted_children = sorted(
            children, key=lambda c: c.get("start_time") or "9999-12-31T23:59:59Z"
        )

        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(sorted_children):
            is_last_child = i == len(sorted_children) - 1
            _append_node_ascii(
                child,
                lines,
                child_prefix,
                is_last_child,
                mode,
                show_duration,
                show_errors,
                show_confidence,
                max_depth,
                current_depth + 1,
            )


def _format_rich_tree(
    hierarchy: Dict[str, Any],
    mode: str,
    show_duration: bool,
    show_errors: bool,
    show_confidence: bool,
    max_depth: Optional[int],
) -> str:
    """Format tree using Rich library with colors"""
    from rich.console import Console
    from rich.tree import Tree as RichTree
    from rich.text import Text
    from io import StringIO

    console = Console(file=StringIO(), width=100)

    # Create root tree
    header = Text()
    header.append("Thread Hierarchy", style="bold cyan")
    header.append(f" ({hierarchy.get('total_nodes', 0)} nodes, ", style="dim")
    header.append(f"max depth: {hierarchy.get('max_depth', 0)}", style="dim")
    if show_duration:
        total_duration = hierarchy.get("total_duration_ms")
        if total_duration:
            header.append(f", {_format_duration(total_duration)}", style="yellow")
    header.append(")", style="dim")

    tree = RichTree(header)

    # Add bottleneck warning
    bottleneck = hierarchy.get("bottleneck")
    if bottleneck:
        warning = Text()
        warning.append("⚠️  BOTTLENECK: ", style="bold yellow")
        warning.append(bottleneck.get("node_id", ""), style="red")
        warning.append(
            f" ({_format_duration(bottleneck.get('duration_ms', 0))}, {bottleneck.get('percentage', 0):.1f}%)",
            style="yellow",
        )
        tree.add(warning)

    # Add error summary
    error_nodes = hierarchy.get("error_nodes", [])
    if error_nodes and show_errors:
        error_text = Text()
        error_text.append(f"❌ {len(error_nodes)} node(s) with errors", style="bold red")
        tree.add(error_text)

    # Add roots
    roots = hierarchy.get("roots", [])
    for root in roots:
        root_node = _create_rich_node(root, mode, show_duration, show_errors, show_confidence)
        root_tree = tree.add(root_node)
        _add_rich_children(
            root_tree, root, mode, show_duration, show_errors, show_confidence, max_depth, 0
        )

    # Render to string
    output = StringIO()
    console = Console(file=output, width=100)
    console.print(tree)
    return output.getvalue()


def _create_rich_node(
    node: Dict[str, Any],
    mode: str,
    show_duration: bool,
    show_errors: bool,
    show_confidence: bool,
):
    """Create a Rich Text object for a node"""
    from rich.text import Text

    text = Text()

    # Error marker
    if show_errors and node.get("error_count", 0) > 0:
        text.append("❌ ", style="bold red")

    # Node ID
    node_id = node.get("id", "unknown")
    text.append(node_id, style="bold green")

    # Metadata
    metadata = []

    if mode == "detailed" or mode == "full":
        node_type = node.get("node_type", "Unknown")
        metadata.append(f"type={node_type}")
        metadata.append(f"entries={node.get('entry_count', 0)}")

        if show_duration:
            duration_ms = node.get("duration_ms")
            if duration_ms is not None:
                metadata.append(f"duration={_format_duration(duration_ms)}")

        if show_confidence:
            confidence = node.get("confidence", 0.0)
            metadata.append(f"confidence={confidence:.2f}")

    elif mode == "compact":
        metadata.append(f"{node.get('entry_count', 0)} entries")
        if show_duration:
            duration_ms = node.get("duration_ms")
            if duration_ms is not None:
                metadata.append(_format_duration(duration_ms))

    if metadata:
        text.append(" (", style="dim")
        text.append(", ".join(metadata), style="cyan")
        text.append(")", style="dim")

    # Error count
    if show_errors and node.get("error_count", 0) > 0:
        text.append(f" [{node.get('error_count')} errors]", style="bold red")

    return text


def _add_rich_children(
    parent_tree,
    node: Dict[str, Any],
    mode: str,
    show_duration: bool,
    show_errors: bool,
    show_confidence: bool,
    max_depth: Optional[int],
    current_depth: int,
):
    """Recursively add children to Rich tree"""
    if max_depth is not None and current_depth >= max_depth:
        return

    children = node.get("children", [])
    if not children:
        return

    # Sort children by start time
    sorted_children = sorted(children, key=lambda c: c.get("start_time") or "9999-12-31T23:59:59Z")

    for child in sorted_children:
        child_text = _create_rich_node(child, mode, show_duration, show_errors, show_confidence)
        child_tree = parent_tree.add(child_text)

        # Add detailed info in full mode
        if mode == "full":
            level_counts = child.get("level_counts", {})
            if level_counts:
                level_text = Text()
                level_text.append("Levels: ", style="dim")
                level_parts = []
                for level, count in level_counts.items():
                    color = "red" if level == "ERROR" else "yellow" if level == "WARN" else "white"
                    level_parts.append(f"{level}: {count}")
                level_text.append(", ".join(level_parts), style=color)
                child_tree.add(level_text)

            evidence = child.get("relationship_evidence", [])
            if evidence and show_confidence:
                for ev in evidence[:2]:
                    ev_text = Text()
                    ev_text.append("📋 ", style="dim")
                    ev_text.append(ev, style="dim italic")
                    child_tree.add(ev_text)

        _add_rich_children(
            child_tree,
            child,
            mode,
            show_duration,
            show_errors,
            show_confidence,
            max_depth,
            current_depth + 1,
        )


def _format_duration(ms: Optional[int]) -> str:
    """Format duration in human-readable form"""
    if ms is None:
        return "N/A"
    if ms < 1000:
        return f"{ms}ms"
    elif ms < 60000:
        return f"{ms/1000:.2f}s"
    else:
        minutes = ms // 60000
        seconds = (ms % 60000) / 1000
        return f"{minutes}m{seconds:.0f}s"


def print_tree(
    hierarchy: Dict[str, Any],
    mode: str = "compact",
    show_duration: bool = True,
    show_errors: bool = True,
    show_confidence: bool = False,
    max_depth: Optional[int] = None,
):
    """
    Print hierarchy tree to console.

    Convenience function that formats and prints in one call.

    Args:
        hierarchy: Hierarchy dictionary
        mode: Display mode - "compact", "detailed", or "full"
        show_duration: Show duration annotations
        show_errors: Highlight errors
        show_confidence: Show confidence scores
        max_depth: Maximum depth to display

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        print_tree(hierarchy, mode="detailed", show_duration=True)
    """
    tree_str = format_tree(hierarchy, mode, show_duration, show_errors, show_confidence, max_depth)
    print(tree_str)


def format_waterfall(
    hierarchy: Dict[str, Any],
    width: int = 80,
    show_labels: bool = True,
    show_errors: bool = True,
) -> str:
    """
    Format hierarchy as a waterfall timeline (horizontal bars).

    Shows temporal overlap and identifies bottlenecks visually.

    Args:
        hierarchy: Hierarchy dictionary
        width: Width of timeline in characters (default: 80)
        show_labels: Show node labels
        show_errors: Highlight errors in red

    Returns:
        Formatted waterfall string

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        waterfall = format_waterfall(hierarchy, width=100)
        print(waterfall)

        Output:
        ┌─────────────────────────────────────────────────────────────┐
        │ Timeline: req-123 (5000ms)                                  │
        ├─────────────────────────────────────────────────────────────┤
        │ main-thread      ████████████████████████████████████  5000ms│
        │   ├─ db-query    ██████████                          2000ms│
        │   └─ api-call      ████████████████                  3000ms│
        └─────────────────────────────────────────────────────────────┘
    """
    lines = []

    # Calculate total duration and time bounds
    total_duration = hierarchy.get("total_duration_ms", 0)
    if total_duration == 0:
        return "No timing information available"

    # Ensure minimum width for rendering
    min_width = 40  # Minimum useful width
    effective_width = max(width, min_width)

    # Header
    lines.append("┌" + "─" * (effective_width - 2) + "┐")
    header = f"Timeline: {hierarchy.get('detection_method', 'Hierarchy')} ({_format_duration(total_duration)})"
    if len(header) > effective_width - 4:
        header = header[: effective_width - 7] + "..."
    lines.append(f"│ {header:<{effective_width-4}} │")
    lines.append("├" + "─" * (effective_width - 2) + "┤")

    # Collect all nodes in order
    nodes_flat = []
    roots = hierarchy.get("roots", [])
    for root in roots:
        _collect_nodes_flat(root, nodes_flat, 0)

    # Find earliest start time
    earliest = None
    for node_info in nodes_flat:
        node = node_info["node"]
        start_str = node.get("start_time")
        if start_str:
            try:
                start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                if earliest is None or start_time < earliest:
                    earliest = start_time
            except (ValueError, TypeError):
                pass  # Skip invalid timestamps

    if earliest is None:
        return "No timing information available"

    # Render each node (effective_width already set in header section)
    label_width = min(20, effective_width // 3)  # Adaptive label width
    bar_width = max(1, effective_width - label_width - 12)  # Ensure positive bar width

    for node_info in nodes_flat:
        node = node_info["node"]
        depth = node_info["depth"]

        node_id = node.get("id", "unknown")
        start_str = node.get("start_time")
        duration_ms = node.get("duration_ms", 0)

        if not start_str or duration_ms == 0:
            continue

        try:
            start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            offset_ms = int((start_time - earliest).total_seconds() * 1000)
        except (ValueError, TypeError):
            continue  # Skip nodes with invalid timestamps

        # Calculate bar position and length
        bar_start = int((offset_ms / total_duration) * bar_width)
        bar_length = max(1, int((duration_ms / total_duration) * bar_width))

        # Truncate bar if it exceeds width
        if bar_start + bar_length > bar_width:
            bar_length = bar_width - bar_start

        # Build label with indentation
        indent = "  " * depth
        if depth > 0:
            indent = "  " * (depth - 1) + "├─ "

        label = f"{indent}{node_id}"
        if len(label) > label_width:
            label = label[: label_width - 3] + "..."
        label = label.ljust(label_width)

        # Build bar
        bar = " " * bar_start
        error_marker = "❌" if show_errors and node.get("error_count", 0) > 0 else ""
        bar += "█" * bar_length
        bar += error_marker

        # Duration label
        duration_label = _format_duration(duration_ms)

        line = f"│ {label} {bar:<{bar_width}} {duration_label:>7}│"
        # Ensure line fits within effective_width
        if len(line) > effective_width:
            line = line[: effective_width - 1] + "│"
        elif len(line) < effective_width:
            line = line[:-1] + " " * (effective_width - len(line)) + "│"
        lines.append(line)

    # Footer
    lines.append("└" + "─" * (effective_width - 2) + "┘")

    # Add bottleneck info (constrained to effective_width)
    bottleneck = hierarchy.get("bottleneck")
    if bottleneck:
        lines.append("")
        bn_text = f"Bottleneck: {bottleneck.get('node_id')} ({_format_duration(bottleneck.get('duration_ms', 0))}, {bottleneck.get('percentage', 0):.1f}%)"
        if len(bn_text) > effective_width - 4:  # Leave room for emoji
            bn_text = bn_text[: effective_width - 7] + "..."
        lines.append(f"⚠️  {bn_text}")

    return "\n".join(lines)


def _collect_nodes_flat(node: Dict[str, Any], result: List[Dict], depth: int):
    """Flatten hierarchy to list with depth info"""
    result.append({"node": node, "depth": depth})
    for child in node.get("children", []):
        _collect_nodes_flat(child, result, depth + 1)


def print_waterfall(
    hierarchy: Dict[str, Any],
    width: int = 80,
    show_labels: bool = True,
    show_errors: bool = True,
):
    """
    Print waterfall timeline to console.

    Convenience function that formats and prints in one call.

    Args:
        hierarchy: Hierarchy dictionary
        width: Width of timeline in characters
        show_labels: Show node labels
        show_errors: Highlight errors

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        print_waterfall(hierarchy, width=100)
    """
    waterfall_str = format_waterfall(hierarchy, width, show_labels, show_errors)
    print(waterfall_str)


def format_flamegraph(
    hierarchy: Dict[str, Any],
    width: int = 100,
    use_colors: bool = True,
    min_width: int = 3,
) -> str:
    """
    Format hierarchy as a flamegraph-style visualization.

    Flamegraphs show call stacks where:
    - Width represents time spent in that span
    - Each layer shows a different depth level
    - You can see which operations take the most time

    Args:
        hierarchy: Hierarchy dictionary from follow_thread_hierarchy()
        width: Width of the flamegraph in characters
        use_colors: Use ANSI colors
        min_width: Minimum width for a span to be shown

    Returns:
        Formatted flamegraph string

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        print(format_flamegraph(hierarchy, width=100))

        # Output:
        # ┌─────────────────────────────────────────────────────────────────────────────────────┐
        # │ api-gateway (500ms)                                                                  │
        # ├─────────────────────────────┬─────────────────────────────────────────────────────────┤
        # │ auth-service (50ms)         │ product-service (400ms)                                 │
        # │                             ├──────────────────┬──────────────────────────────────────┤
        # │                             │ db-query (100ms) │ cache-update (250ms)                 │
        # └─────────────────────────────┴──────────────────┴──────────────────────────────────────┘
    """
    if not hierarchy or not hierarchy.get("roots"):
        return "No hierarchy data"

    total_duration = hierarchy.get("total_duration_ms", 0)
    if total_duration <= 0:
        # Calculate from roots
        total_duration = sum(root.get("duration_ms", 0) or 0 for root in hierarchy.get("roots", []))
    if total_duration <= 0:
        total_duration = 1  # Avoid division by zero

    lines = []
    colors = [
        "\033[44m",  # Blue
        "\033[42m",  # Green
        "\033[43m",  # Yellow
        "\033[45m",  # Magenta
        "\033[46m",  # Cyan
        "\033[41m",  # Red (for errors)
    ]
    reset = "\033[0m"

    def get_color(depth: int, has_error: bool) -> str:
        if not use_colors:
            return ""
        if has_error:
            return colors[5]  # Red for errors
        return colors[depth % 5]

    def format_duration(ms: Optional[float]) -> str:
        if ms is None or ms <= 0:
            return ""
        if ms < 1000:
            return f"{ms:.0f}ms"
        return f"{ms/1000:.2f}s"

    # Build layers by depth
    max_depth = hierarchy.get("max_depth", 0)
    layers: List[List[Dict[str, Any]]] = [[] for _ in range(max_depth + 1)]

    def collect_by_depth(node: Dict[str, Any], offset: float = 0):
        depth = node.get("depth", 0)
        duration = node.get("duration_ms", 0) or 0
        node_info = {
            "id": node.get("id", "unknown"),
            "duration": duration,
            "offset": offset,
            "has_error": node.get("error_count", 0) > 0,
            "is_bottleneck": node.get("id") == hierarchy.get("bottleneck", {}).get("node_id"),
        }
        layers[depth].append(node_info)

        child_offset = offset
        for child in node.get("children", []):
            collect_by_depth(child, child_offset)
            child_offset += child.get("duration_ms", 0) or 0

    # Collect all nodes
    for root in hierarchy.get("roots", []):
        collect_by_depth(root)

    # Header
    lines.append("=" * width)
    lines.append("🔥 FLAMEGRAPH VISUALIZATION")
    lines.append("=" * width)
    lines.append(f"Total Duration: {format_duration(total_duration)}")
    lines.append("")

    # Draw each layer
    for depth, layer in enumerate(layers):
        if not layer:
            continue

        layer_line = []

        for node in layer:
            # Calculate width proportional to duration
            proportion = node["duration"] / total_duration if total_duration > 0 else 0
            span_width = max(min_width, int(proportion * (width - 2)))

            # Truncate label if needed
            label = node["id"]
            duration_str = format_duration(node["duration"])
            full_label = f"{label} ({duration_str})" if duration_str else label

            if len(full_label) > span_width - 2:
                full_label = full_label[: span_width - 4] + ".."

            # Create the span block
            color = get_color(depth, node["has_error"])
            end_color = reset if use_colors else ""

            # Bottleneck indicator
            if node["is_bottleneck"]:
                full_label = f"⚠ {full_label}"

            # Center the label
            padding = span_width - len(full_label) - 2
            left_pad = padding // 2
            right_pad = padding - left_pad

            block = f"{color}│{' ' * left_pad}{full_label}{' ' * right_pad}│{end_color}"
            layer_line.append(block)

        if layer_line:
            # Top border for first layer
            if depth == 0:
                lines.append("┌" + "─" * (width - 2) + "┐")

            lines.append("".join(layer_line))

            # Add separator if there's a next layer
            if depth < len(layers) - 1 and layers[depth + 1]:
                sep_line = "├" + "─" * (width - 2) + "┤"
                lines.append(sep_line)

    # Bottom border
    lines.append("└" + "─" * (width - 2) + "┘")

    # Legend
    lines.append("")
    lines.append("Legend:")
    lines.append("  ⚠ = Bottleneck   Red = Error")
    lines.append("  Width proportional to duration")

    return "\n".join(lines)


def print_flamegraph(
    hierarchy: Dict[str, Any],
    width: int = 100,
    use_colors: bool = True,
):
    """
    Print flamegraph to console.

    Args:
        hierarchy: Hierarchy dictionary
        width: Width in characters
        use_colors: Use ANSI colors

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        print_flamegraph(hierarchy)
    """
    print(format_flamegraph(hierarchy, width, use_colors))
