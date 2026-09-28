from __future__ import annotations

import math
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from database.database import GraphNode, GraphSnapshot


class GraphRenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class _NodeLayout:
    node: GraphNode
    canonical_lines: tuple[str, ...]
    alias_lines: tuple[str, ...]
    height: int


CARD_WIDTH = 250
CARD_GAP_X = 64
LAYER_GAP_Y = 100
MARGIN = 56
HEADER_HEIGHT = 92
MAX_IMAGE_PIXELS = 40_000_000


FONT_CANDIDATES = (
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
)


def _font(size: int):
    configured = os.environ.get("GRAPH_FONT_PATH", "").strip()
    candidates = ([configured] if configured else []) + list(FONT_CANDIDATES)
    for candidate in candidates:
        if not Path(candidate).is_file():
            continue
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    raise GraphRenderError(
        "A Japanese TrueType font was not found; set GRAPH_FONT_PATH to a .ttf or .ttc file"
    )


def _wrap_text(text: str, font, max_width: int) -> tuple[str, ...]:
    lines: list[str] = []
    line = ""
    for character in text:
        if line and font.getlength(line + character) > max_width:
            lines.append(line)
            line = character
        else:
            line += character
    if line:
        lines.append(line)
    return tuple(lines)


def _layer_ranks(snapshot: GraphSnapshot) -> dict[int, int]:
    nodes_by_id = {node.id: node for node in snapshot.nodes}
    parents: dict[int, list[int]] = defaultdict(list)
    children: dict[int, list[int]] = defaultdict(list)
    for edge in snapshot.edges:
        if edge.predicate != "IS_A":
            continue
        if edge.subject_id not in nodes_by_id or edge.object_id not in nodes_by_id:
            continue
        parents[edge.subject_id].append(edge.object_id)
        children[edge.object_id].append(edge.subject_id)

    key = lambda node_id: nodes_by_id[node_id].canonical_name
    ranks: dict[int, int] = {}
    roots = sorted((node_id for node_id in nodes_by_id if not parents[node_id]), key=key)
    pending = deque(roots)
    for node_id in roots:
        ranks[node_id] = 0
    while pending:
        parent_id = pending.popleft()
        for child_id in sorted(children[parent_id], key=key):
            if child_id in ranks:
                continue
            ranks[child_id] = ranks[parent_id] + 1
            pending.append(child_id)

    while len(ranks) < len(nodes_by_id):
        remaining = sorted((node_id for node_id in nodes_by_id if node_id not in ranks), key=key)
        start_id = remaining[0]
        ranks[start_id] = max(ranks.values(), default=-1) + 1
        pending.append(start_id)
        while pending:
            parent_id = pending.popleft()
            for child_id in sorted(children[parent_id], key=key):
                if child_id in ranks:
                    continue
                ranks[child_id] = ranks[parent_id] + 1
                pending.append(child_id)
    return ranks


def _prepare_nodes(snapshot: GraphSnapshot, regular_font, alias_font) -> dict[int, _NodeLayout]:
    prepared = {}
    text_width = CARD_WIDTH - 32
    for node in snapshot.nodes:
        canonical_lines = _wrap_text(node.canonical_name, regular_font, text_width)
        aliases = [word for word in node.words if word != node.canonical_name]
        alias_lines = _wrap_text(" ・ ".join(aliases), alias_font, text_width) if aliases else ()
        height = 24 + len(canonical_lines) * 30 + len(alias_lines) * 22 + 18
        prepared[node.id] = _NodeLayout(
            node=node,
            canonical_lines=canonical_lines,
            alias_lines=alias_lines,
            height=max(82, height),
        )
    return prepared


def _edge_endpoints(source: tuple[float, float], target: tuple[float, float], source_height: int, target_height: int):
    dx = target[0] - source[0]
    dy = target[1] - source[1]
    if dx == 0 and dy == 0:
        return source, target
    scale = min(
        (CARD_WIDTH / 2) / abs(dx) if dx else math.inf,
        (source_height / 2) / abs(dy) if dy else math.inf,
    )
    start = (source[0] + dx * scale, source[1] + dy * scale)
    end_scale = min(
        (CARD_WIDTH / 2) / abs(dx) if dx else math.inf,
        (target_height / 2) / abs(dy) if dy else math.inf,
    )
    end = (target[0] - dx * end_scale, target[1] - dy * end_scale)
    return start, end


