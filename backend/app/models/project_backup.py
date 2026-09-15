from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StringConstraints, model_validator
from app.services.project_snapshot import MAX_DEPTH, MAX_NODES, MAX_TAGS, MAX_LINKS

Ref = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=80)]
Index = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
EXCLUDED = ["votes", "metrics", "history", "accounts", "credentials", "memberships", "operations"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    @model_validator(mode="after")
    def valid_postgres_text(self):
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, str):
                if "\x00" in value:
                    raise ValueError(f"{name}: NUL characters are not supported by PostgreSQL")
                try:
                    value.encode("utf-8")
                except UnicodeEncodeError:
                    raise ValueError(f"{name}: unpaired Unicode surrogate is not valid UTF-8") from None
        return self


class BackupProject(StrictModel):
    name: str = Field(min_length=1, max_length=120, strict=True)
    description: str | None = Field(default=None, strict=True)


class BackupNode(StrictModel):
    ref: Ref
    parent_ref: Ref | None
    content: str = Field(strict=True)
    state: Literal["ACTIVE", "GHOST", "ARCHIVED"]
    depth: int = Field(strict=True, ge=0, le=MAX_DEPTH)
    order_index: Index
    pos_x: FiniteFloat | None = Field(strict=True)
    pos_y: FiniteFloat | None = Field(strict=True)


class BackupTag(StrictModel):
    ref: Ref
    name: str = Field(strict=True, max_length=80)
    color: str | None = Field(default=None, strict=True, max_length=7)


class BackupLink(StrictModel):
    node_ref: Ref
    tag_ref: Ref


class DepthAdjustment(StrictModel):
    node_ref: Ref
    stored_depth: int = Field(strict=True)
    depth: int = Field(strict=True, ge=0, le=MAX_DEPTH)


class ProjectBackup(StrictModel):
    schema_version: Literal[1]
    exported_at: datetime
    project: BackupProject
    nodes: list[BackupNode] = Field(max_length=MAX_NODES)
    tags: list[BackupTag] = Field(max_length=MAX_TAGS)
    node_tags: list[BackupLink] = Field(max_length=MAX_LINKS)
    depth_adjustments: list[DepthAdjustment] = Field(default_factory=list, max_length=MAX_NODES)

    @model_validator(mode="after")
    def validate_graph(self):
        nodes = {n.ref: n for n in self.nodes}
        tags = {t.ref: t for t in self.tags}
        if len(nodes) != len(self.nodes): raise ValueError("nodes.ref: duplicate reference")
        if len(tags) != len(self.tags): raise ValueError("tags.ref: duplicate reference")
        if sum(n.state == "ACTIVE" and n.parent_ref is None for n in self.nodes) > 1:
            raise ValueError("nodes: at most one ACTIVE root is permitted")
        for i, n in enumerate(self.nodes):
            if n.parent_ref is None:
                if n.depth != 0: raise ValueError(f"nodes.{i}.depth: root depth must be zero")
            elif n.parent_ref not in nodes:
                raise ValueError(f"nodes.{i}.parent_ref: missing parent")
            elif n.depth != nodes[n.parent_ref].depth + 1:
                raise ValueError(f"nodes.{i}.depth: must be parent depth + 1 (cycles are invalid)")
        # Strict increasing depth rules out cycles without recursive traversal.
        links = set()
        for i, link in enumerate(self.node_tags):
            if link.node_ref not in nodes: raise ValueError(f"node_tags.{i}.node_ref: missing node")
            if link.tag_ref not in tags: raise ValueError(f"node_tags.{i}.tag_ref: missing tag")
            pair = (link.node_ref, link.tag_ref)
            if pair in links: raise ValueError(f"node_tags.{i}: duplicate relation")
            links.add(pair)
        adjusted = set()
        for i, item in enumerate(self.depth_adjustments):
            if item.node_ref not in nodes or item.node_ref in adjusted or item.depth != nodes[item.node_ref].depth:
                raise ValueError(f"depth_adjustments.{i}: invalid reference or depth")
            adjusted.add(item.node_ref)
        return self
