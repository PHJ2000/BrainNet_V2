"""Portable content, never portable credentials or membership."""
from datetime import date
from typing import Literal
from pydantic import AwareDatetime, Field, model_validator
from app.models.project_backup import ProjectBackup, StrictModel, Ref


class SavedTask(StrictModel):
    ref: Ref
    node_ref: Ref | None = None
    title: str = Field(min_length=1, max_length=240)
    body: str = Field(max_length=12000)
    status: Literal["TODO", "DOING", "DONE", "CANCELED"]
    priority: Literal["LOW", "MEDIUM", "HIGH"]
    due_date: date | None = None
    created_at: AwareDatetime


class SavedDiscussion(StrictModel):
    ref: Ref | None = None
    node_ref: Ref | None = None
    body: str = Field(min_length=1, max_length=8000)
    resolved: bool
    created_at: AwareDatetime


class SavedSource(StrictModel):
    node_ref: Ref | None = None
    content: str = Field(max_length=4000)


class SavedProposal(StrictModel):
    mode: Literal["EXPAND", "SUMMARY", "ACTION"]
    instruction: str = Field(max_length=1000)
    sources: list[SavedSource] = Field(min_length=1, max_length=8)
    status: Literal["QUEUED", "RUNNING", "READY", "FAILED", "INTERRUPTED", "ACCEPTED", "CANCELED"]
    output: str | None = Field(default=None, max_length=12000)
    error_code: str | None = Field(default=None, max_length=80)
    task_ref: Ref | None = None
    created_at: AwareDatetime


class SavedReply(StrictModel):
    discussion_ref: Ref
    body: str = Field(min_length=1, max_length=8000)
    created_at: AwareDatetime


class SavedLink(StrictModel):
    source_ref: Ref
    target_ref: Ref
    label: str = Field(default="", max_length=120)


class SavedDependency(StrictModel):
    task_ref: Ref
    requires_ref: Ref


class WorkspaceBackup(StrictModel):
    schema_version: Literal[2]
    graph: ProjectBackup
    tasks: list[SavedTask] = Field(max_length=1000)
    discussions: list[SavedDiscussion] = Field(max_length=2000)
    proposals: list[SavedProposal] = Field(max_length=500)
    bookmarks: list[Ref] = Field(max_length=5000)
    replies: list[SavedReply] = Field(default_factory=list, max_length=5000)
    links: list[SavedLink] = Field(default_factory=list, max_length=10000)
    dependencies: list[SavedDependency] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def references(self):
        nodes = {row.ref for row in self.graph.nodes}
        tasks = {row.ref for row in self.tasks}
        if len(tasks) != len(self.tasks):
            raise ValueError("tasks: duplicate reference")
        threads = [row.ref for row in self.discussions if row.ref is not None]
        if len(set(threads)) != len(threads) or any(r.discussion_ref not in threads for r in self.replies):
            raise ValueError("replies: unknown or duplicate discussion reference")
        link_pairs = {(r.source_ref, r.target_ref) for r in self.links}
        if len({frozenset(pair) for pair in link_pairs}) != len(self.links) or any(a == b or a not in nodes or b not in nodes for a, b in link_pairs):
            raise ValueError("links: invalid reference")
        pairs = {(r.task_ref, r.requires_ref) for r in self.dependencies}
        if len(pairs) != len(self.dependencies) or any(a == b or a not in tasks or b not in tasks for a, b in pairs):
            raise ValueError("dependencies: invalid reference")
        graph = {ref: set() for ref in tasks}
        states = {r.ref: r.status for r in self.tasks}
        for a, b in pairs:
            graph[a].add(b)
            if states[a] == "DONE" and states[b] != "DONE":
                raise ValueError("completed task has unfinished prerequisite")
        # Bounded topological elimination, no recursive traversal of untrusted input.
        while graph:
            ready = {ref for ref, required in graph.items() if not required}
            if not ready:
                raise ValueError("dependencies: cycle")
            graph = {ref: required - ready for ref, required in graph.items() if ref not in ready}
        if len(set(self.bookmarks)) != len(self.bookmarks) or not set(self.bookmarks) <= nodes:
            raise ValueError("bookmarks: duplicate or unknown node")
        for row in [*self.tasks, *self.discussions, *(source for proposal in self.proposals for source in proposal.sources)]:
            if row.node_ref is not None and row.node_ref not in nodes:
                raise ValueError("unknown node reference")
        for proposal in self.proposals:
            if proposal.task_ref is not None and proposal.task_ref not in tasks:
                raise ValueError("unknown task reference")
            if proposal.status == "ACCEPTED" and not proposal.task_ref:
                raise ValueError("accepted proposal requires its task")
            if proposal.status in ("READY", "ACCEPTED") and not proposal.output:
                raise ValueError("completed proposal requires output")
        return self
