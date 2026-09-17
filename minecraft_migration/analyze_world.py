"""Mapeia chunks já gerados em um world.zip sem extrair o mundo."""

from __future__ import annotations

from collections import defaultdict, deque
import gzip
from io import BytesIO
import json
import math
from pathlib import Path
import re
from statistics import median
import struct
import sys
from zipfile import ZipFile


REGION_RE = re.compile(
    r"^world/(?:(?P<dimension>DIM-1|DIM1|dimensions/[^/]+/[^/]+)/)?"
    r"region/r\.(?P<x>-?\d+)\.(?P<z>-?\d+)\.mca$"
)


class NbtReader:
    def __init__(self, data: bytes) -> None:
        self.data = memoryview(data)
        self.offset = 0

    def take(self, size: int) -> bytes:
        value = self.data[self.offset : self.offset + size].tobytes()
        self.offset += size
        return value

    def number(self, fmt: str) -> int | float:
        return struct.unpack(">" + fmt, self.take(struct.calcsize(fmt)))[0]

    def string(self) -> str:
        return self.take(int(self.number("H"))).decode("utf-8")

    def payload(self, tag: int) -> object:
        if tag == 1:
            return self.number("b")
        if tag == 2:
            return self.number("h")
        if tag == 3:
            return self.number("i")
        if tag == 4:
            return self.number("q")
        if tag == 5:
            return self.number("f")
        if tag == 6:
            return self.number("d")
        if tag == 7:
            return list(self.take(int(self.number("i"))))
        if tag == 8:
            return self.string()
        if tag == 9:
            child_tag = int(self.number("B"))
            return [self.payload(child_tag) for _ in range(int(self.number("i")))]
        if tag == 10:
            result: dict[str, object] = {}
            while True:
                child_tag = int(self.number("B"))
                if child_tag == 0:
                    return result
                child_name = self.string()
                result[child_name] = self.payload(child_tag)
        if tag == 11:
            return [self.number("i") for _ in range(int(self.number("i")))]
        if tag == 12:
            return [self.number("q") for _ in range(int(self.number("i")))]
        raise ValueError(f"Tag NBT desconhecida: {tag}")

    def root(self) -> dict[str, object]:
        tag = int(self.number("B"))
        if tag != 10:
            raise ValueError("A raiz NBT não é um compound.")
        self.string()
        value = self.payload(tag)
        if not isinstance(value, dict):
            raise ValueError("NBT inválido.")
        return value


def read_nbt(compressed: bytes) -> dict[str, object]:
    return NbtReader(gzip.decompress(compressed)).root()


def dimension_name(value: str | None) -> str:
    return {None: "overworld", "DIM-1": "nether", "DIM1": "end"}.get(
        value, value or "overworld"
    )


def components(chunks: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    remaining = set(chunks)
    result: list[set[tuple[int, int]]] = []
    neighbors = tuple(
        (dx, dz)
        for dx in (-1, 0, 1)
        for dz in (-1, 0, 1)
        if dx or dz
    )
    while remaining:
        first = remaining.pop()
        component = {first}
        queue = deque((first,))
        while queue:
            x, z = queue.popleft()
            for dx, dz in neighbors:
                candidate = (x + dx, z + dz)
                if candidate in remaining:
                    remaining.remove(candidate)
                    component.add(candidate)
                    queue.append(candidate)
        result.append(component)
    return sorted(result, key=len, reverse=True)


def bounds(chunks: set[tuple[int, int]]) -> dict[str, object]:
    xs = [chunk[0] for chunk in chunks]
    zs = [chunk[1] for chunk in chunks]
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)
    min_block_x, max_block_x = min_x * 16, max_x * 16 + 15
    min_block_z, max_block_z = min_z * 16, max_z * 16 + 15
    center_x = (min_block_x + max_block_x) // 2
    center_z = (min_block_z + max_block_z) // 2
    radius = max(
        center_x - min_block_x,
        max_block_x - center_x,
        center_z - min_block_z,
        max_block_z - center_z,
    )
    return {
        "chunks": len(chunks),
        "chunk_bounds": [min_x, min_z, max_x, max_z],
        "block_bounds": [min_block_x, min_block_z, max_block_x, max_block_z],
        "center_blocks": [center_x, center_z],
        "minimum_square_radius_blocks": radius,
    }