def render_knowledge_graph(snapshot: GraphSnapshot) -> bytes:
    title_font = _font(29)
    regular_font = _font(21)
    alias_font = _font(15)
    edge_font = _font(13)
    prepared = _prepare_nodes(snapshot, regular_font, alias_font)

    if not prepared:
        width, height = 720, 220
        image = Image.new("RGB", (width, height), "#f3f6fa")
        draw = ImageDraw.Draw(image)
        draw.text((MARGIN, 28), "知識ネットワーク", fill="#172b4d", font=title_font)
        draw.text((MARGIN, 110), "表示する概念はありません。", fill="#53657d", font=regular_font)
        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    ranks = _layer_ranks(snapshot)
    layers: dict[int, list[int]] = defaultdict(list)
    for node_id, rank in ranks.items():
        layers[rank].append(node_id)
    node_by_id = {node.id: node for node in snapshot.nodes}
    for node_ids in layers.values():
        node_ids.sort(key=lambda node_id: node_by_id[node_id].canonical_name)

    max_columns = max(len(node_ids) for node_ids in layers.values())
    width = 2 * MARGIN + max_columns * CARD_WIDTH + (max_columns - 1) * CARD_GAP_X
    heights = {rank: max(prepared[node_id].height for node_id in node_ids) for rank, node_ids in layers.items()}
    node_positions: dict[int, tuple[float, float]] = {}
    node_boxes: dict[int, tuple[int, int, int, int]] = {}
    y = HEADER_HEIGHT
    for rank in sorted(layers):
        node_ids = layers[rank]
        layer_height = heights[rank]
        group_width = len(node_ids) * CARD_WIDTH + (len(node_ids) - 1) * CARD_GAP_X
        x = (width - group_width) // 2
        for column, node_id in enumerate(node_ids):
            layout = prepared[node_id]
            left = x + column * (CARD_WIDTH + CARD_GAP_X)
            top = y + (layer_height - layout.height) // 2
            node_boxes[node_id] = (left, top, left + CARD_WIDTH, top + layout.height)
            node_positions[node_id] = (left + CARD_WIDTH / 2, top + layout.height / 2)
        y += layer_height + LAYER_GAP_Y
    height = y - LAYER_GAP_Y + MARGIN
    if width * height > MAX_IMAGE_PIXELS:
        raise GraphRenderError(
            f"Graph image would be too large ({width}x{height}); reduce the database or render a smaller graph"
        )

    image = Image.new("RGB", (width, height), "#f3f6fa")
    draw = ImageDraw.Draw(image)
    draw.text((MARGIN, 20), "知識ネットワーク", fill="#172b4d", font=title_font)
    summary = f"概念 {len(snapshot.nodes)} ・ 有効な関係 {len(snapshot.edges)}"
    draw.text((MARGIN, 59), summary, fill="#53657d", font=alias_font)

    edge_colors = {
        "IS_A": "#5279a5",
        "SAME_AS": "#8a5ab5",
        "RELATED_TO": "#b0793a",
    }
    for edge in snapshot.edges:
        if edge.subject_id not in node_positions or edge.object_id not in node_positions:
            continue
        source_box = node_boxes[edge.subject_id]
        target_box = node_boxes[edge.object_id]
        start, end = _edge_endpoints(
            node_positions[edge.subject_id],
            node_positions[edge.object_id],
            source_box[3] - source_box[1],
            target_box[3] - target_box[1],
        )
        color = edge_colors.get(edge.predicate, "#6b8f71")
        draw.line((start, end), fill=color, width=3)
        if edge.predicate != "RELATED_TO":
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = max(math.hypot(dx, dy), 1.0)
            unit_x, unit_y = dx / length, dy / length
            base_x, base_y = end[0] - unit_x * 13, end[1] - unit_y * 13
            perpendicular_x, perpendicular_y = -unit_y * 6, unit_x * 6
            draw.polygon(
                [
                    end,
                    (base_x + perpendicular_x, base_y + perpendicular_y),
                    (base_x - perpendicular_x, base_y - perpendicular_y),
                ],
                fill=color,
            )
        label = edge.predicate
        label_box = draw.textbbox((0, 0), label, font=edge_font)
        label_width = label_box[2] - label_box[0]
        label_height = label_box[3] - label_box[1]
        mid_x, mid_y = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
        label_rect = (mid_x - label_width / 2 - 6, mid_y - label_height / 2 - 3,
                      mid_x + label_width / 2 + 6, mid_y + label_height / 2 + 3)
        draw.rounded_rectangle(label_rect, radius=5, fill="#f3f6fa")
        draw.text(
            (mid_x - label_width / 2 - label_box[0], mid_y - label_height / 2 - label_box[1]),
            label,
            fill=color,
            font=edge_font,
        )

    for node_id, layout in prepared.items():
        left, top, right, bottom = node_boxes[node_id]
        draw.rounded_rectangle(
            (left, top, right, bottom), radius=15, fill="#ffffff", outline="#9aabc0", width=2
        )
        center_x = left + CARD_WIDTH / 2
        line_y = top + 12
        for line in layout.canonical_lines:
            box = draw.textbbox((0, 0), line, font=regular_font)
            text_width = box[2] - box[0]
            draw.text(
                (center_x - text_width / 2 - box[0], line_y - box[1]),
                line,
                fill="#203653",
                font=regular_font,
            )
            line_y += 30
        if layout.alias_lines:
            line_y += 5
            for line in layout.alias_lines:
                box = draw.textbbox((0, 0), line, font=alias_font)
                text_width = box[2] - box[0]
                draw.text(
                    (center_x - text_width / 2 - box[0], line_y - box[1]),
                    line,
                    fill="#63748a",
                    font=alias_font,
                )
                line_y += 22

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
