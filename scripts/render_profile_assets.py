#!/usr/bin/env python3
"""Render snake SVG assets for the GitHub profile README."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GRAPH_COLUMNS = 53
GRAPH_ROWS = 7
CELL_SIZE = 12
CELL_GAP = 4
CELL_STEP = CELL_SIZE + CELL_GAP

SNAKE_VIEWBOX = (0, 0, 880, 192)
SNAKE_GRID_ORIGIN = (18, 28)
SNAKE_DURATION = 28.0
SNAKE_SEGMENTS = (
    (0.8, 14.4, 4.6, "head"),
    (1.5, 13.0, 4.2, "body"),
    (2.2, 11.6, 3.8, "body"),
    (2.9, 10.2, 3.4, "body"),
    (3.5, 9.0, 3.0, "tail"),
    (4.1, 7.8, 2.6, "tail"),
)
FOOD_COUNT = 20
SNAKE_WAYPOINTS = (
    (0, 6),
    (4, 2),
    (10, 0),
    (16, 4),
    (22, 6),
    (28, 1),
    (34, 0),
    (40, 5),
    (46, 6),
    (52, 2),
    (52, 0),
    (48, 4),
    (42, 6),
    (36, 1),
    (30, 0),
    (24, 5),
    (18, 6),
    (12, 2),
    (6, 0),
    (0, 4),
)

PUBLIC_LEVEL_WEIGHTS = {0: 0, 1: 2, 2: 5, 3: 9, 4: 14}
GRAPHQL_LEVELS = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

SNAKE_PALETTES = {
    "light": {
        "bg0": "#04070D",
        "bg1": "#0A121C",
        "frame": "#7FA9BC",
        "frame_soft": "#1E2B38",
        "halo": "#62C8F4",
        "scan": "#DDF2FB",
        "sweep": "#F5FBFF",
        "grid": ("#0C1218", "#143349", "#1E4F68", "#2F728F", "#8BDFFF"),
        "snake_head": "#F6FCFF",
        "snake_body": "#D8F5FF",
        "snake_tail": "#8FCDE3",
        "snake_stroke": "#09212F",
        "food_core": "#F5FCFF",
        "food_glow": "#73DBFF",
    },
    "dark": {
        "bg0": "#020407",
        "bg1": "#081019",
        "frame": "#648191",
        "frame_soft": "#17212B",
        "halo": "#4AAAD0",
        "scan": "#D8EEF8",
        "sweep": "#EEF8FF",
        "grid": ("#070B10", "#102734", "#173B4D", "#245E77", "#6ECBEF"),
        "snake_head": "#F8FDFF",
        "snake_body": "#D9F6FF",
        "snake_tail": "#7CB7CB",
        "snake_stroke": "#071621",
        "food_core": "#F7FDFF",
        "food_glow": "#5DD4FF",
    },
}


@dataclass(frozen=True)
class ContributionDay:
    value_date: date
    level: int
    count: int


def fmt(number: float) -> str:
    text = f"{number:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def chunked_range(length: int) -> list[float]:
    if length <= 1:
        return [0.0]
    return [index / (length - 1) for index in range(length)]


def request_text(url: str, *, data: dict | None = None, headers: dict[str, str] | None = None) -> str:
    payload = None if data is None else json.dumps(data).encode("utf-8")
    request_headers = {"User-Agent": "bujhmml-profile-assets"}
    if headers:
        request_headers.update(headers)
    request = Request(url, data=payload, headers=request_headers)
    with urlopen(request) as response:
        return response.read().decode("utf-8")


def fetch_graphql_contributions(username: str, token: str) -> dict[date, ContributionDay]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=370)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays {
                contributionCount
                contributionLevel
                date
              }
            }
          }
        }
      }
    }
    """
    payload = {
        "query": query,
        "variables": {
            "login": username,
            "from": start.isoformat().replace("+00:00", "Z"),
            "to": now.isoformat().replace("+00:00", "Z"),
        },
    }
    body = request_text(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    parsed = json.loads(body)
    if parsed.get("errors"):
        raise RuntimeError(parsed["errors"][0]["message"])
    weeks = (
        parsed.get("data", {})
        .get("user", {})
        .get("contributionsCollection", {})
        .get("contributionCalendar", {})
        .get("weeks", [])
    )
    if not weeks:
        raise RuntimeError("GraphQL response did not include contribution weeks")

    data: dict[date, ContributionDay] = {}
    for week in weeks:
        for item in week.get("contributionDays", []):
            value_date = date.fromisoformat(item["date"])
            level = GRAPHQL_LEVELS.get(item["contributionLevel"], 0)
            count = int(item["contributionCount"])
            data[value_date] = ContributionDay(value_date=value_date, level=level, count=count)
    return data


def fetch_public_contributions(username: str) -> dict[date, ContributionDay]:
    data: dict[date, ContributionDay] = {}
    current_year = date.today().year
    today = date.today()
    for year in (current_year - 1, current_year):
        html = request_text(
            f"https://github.com/users/{username}/contributions?from={year}-01-01&to={year}-12-31"
        )
        matches = re.findall(
            r'data-date="([^"]+)"[^>]*id="([^"]+)"[^>]*data-level="([^"]+)"',
            html,
        )
        if not matches:
            continue

        counts_by_id: dict[str, int] = {}
        for component_id, tooltip_text in re.findall(
            r'for="([^"]+)"[^>]*>([^<]+)</tool-tip>',
            html,
        ):
            count_match = re.search(r"(\d+) contributions?", tooltip_text)
            counts_by_id[component_id] = int(count_match.group(1)) if count_match else 0

        for value, component_id, raw_level in matches:
            value_date = date.fromisoformat(value)
            if value_date > today:
                continue
            level = int(raw_level)
            count = counts_by_id.get(component_id, PUBLIC_LEVEL_WEIGHTS[level])
            data[value_date] = ContributionDay(value_date=value_date, level=level, count=count)

    if not data:
        raise RuntimeError("Could not parse contribution days from the public contribution graph")
    return data


def build_weeks(days: dict[date, ContributionDay]) -> list[list[ContributionDay]]:
    if not days:
        raise RuntimeError("No contribution data was loaded")

    first_day = min(days)
    last_day = max(days)
    first_sunday = first_day - timedelta(days=int(first_day.strftime("%w")))
    last_saturday = last_day + timedelta(days=6 - int(last_day.strftime("%w")))

    weeks: list[list[ContributionDay]] = []
    cursor = first_sunday
    while cursor <= last_saturday:
        week: list[ContributionDay] = []
        for offset in range(GRAPH_ROWS):
            value_date = cursor + timedelta(days=offset)
            week.append(days.get(value_date, ContributionDay(value_date=value_date, level=0, count=0)))
        weeks.append(week)
        cursor += timedelta(days=7)

    if len(weeks) > GRAPH_COLUMNS:
        weeks = weeks[-GRAPH_COLUMNS:]

    while len(weeks) < GRAPH_COLUMNS:
        filler_start = weeks[0][0].value_date - timedelta(days=7)
        weeks.insert(
            0,
            [
                ContributionDay(value_date=filler_start + timedelta(days=offset), level=0, count=0)
                for offset in range(GRAPH_ROWS)
            ],
        )

    return weeks


def load_contribution_weeks(username: str) -> list[list[ContributionDay]]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    errors: list[str] = []

    if token:
        try:
            return build_weeks(fetch_graphql_contributions(username, token))
        except (RuntimeError, HTTPError, URLError, KeyError, ValueError) as exc:
            errors.append(f"GraphQL fallback triggered: {exc}")

    try:
        return build_weeks(fetch_public_contributions(username))
    except (RuntimeError, HTTPError, URLError, ValueError) as exc:
        errors.append(f"Public HTML fallback failed: {exc}")

    raise RuntimeError("; ".join(errors))


def walk_axis(current: int, target: int) -> Iterable[int]:
    step = 1 if target > current else -1
    return range(current + step, target + step, step)


def connect_cells(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    horizontal_first: bool,
) -> list[tuple[int, int]]:
    column, row = start
    target_column, target_row = end
    path = [start]

    def move_horizontal() -> None:
        nonlocal column
        for next_column in walk_axis(column, target_column):
            column = next_column
            path.append((column, row))

    def move_vertical() -> None:
        nonlocal row
        for next_row in walk_axis(row, target_row):
            row = next_row
            path.append((column, row))

    if column != target_column or row != target_row:
        if horizontal_first:
            if column != target_column:
                move_horizontal()
            if row != target_row:
                move_vertical()
        else:
            if row != target_row:
                move_vertical()
            if column != target_column:
                move_horizontal()

    return path


def snake_path() -> list[tuple[int, int]]:
    anchors = list(SNAKE_WAYPOINTS)
    path = [anchors[0]]
    for index, target in enumerate(anchors[1:] + anchors[:1]):
        segment = connect_cells(path[-1], target, horizontal_first=index % 2 == 0)
        path.extend(segment[1:])
    if path[-1] == path[0]:
        path.pop()
    return path


def score_food_candidate(day: ContributionDay, row: int, centre_row: float) -> tuple[int, int, int, float]:
    row_bias = -abs(row - centre_row)
    return (1 if day.level > 0 else 0, day.level, day.count, row_bias)


def active_food_indices(weeks: list[list[ContributionDay]], path: list[tuple[int, int]]) -> list[int]:
    path_length = len(path)
    unique_path: list[tuple[int, int, int]] = []
    seen_cells: set[tuple[int, int]] = set()
    for index, (column, row) in enumerate(path):
        cell = (column, row)
        if cell in seen_cells:
            continue
        seen_cells.add(cell)
        unique_path.append((index, column, row))

    if len(unique_path) <= FOOD_COUNT:
        return [index for index, _, _ in unique_path]

    window = path_length / FOOD_COUNT
    radius = max(10, int(window * 0.72))
    centre_offset = window * 0.58
    picked: list[int] = []
    used_cells: set[tuple[int, int]] = set()

    def well_spaced(column: int, row: int) -> bool:
        return all(abs(column - used_column) + abs(row - used_row) >= 4 for used_column, used_row in used_cells)

    for slot in range(FOOD_COUNT):
        centre = int(round((slot * window + centre_offset) % path_length))
        centre_row = 1.5 + ((slot * 3) % GRAPH_ROWS)
        candidates = []
        for index, column, row in unique_path:
            cyclic_distance = min((index - centre) % path_length, (centre - index) % path_length)
            if cyclic_distance > radius or (column, row) in used_cells or not well_spaced(column, row):
                continue
            day = weeks[column][row]
            score = score_food_candidate(day, row, centre_row)
            candidates.append((score, -cyclic_distance, index, column, row))

        if not candidates:
            for index, column, row in unique_path:
                if (column, row) in used_cells or not well_spaced(column, row):
                    continue
                cyclic_distance = min((index - centre) % path_length, (centre - index) % path_length)
                score = score_food_candidate(weeks[column][row], row, centre_row)
                candidates.append((score, -cyclic_distance, index, column, row))

        if not candidates:
            for index, column, row in unique_path:
                if (column, row) in used_cells:
                    continue
                cyclic_distance = min((index - centre) % path_length, (centre - index) % path_length)
                score = score_food_candidate(weeks[column][row], row, centre_row)
                candidates.append((score, -cyclic_distance, index, column, row))

        _, _, index, column, row = max(candidates)
        picked.append(index)
        used_cells.add((column, row))

    return sorted(picked)


def snake_translate(column: int, row: int, inset: float) -> tuple[float, float]:
    grid_x, grid_y = SNAKE_GRID_ORIGIN
    return (
        grid_x + column * CELL_STEP - inset,
        grid_y + row * CELL_STEP - inset,
    )


def cell_rect(column: int, row: int) -> tuple[float, float]:
    grid_x, grid_y = SNAKE_GRID_ORIGIN
    return (
        grid_x + column * CELL_STEP,
        grid_y + row * CELL_STEP,
    )


def animate_transform(values: Iterable[tuple[float, float]], duration: float) -> str:
    value_list = list(values)
    serialised = ";".join(f"{fmt(x)} {fmt(y)}" for x, y in value_list)
    key_times = ";".join(fmt(point) for point in chunked_range(len(value_list)))
    return (
        f'<animateTransform attributeName="transform" type="translate" dur="{fmt(duration)}s" '
        f'repeatCount="indefinite" calcMode="linear" values="{serialised}" keyTimes="{key_times}"/>'
    )


def render_snake(weeks: list[list[ContributionDay]], variant: str, output_path: Path) -> None:
    palette = SNAKE_PALETTES[variant]
    vx, vy, width, height = SNAKE_VIEWBOX
    grid_width = GRAPH_COLUMNS * CELL_STEP - CELL_GAP
    grid_height = GRAPH_ROWS * CELL_STEP - CELL_GAP
    path = snake_path()
    path_length = len(path)

    grid_cells = []
    for column, week in enumerate(weeks):
        for row, day in enumerate(week):
            x, y = cell_rect(column, row)
            grid_cells.append(
                f'<rect class="cell l{day.level}" x="{fmt(x)}" y="{fmt(y)}" width="{CELL_SIZE}" '
                f'height="{CELL_SIZE}" rx="2" ry="2"/>'
            )

    segment_nodes = []
    for offset, size, radius, role in SNAKE_SEGMENTS:
        positions = [snake_translate(column, row, offset) for column, row in path]
        positions.append(positions[0])
        lag = int(math.ceil(offset * 1.7))
        shifted = positions[-(lag + 1) : -1] + positions[:-lag] if lag else positions
        if len(shifted) != len(positions):
            shifted = positions
        fill_class = "snake-head" if role == "head" else "snake-tail" if role == "tail" else "snake-body"
        segment_nodes.append(
            f'<rect class="snake {fill_class}" x="{fmt(offset)}" y="{fmt(offset)}" '
            f'width="{fmt(size)}" height="{fmt(size)}" rx="{fmt(radius)}" ry="{fmt(radius)}">'
            f"{animate_transform(shifted, SNAKE_DURATION)}</rect>"
        )

    food_nodes = []
    for slot, index in enumerate(active_food_indices(weeks, path)):
        column, row = path[index]
        x, y = cell_rect(column, row)
        cx = x + CELL_SIZE / 2
        cy = y + CELL_SIZE / 2
        arrival = index / path_length
        vanish_start = max(0.0, arrival - 0.012)
        vanish_end = min(1.0, arrival + 0.022)
        pulse = 4.6 + (slot % 4) * 0.25
        food_nodes.append(
            f'<g class="food" transform="translate({fmt(cx)} {fmt(cy)})">'
            f'<circle class="food-halo" r="{fmt(pulse)}">'
            f'<animate attributeName="opacity" dur="{fmt(SNAKE_DURATION)}s" repeatCount="indefinite" '
            f'values="0.18;0.62;0;0" keyTimes="0;{fmt(vanish_start)};{fmt(vanish_end)};1"/>'
            f'<animate attributeName="r" dur="{fmt(SNAKE_DURATION)}s" repeatCount="indefinite" '
            f'values="{fmt(pulse + 1.3)};{fmt(pulse)};{fmt(max(1.4, pulse - 1.9))};{fmt(max(1.4, pulse - 1.9))}" '
            f'keyTimes="0;{fmt(vanish_start)};{fmt(vanish_end)};1"/></circle>'
            f'<circle class="food-core" r="2.35">'
            f'<animate attributeName="opacity" dur="{fmt(SNAKE_DURATION)}s" repeatCount="indefinite" '
            f'values="0.42;1;0;0" keyTimes="0;{fmt(vanish_start)};{fmt(vanish_end)};1"/>'
            f'</circle></g>'
        )

    star_nodes = []
    for cx, cy, radius, duration, delay in (
        (92, 22, 1.1, 6.3, 0.0),
        (208, 18, 1.3, 7.1, 1.2),
        (324, 26, 1.0, 5.8, 2.0),
        (488, 16, 1.2, 6.7, 0.7),
        (656, 24, 1.1, 7.4, 1.8),
        (782, 18, 1.4, 6.0, 1.1),
    ):
        star_nodes.append(
            f'<circle class="star" cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(radius)}">'
            f'<animate attributeName="opacity" values="0.22;0.9;0.22" dur="{fmt(duration)}s" '
            f'begin="-{fmt(delay)}s" repeatCount="indefinite"/></circle>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vx} {vy} {width} {height}" preserveAspectRatio="xMidYMid meet" role="img" aria-labelledby="title desc">
  <title id="title">GitHub contribution snake</title>
  <desc id="desc">Animated GitHub contribution snake moving across the full contribution grid with distributed food targets.</desc>
  <defs>
    <linearGradient id="panel-bg" x1="{vx}" y1="{vy}" x2="{width}" y2="{height}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{palette['bg0']}"/>
      <stop offset="0.55" stop-color="{palette['bg1']}"/>
      <stop offset="1" stop-color="{palette['bg0']}"/>
    </linearGradient>
    <radialGradient id="panel-halo" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(700 46) rotate(90) scale(132 220)">
      <stop stop-color="{palette['halo']}" stop-opacity="0.18"/>
      <stop offset="0.52" stop-color="{palette['halo']}" stop-opacity="0.05"/>
      <stop offset="1" stop-color="{palette['halo']}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="panel-sweep" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{palette['sweep']}" stop-opacity="0"/>
      <stop offset="0.5" stop-color="{palette['sweep']}" stop-opacity="0.11"/>
      <stop offset="1" stop-color="{palette['sweep']}" stop-opacity="0"/>
    </linearGradient>
    <pattern id="scanlines" width="12" height="12" patternUnits="userSpaceOnUse">
      <rect width="12" height="12" fill="transparent"/>
      <path d="M0 2.5H12" stroke="{palette['scan']}" stroke-opacity="0.06"/>
    </pattern>
    <clipPath id="panel-clip">
      <rect x="{vx}" y="{vy}" width="{width}" height="{height}" rx="18" ry="18"/>
    </clipPath>
  </defs>
  <style>
    .cell{{shape-rendering:geometricPrecision;stroke:#000;stroke-opacity:0.12;stroke-width:1}}
    .cell.l0{{fill:{palette['grid'][0]}}}
    .cell.l1{{fill:{palette['grid'][1]}}}
    .cell.l2{{fill:{palette['grid'][2]}}}
    .cell.l3{{fill:{palette['grid'][3]}}}
    .cell.l4{{fill:{palette['grid'][4]}}}
    .snake{{shape-rendering:geometricPrecision;stroke:{palette['snake_stroke']};stroke-opacity:0.32;stroke-width:1}}
    .snake-head{{fill:{palette['snake_head']}}}
    .snake-body{{fill:{palette['snake_body']}}}
    .snake-tail{{fill:{palette['snake_tail']}}}
    .food-halo{{fill:{palette['food_glow']};opacity:0.28}}
    .food-core{{fill:{palette['food_core']}}}
    .star{{fill:{palette['food_core']};opacity:0.24}}
  </style>
  <g clip-path="url(#panel-clip)">
    <rect x="{vx}" y="{vy}" width="{width}" height="{height}" rx="18" ry="18" fill="url(#panel-bg)"/>
    <rect x="{vx}" y="{vy}" width="{width}" height="{height}" rx="18" ry="18" fill="url(#panel-halo)">
      <animate attributeName="opacity" values="0.08;0.18;0.08" dur="18s" repeatCount="indefinite"/>
    </rect>
    {''.join(star_nodes)}
    <g opacity="0.2">
      <rect x="{vx}" y="{vy}" width="{width}" height="{height}" rx="18" ry="18" fill="url(#scanlines)">
        <animateTransform attributeName="transform" type="translate" values="0 0;0 7;0 0" dur="20s" repeatCount="indefinite"/>
      </rect>
    </g>
    <rect x="18" y="144" width="{grid_width}" height="18" rx="9" fill="{palette['frame_soft']}" opacity="0.36"/>
    <rect x="18" y="144" width="{grid_width}" height="18" rx="9" fill="none" stroke="{palette['frame']}" stroke-opacity="0.12"/>
    <g>
      {''.join(grid_cells)}
    </g>
    <g>
      {''.join(food_nodes)}
    </g>
    <g>
      {''.join(segment_nodes)}
    </g>
    <rect x="-190" y="-88" width="180" height="{height * 2}" fill="url(#panel-sweep)" opacity="0.12" transform="rotate(12 440 96)">
      <animate attributeName="x" values="-190;940;-190" dur="32s" repeatCount="indefinite"/>
    </rect>
  </g>
  <rect x="0.75" y="0.75" width="{width - 1.5}" height="{height - 1.5}" rx="17.25" fill="none" stroke="{palette['frame']}" stroke-opacity="0.45" stroke-width="1.5"/>
  <rect x="12" y="12" width="{width - 24}" height="{height - 24}" rx="12" fill="none" stroke="{palette['frame_soft']}" stroke-opacity="0.48" stroke-width="1"/>
</svg>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render GitHub profile snake SVG assets.")
    parser.add_argument(
        "target",
        choices=("snake",),
        help="Which asset set to generate.",
    )
    parser.add_argument(
        "--username",
        required=True,
        help="GitHub username to read contribution data for.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    weeks = load_contribution_weeks(args.username)

    if args.target == "snake":
        render_snake(weeks, "light", Path("dist/github-contribution-grid-snake.svg"))
        render_snake(weeks, "dark", Path("dist/github-contribution-grid-snake-dark.svg"))

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI guardrail
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