def coverage(chunks: set[tuple[int, int]], center_x: int, center_z: int, radius: int) -> dict[str, object]:
    min_chunk_x = math.floor((center_x - radius) / 16)
    max_chunk_x = math.floor((center_x + radius) / 16)
    min_chunk_z = math.floor((center_z - radius) / 16)
    max_chunk_z = math.floor((center_z + radius) / 16)
    square_total = 0
    square_generated = 0
    circle_total = 0
    circle_generated = 0
    for chunk_x in range(min_chunk_x, max_chunk_x + 1):
        for chunk_z in range(min_chunk_z, max_chunk_z + 1):
            generated = (chunk_x, chunk_z) in chunks
            square_total += 1
            square_generated += int(generated)
            block_x, block_z = chunk_x * 16 + 8, chunk_z * 16 + 8
            if (block_x - center_x) ** 2 + (block_z - center_z) ** 2 <= radius**2:
                circle_total += 1
                circle_generated += int(generated)
    return {
        "radius_blocks": radius,
        "circle_chunks": circle_total,
        "circle_already_generated": circle_generated,
        "circle_coverage_percent": round(circle_generated * 100 / circle_total, 1),
        "square_chunks": square_total,
        "square_already_generated": square_generated,
        "square_coverage_percent": round(square_generated * 100 / square_total, 1),
    }


def analyze(path: Path) -> dict[str, object]:
    by_dimension: dict[str, set[tuple[int, int]]] = defaultdict(set)
    region_files: dict[str, int] = defaultdict(int)
    invalid_regions: list[str] = []
    world_metadata: dict[str, object] = {}
    players: list[dict[str, object]] = []
    with ZipFile(path) as archive:
        level_entry = archive.getinfo("world/level.dat")
        level = read_nbt(archive.read(level_entry)).get("Data", {})
        if isinstance(level, dict):
            version = level.get("Version", {})
            world_metadata = {
                "spawn_blocks": [level.get("SpawnX"), level.get("SpawnY"), level.get("SpawnZ")],
                "level_name": level.get("LevelName"),
                "data_version": level.get("DataVersion"),
                "minecraft_version": version.get("Name") if isinstance(version, dict) else None,
            }
        for info in archive.infolist():
            if not re.match(r"^world/playerdata/[0-9a-f-]+\.dat$", info.filename):
                continue
            player = read_nbt(archive.read(info))
            position = player.get("Pos", [])
            players.append({
                "uuid": Path(info.filename).stem,
                "dimension": player.get("Dimension"),
                "position_blocks": [round(float(value), 1) for value in position]
                if isinstance(position, list) else [],
            })
        for info in archive.infolist():
            match = REGION_RE.match(info.filename)
            if not match or info.file_size == 0:
                continue
            dimension = dimension_name(match.group("dimension"))
            region_x, region_z = int(match.group("x")), int(match.group("z"))
            with archive.open(info) as region:
                header = region.read(4096)
            if len(header) != 4096:
                invalid_regions.append(info.filename)
                continue
            region_files[dimension] += 1
            for index in range(1024):
                location = header[index * 4 : index * 4 + 4]
                if location != b"\x00\x00\x00\x00":
                    local_x, local_z = index % 32, index // 32
                    by_dimension[dimension].add(
                        (region_x * 32 + local_x, region_z * 32 + local_z)
                    )

    dimensions: dict[str, object] = {}
    for dimension, chunks in sorted(by_dimension.items()):
        groups = components(chunks)
        dimensions[dimension] = {
            "region_files": region_files[dimension],
            "all_generated": bounds(chunks),
            "connected_areas": [bounds(group) for group in groups[:12]],
            "connected_area_count": len(groups),
        }
    candidate_centers: dict[str, object] = {}
    overworld_chunks = by_dimension.get("overworld", set())
    spawn = world_metadata.get("spawn_blocks", [])
    overworld_players = [
        item["position_blocks"]
        for item in players
        if item.get("dimension") == "minecraft:overworld" and item.get("position_blocks")
    ]
    centers: dict[str, tuple[int, int]] = {}
    if isinstance(spawn, list) and len(spawn) == 3:
        centers["spawn"] = (int(spawn[0]), int(spawn[2]))
    if overworld_players:
        centers["median_player_position"] = (
            round(median(position[0] for position in overworld_players)),
            round(median(position[2] for position in overworld_players)),
        )
    for label, (center_x, center_z) in centers.items():
        candidate_centers[label] = {
            "center_blocks": [center_x, center_z],
            "coverage": [
                coverage(overworld_chunks, center_x, center_z, radius)
                for radius in (512, 1024, 1536, 2048, 3072, 4096)
            ],
        }
    return {
        "world_zip": str(path.resolve()),
        "metadata": world_metadata,
        "players": players,
        "candidate_centers": candidate_centers,
        "dimensions": dimensions,
        "invalid": invalid_regions,
    }


if __name__ == "__main__":
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("world-aternos-original.zip")
    print(json.dumps(analyze(source), ensure_ascii=False, indent=2))
